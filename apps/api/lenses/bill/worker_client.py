"""API-side client for the worker's Bill sandbox (`POST /run-bill`, see apps/worker/bill_modes.py).

Synchronous on purpose: the Bill pipeline runs in a thread (asyncio.to_thread) so it can call
the gateway and the sandbox without blocking Person A's queue loop.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable

import httpx

from .runners import RunResult, with_input_dir

# Sandbox lifecycle events forwarded to the job timeline. Result lines carry data only;
# instruction_ignored is emitted by the pipeline from the parse result.
FORWARDED_EVENTS = {"container_started", "container_destroyed", "timeout_kill", "memory_kill", "worker_error", "bill_parse_failed"}


class SandboxError(RuntimeError):
    pass


class WorkerClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or os.getenv("WORKER_URL", "http://10.99.0.3:8080")).rstrip("/")
        self.token = token or os.getenv("WORKER_TOKEN", "dev-secret-token")
        self.timeout_s = timeout_s
        self.transport = transport

    def run(
        self,
        job_id: str | None,
        mode: str,
        files: dict[str, bytes],
        emit: Callable[[str, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        body = {
            "job_id": job_id or "adhoc",
            "mode": mode,
            "inputs": [{"name": name, "b64": base64.b64encode(data).decode("ascii")} for name, data in files.items()],
        }
        lines: list[dict[str, Any]] = []
        with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/run-bill",
                json=body,
                headers={"Authorization": f"Bearer {self.token}"},
            ) as response:
                if response.status_code != 200:
                    response.read()
                    raise SandboxError(f"Worker refused the {mode} request (HTTP {response.status_code}): {response.text[:200]}")
                for raw in response.iter_lines():
                    if not raw.strip():
                        continue
                    message = json.loads(raw)
                    lines.append(message)
                    if emit and message.get("event") in FORWARDED_EVENTS:
                        emit(message["event"], str(message.get("detail", "")))
        return lines


class WorkerParser:
    """Runs sandbox/code/parse_bill.py on the PDF inside the worker's no-network sandbox."""

    def __init__(self, client: WorkerClient, job_id: str | None, emit: Callable[[str, str], None] | None = None):
        self.client, self.job_id, self.emit = client, job_id, emit

    def __call__(self, pdf: bytes) -> dict[str, Any]:
        lines = self.client.run(self.job_id, "parse_bill", {"bill.pdf": pdf}, self.emit)
        for message in lines:
            if message.get("event") == "bill_parsed":
                parsed = (message.get("data") or {}).get("parsed")
                if isinstance(parsed, dict):
                    return parsed
        failure = next((m.get("detail") for m in lines if m.get("event") in {"bill_parse_failed", "worker_error", "timeout_kill"}), None)
        raise SandboxError(failure or "The sandbox did not return a parse result")


class WorkerDocumentParser:
    """Extract text from a text-based PDF inside the no-network code sandbox."""

    def __init__(
        self,
        client: WorkerClient,
        job_id: str | None,
        emit: Callable[[str, str], None] | None = None,
    ):
        self.client, self.job_id, self.emit = client, job_id, emit

    def __call__(self, pdf: bytes) -> dict[str, Any]:
        lines = self.client.run(self.job_id, "parse_document", {"document.pdf": pdf}, self.emit)
        for message in lines:
            if message.get("event") == "document_parsed":
                document = (message.get("data") or {}).get("document")
                if isinstance(document, dict):
                    return document
        failure = next(
            (
                message.get("detail")
                for message in lines
                if message.get("event") in {
                    "document_parse_failed",
                    "worker_error",
                    "timeout_kill",
                }
            ),
            None,
        )
        raise SandboxError(failure or "The sandbox did not return extracted document text")


class WorkerCodeRunner:
    """CodeRunner backed by the worker's `code` mode. The analyst program never runs in the API."""

    def __init__(self, client: WorkerClient, job_id: str | None, emit: Callable[[str, str], None] | None = None):
        self.client, self.job_id, self.emit = client, job_id, emit

    def run(self, code: str, inputs: dict[str, object]) -> RunResult:
        executed = with_input_dir(code, "/inputs")
        files = {name: json.dumps(data, ensure_ascii=False).encode("utf-8") for name, data in inputs.items()}
        files["main.py"] = executed.encode("utf-8")
        lines = self.client.run(self.job_id, "code", files, self.emit)
        result = next(((m.get("data") or {}) for m in lines if m.get("event") == "code_result"), None)
        if result is None:
            detail = next((m.get("detail") for m in lines if m.get("event") == "worker_error"), "no result from sandbox")
            return RunResult(exit_code=-1, stdout="", stderr=str(detail), timed_out=False, duration_ms=0, executed_code=executed)
        return RunResult(
            exit_code=int(result.get("exit_code", -1)),
            stdout=str(result.get("stdout", "")),
            stderr=str(result.get("stderr", "")),
            timed_out=bool(result.get("timed_out")),
            duration_ms=int(result.get("duration_ms", 0)),
            executed_code=executed,
        )
