"""Bill Lens sandbox modes for the worker (owned by Person B).

Plug-in for apps/worker/main.py. Two lines in Person A's worker wire it in:

    from bill_modes import router as bill_router
    app.include_router(bill_router)

and the worker Dockerfile copies this file next to main.py. It adds `POST /run-bill`, so the
existing `/run` request model and its global JOB_LOCK are untouched.

Request: {job_id, mode: "parse_bill" | "code", inputs: [{name, b64}]}
Response: NDJSON lines in the same `{event, detail, data?}` shape as `/run`. The last line is
always `container_destroyed`; the line before it carries the result:
  parse_bill -> {"event": "bill_parsed", "data": {"parsed": {...}}}      (or bill_parse_failed)
  code       -> {"event": "code_result", "data": {exit_code, stdout, stderr, timed_out, duration_ms}}

Both modes use the proofbox-parse image (sandbox/code) with no network, a read-only root,
inputs mounted read-only at /inputs, 512 MB, 0.5 CPU and a 20 s wall clock (contract C4).
Only the trusted parse script's `instruction_ignored` events are forwarded as events. Output
of model-written code is returned as data and never becomes an event.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

WORKER_TOKEN = os.getenv("WORKER_TOKEN", "dev-secret-token")
IMAGE = os.getenv("BILL_SANDBOX_IMAGE", "proofbox-parse:latest")
RUNTIME = os.getenv("BILL_SANDBOX_RUNTIME", "runsc")
WORK_DIR = Path(os.getenv("BILL_WORK_DIR", "/tmp"))
TIMEOUT_S = int(os.getenv("BILL_SANDBOX_TIMEOUT_S", "20"))
MAX_PARALLEL = int(os.getenv("BILL_SANDBOX_PARALLEL", "2"))
MAX_INPUT_BYTES = 12 * 1024 * 1024
MAX_STDOUT = 4 * 1024 * 1024
MAX_STDERR = 64 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MODES = {"parse_bill", "code"}

router = APIRouter()
_slots: asyncio.Semaphore | None = None


class SandboxInput(BaseModel):
    name: str
    b64: str


class BillRunRequest(BaseModel):
    job_id: str
    mode: str
    inputs: list[SandboxInput] = Field(default_factory=list)


def _line(event_type: str, detail: str, data: dict | None = None) -> str:
    payload: dict = {"event": event_type, "detail": detail}
    if data is not None:
        payload["data"] = data
    return json.dumps(payload, ensure_ascii=False) + "\n"


def decode_inputs(inputs: list[SandboxInput]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    for item in inputs:
        if not NAME_RE.match(item.name) or item.name in files:
            raise ValueError(f"Invalid input name: {item.name[:40]!r}")
        try:
            data = base64.b64decode(item.b64, validate=True)
        except ValueError as error:
            raise ValueError(f"Input {item.name} is not valid base64") from error
        total += len(data)
        if total > MAX_INPUT_BYTES:
            raise ValueError("Inputs exceed the size limit")
        files[item.name] = data
    return files


def validate_request(request: BillRunRequest) -> dict[str, bytes]:
    if request.mode not in MODES:
        raise ValueError(f"Unknown Bill mode: {request.mode[:40]!r}")
    files = decode_inputs(request.inputs)
    required = "bill.pdf" if request.mode == "parse_bill" else "main.py"
    if required not in files:
        raise ValueError(f"Missing input {required}")
    return files


def docker_command(container: str, mode: str, input_dir: Path) -> list[str]:
    command = ["docker", "run", "--name", container, "--rm"]
    if RUNTIME:
        command.append(f"--runtime={RUNTIME}")
    command += [
        "--network", "none", "--read-only", "--cap-drop=ALL",
        "--security-opt", "no-new-privileges",
        "--memory=512m", "--memory-swap=512m", "--cpus=0.5", "--pids-limit=64",
        "--tmpfs", "/tmp:size=64m",
        "--label", "proofbox.owner=b",
        "-v", f"{input_dir}:/inputs:ro",
        IMAGE,
    ]
    if mode == "parse_bill":
        command += ["python", "/app/parse_bill.py", "/inputs/bill.pdf"]
    else:
        command += ["python", "-I", "/inputs/main.py"]
    return command


def parse_result_lines(out_text: str, err_text: str, exit_code: int) -> list[str]:
    try:
        parsed = json.loads(out_text.strip().splitlines()[-1]) if out_text.strip() else None
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict) or parsed.get("status") != "ok":
        reason = parsed.get("error") if isinstance(parsed, dict) else None
        return [_line("bill_parse_failed", reason or f"Parser exited with code {exit_code}: {err_text[-300:]}")]
    lines = []
    for item in parsed.get("events", []):
        if item.get("type") == "instruction_ignored":
            lines.append(_line("instruction_ignored", str(item.get("message", ""))[:400], item.get("data")))
    pages = (parsed.get("input") or {}).get("pages")
    lines.append(_line("bill_parsed", f"Read {pages} page(s) of bill text in the sandbox", {"parsed": parsed}))
    return lines


def _cleanup(input_dir: Path) -> None:
    if not input_dir.exists():
        return
    for path in input_dir.iterdir():
        path.chmod(0o644)
    input_dir.chmod(0o755)
    shutil.rmtree(input_dir, ignore_errors=True)


async def run_bill_mode(request: BillRunRequest, files: dict[str, bytes]) -> AsyncIterator[str]:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(MAX_PARALLEL)
    async with _slots:
        safe_job = re.sub(r"[^a-zA-Z0-9-]", "", request.job_id)[:24] or "job"
        container = f"pb-{safe_job}-code-{uuid.uuid4().hex[:6]}"
        input_dir = WORK_DIR / f"pb_bill_{container}_in"
        process = None
        try:
            input_dir.mkdir(parents=True, exist_ok=False)
            for name, data in files.items():
                path = input_dir / name
                path.write_bytes(data)
                path.chmod(0o444)
            input_dir.chmod(0o555)

            yield _line("container_started", f"Started isolated sandbox {container} (no network, read-only inputs)")
            started = time.monotonic()
            timed_out = False
            process = await asyncio.create_subprocess_exec(
                *docker_command(container, request.mode, input_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=TIMEOUT_S)
            except asyncio.TimeoutError:
                timed_out = True
                kill = await asyncio.create_subprocess_exec("docker", "rm", "-f", container)
                await kill.communicate()
                stdout, stderr = await process.communicate()
                yield _line("timeout_kill", f"Blocked: sandbox exceeded the {TIMEOUT_S}s limit")
            duration_ms = int((time.monotonic() - started) * 1000)
            exit_code = -1 if timed_out else process.returncode
            if exit_code == 137:
                yield _line("memory_kill", "Blocked: sandbox exceeded its memory limit")
            out_text = stdout[:MAX_STDOUT].decode("utf-8", "replace")
            err_text = stderr[:MAX_STDERR].decode("utf-8", "replace")

            if request.mode == "parse_bill":
                for line in parse_result_lines(out_text, err_text, exit_code):
                    yield line
            else:
                yield _line(
                    "code_result",
                    f"Analyst program finished with exit code {exit_code}",
                    {"exit_code": exit_code, "stdout": out_text, "stderr": err_text, "timed_out": timed_out, "duration_ms": duration_ms},
                )
        except Exception as error:  # noqa: BLE001 - every failure is reported to the caller as an event
            yield _line("worker_error", f"{type(error).__name__}: {str(error)[:300]}")
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            _cleanup(input_dir)
            yield _line("container_destroyed", f"Sandbox {container} and its input files removed")


@router.post("/run-bill")
async def run_bill(request: BillRunRequest, authorization: str | None = Header(default=None)):
    if authorization != f"Bearer {WORKER_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        files = validate_request(request)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return StreamingResponse(run_bill_mode(request, files), media_type="application/x-ndjson")
