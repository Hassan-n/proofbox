import asyncio
import base64
import json
import os
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI()
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "dev-secret-token")
PROXY_LOG = Path(os.getenv("PROXY_LOG", "/tmp/proxy_logs/proxy_events.jsonl"))
JOB_LOCK = asyncio.Lock()


class JobRequest(BaseModel):
    job_id: str
    mode: str = "normal"
    url: str = ""


def event(event_type: str, detail: str, data: dict | None = None) -> str:
    payload = {"event": event_type, "detail": detail}
    if data:
        payload["data"] = data
    return json.dumps(payload) + "\n"


@app.post("/run")
async def run_job(request: JobRequest, authorization: str | None = Header(default=None)):
    if authorization != f"Bearer {WORKER_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    if request.mode == "link_lens" and not request.url:
        raise HTTPException(status_code=422, detail="A URL is required for Link Lens jobs")

    async def stream():
        async with JOB_LOCK:
            container_name = f"pb-job-{uuid.uuid4().hex[:8]}"
            output_dir = Path(f"/tmp/job_{container_name}_out")
            quarantine_dir = Path(f"/tmp/job_{container_name}_quar")
            output_dir.mkdir(parents=True, exist_ok=True)
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            output_dir.chmod(0o777)
            quarantine_dir.chmod(0o777)
            log_offset = PROXY_LOG.stat().st_size if PROXY_LOG.exists() else 0

            yield event("container_started", f"Started isolated container {container_name}")
            if request.mode == "link_lens":
                command = [
                    "docker", "run", "--name", container_name, "--rm",
                    "--runtime=runsc", "--network", "pb_internal",
                    "--read-only", "--cap-drop=ALL", "--security-opt", "no-new-privileges",
                    "--memory=1g", "--cpus=1.0", "--pids-limit=128",
                    "--tmpfs", "/tmp:size=256m", "--tmpfs", "/home/runner:size=64m",
                    "-e", "HTTP_PROXY=http://172.30.0.2:3128",
                    "-e", "HTTPS_PROXY=http://172.30.0.2:3128",
                    "-v", f"{output_dir}:/out", "-v", f"{quarantine_dir}:/quarantine",
                    "proofbox-browser:latest", request.url, "/out",
                ]
                timeout_seconds = 25
            else:
                py_code = "import time; time.sleep(100)" if request.mode == "timeout" else "print('ok')"
                command = [
                    "docker", "run", "--name", container_name, "--rm",
                    "--runtime=runsc", "--network", "none", "--read-only",
                    "--cap-drop=ALL", "--security-opt", "no-new-privileges",
                    "--memory=512m", "--cpus=0.5", "--pids-limit=64",
                    "python:3.12-slim", "python", "-c", py_code,
                ]
                timeout_seconds = 5

            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, _ = await asyncio.wait_for(
                        process.communicate(), timeout=timeout_seconds
                    )
                    if process.returncode == 137:
                        yield event("memory_kill", "Blocked: container exceeded its memory limit")
                except asyncio.TimeoutError:
                    yield event("timeout_kill", f"Blocked: container exceeded {timeout_seconds}s limit")
                    kill = await asyncio.create_subprocess_exec("docker", "rm", "-f", container_name)
                    await kill.communicate()
                    await process.communicate()
                if process.returncode == 0 and request.mode != "link_lens" and stdout:
                    yield event("container_output", stdout.decode(errors="replace")[:2000])

                if PROXY_LOG.exists():
                    with PROXY_LOG.open("r", encoding="utf-8") as proxy_log:
                        proxy_log.seek(log_offset)
                        for line in proxy_log:
                            if line.strip():
                                proxy_event = json.loads(line)
                                if proxy_event.get("event") == "network_blocked":
                                    yield event("network_blocked", proxy_event["detail"])

                trace_path = output_dir / "trace.json"
                if trace_path.exists():
                    trace = json.loads(trace_path.read_text(encoding="utf-8"))
                    for download in trace.get("downloads", []):
                        yield event(
                            "download_quarantined",
                            f"Quarantined '{download['filename']}' ({download['size_bytes']} bytes, SHA-256 {download['sha256'][:12]}...)",
                        )
                    for blocked in trace.get("blocked_requests", []):
                        yield event(
                            "request_blocked",
                            f"Blocked non-read-only {blocked['method']} request to {blocked['url']}",
                        )
                    screenshot_path = output_dir / "shot.webp"
                    screenshot = ""
                    if screenshot_path.exists():
                        screenshot = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
                    yield event(
                        "artifacts_collected",
                        "Captured DOM trace and screenshot",
                        {"trace": trace, "screenshot_webp": screenshot},
                    )
            except Exception as error:
                yield event("worker_error", str(error))
            finally:
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                shutil.rmtree(output_dir, ignore_errors=True)
                shutil.rmtree(quarantine_dir, ignore_errors=True)
                yield event("container_destroyed", f"Container {container_name} and temporary files removed")

    return StreamingResponse(stream(), media_type="application/x-ndjson")