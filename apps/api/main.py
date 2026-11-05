import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from psycopg.types.json import Jsonb

from db import add_event, claim_next_job, init_db, pool
from link_lens import evaluate_link, validate_inspection_url
from lenses.bill.job import process_bill_job
from lenses.bill.router import router as bill_router

WORKER_URL = os.getenv("WORKER_URL", "http://10.99.0.3:8080")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "dev-secret-token")
# Bill jobs take ~20 s with live models, so they run beside the queue instead of blocking Link jobs.
BILL_SLOTS = asyncio.Semaphore(int(os.getenv("BILL_JOBS_PARALLEL", "2")))
_bill_tasks: set[asyncio.Task] = set()


async def _run_bill_job(job: dict) -> None:
    try:
        await process_bill_job(job)
    finally:
        BILL_SLOTS.release()


async def process_job(job: dict) -> None:
    if job["lens"] == "bill":
        await BILL_SLOTS.acquire()
        task = asyncio.create_task(_run_bill_job(job))
        _bill_tasks.add(task)
        task.add_done_callback(_bill_tasks.discard)
        return
    job_id = job["id"]
    url = job["input_ref"]
    containment_events = []
    trace = {}
    screenshot_b64 = ""
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            async with client.stream(
                "POST",
                f"{WORKER_URL}/run",
                json={"job_id": job_id, "mode": "link_lens", "url": url},
                headers={"Authorization": f"Bearer {WORKER_TOKEN}"},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    message = json.loads(line)
                    event_type = message["event"]
                    if event_type == "artifacts_collected":
                        trace = message["data"].get("trace", {})
                        screenshot_b64 = message["data"].get("screenshot_webp", "")
                    add_event(job_id, event_type, message.get("detail", ""))
                    if event_type in {
                        "network_blocked",
                        "download_quarantined",
                        "timeout_kill",
                        "memory_kill",
                    }:
                        containment_events.append(message.get("detail", event_type))

        verdict = await asyncio.to_thread(
            evaluate_link, job_id, url, trace, screenshot_b64, containment_events
        )
        result_payload = {
            "verdict": verdict,
            "screenshot_webp": screenshot_b64,
            "final_url": trace.get("final_url", url),
            "redirect_chain": trace.get("redirect_chain", []),
        }
        with pool.connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'completed', result_json = %s WHERE id = %s",
                (Jsonb(result_payload), job_id),
            )
        add_event(job_id, "job_completed", f"Verdict: {verdict['verdict'].upper()}")
    except Exception as error:
        await asyncio.to_thread(add_event, job_id, "job_failed", str(error))
        with pool.connection() as conn:
            conn.execute("UPDATE jobs SET status = 'failed' WHERE id = %s", (job_id,))


async def queue_worker_loop() -> None:
    while True:
        try:
            job = await asyncio.to_thread(claim_next_job)
            if job:
                await process_job(job)
            else:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print("Worker loop error:", error)
            await asyncio.sleep(2.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(init_db)
    task = asyncio.create_task(queue_worker_loop())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if _bill_tasks:
            await asyncio.wait(_bill_tasks, timeout=30)
        await asyncio.to_thread(pool.close)


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(bill_router)


class IntakeReq(BaseModel):
    lens: str = "link"
    input_ref: str
    session_id: str | None = None

    @field_validator("input_ref")
    @classmethod
    def validate_input_ref(cls, value: str) -> str:
        return validate_inspection_url(value)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/sessions")
def create_session():
    session_id = f"sess-{uuid.uuid4().hex[:12]}"
    with pool.connection() as conn:
        conn.execute("INSERT INTO sessions (id) VALUES (%s)", (session_id,))
    return {"session_id": session_id}


@app.post("/api/intake")
def create_job(req: IntakeReq):
    if req.lens != "link":
        raise HTTPException(status_code=422, detail="Unsupported lens.")
    job_id = f"job-{uuid.uuid4().hex[:10]}"
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO jobs (id, session_id, lens, status, input_ref)
               VALUES (%s, %s, %s, 'queued', %s)""",
            (job_id, req.session_id, req.lens, req.input_ref),
        )
    add_event(job_id, "job_queued", f"Queued Link Lens inspection for {req.input_ref}")
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with pool.connection() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        events = conn.execute(
            "SELECT * FROM job_events WHERE job_id = %s ORDER BY id ASC", (job_id,)
        ).fetchall()
    return {"job": job, "events": events}


@app.get("/api/jobs/{job_id}/events")
async def stream_job_events(job_id: str):
    with pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM jobs WHERE id = %s", (job_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        last_id = 0
        while True:
            with pool.connection() as conn:
                rows = conn.execute(
                    """SELECT * FROM job_events
                       WHERE job_id = %s AND id > %s ORDER BY id ASC""",
                    (job_id, last_id),
                ).fetchall()
                job = conn.execute(
                    "SELECT status FROM jobs WHERE id = %s", (job_id,)
                ).fetchone()
            for row in rows:
                last_id = row["id"]
                event = {"event": row["event_type"], "detail": row["detail"]}
                yield f"data: {json.dumps(event)}\n\n"
            if not job or job["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(event_stream(), media_type="text/event-stream")