"""Local dev server for the Bill Lens web app. DEVELOPMENT ONLY - not a sandbox.

Serves apps/web (so the page is at http://127.0.0.1:8765/bill/) and the same API the deployed
stack exposes for Bill: /api/bill/intake, /api/bill/receipts/{id}, /api/jobs/{id} and
/api/jobs/{id}/events (Person A's job routes, re-implemented in memory).

Differences from production, all deliberate and dev-only:
  * the PDF is parsed in-process and the analyst program runs as a local subprocess
    (LocalSubprocessRunner). Production runs both in the worker's no-network sandbox;
  * jobs, events and receipts live in memory (MemoryStore) instead of Postgres.

  python scripts/bill_dev_server.py            # live models if VULTR_INFERENCE_KEY is set, else stubs
  python scripts/bill_dev_server.py --stub     # offline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for extra in (REPO_ROOT / "apps" / "api", REPO_ROOT / "sandbox" / "code", REPO_ROOT / "scripts"):
    sys.path.insert(0, str(extra))

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import RedirectResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import parse_bill as pb  # noqa: E402
from lenses.bill.job import BillServices, run_bill_job  # noqa: E402
from lenses.bill.router import create_router  # noqa: E402
from lenses.bill.runners import LocalSubprocessRunner  # noqa: E402
from lenses.bill.store import MemoryStore  # noqa: E402

WEB_DIR = REPO_ROOT / "apps" / "web"


class SlowStore(MemoryStore):
    """Spaces out progress events a little so the page's live stepper is visible locally."""

    def __init__(self, delay_s: float):
        super().__init__()
        self.delay_s = delay_s

    def emit(self, job_id, event_type, detail):
        super().emit(job_id, event_type, detail)
        time.sleep(self.delay_s)


def local_parser(job_id, emit):
    def parse(pdf: bytes) -> dict:
        emit("container_started", "DEV: parsing in a local process (production uses the no-network sandbox)")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bill.pdf"
            path.write_bytes(pdf)
            try:
                return pb.parse_pdf(path)
            finally:
                emit("container_destroyed", "DEV: local parse finished, temporary file removed")

    return parse


def build_services(store: MemoryStore, live: bool) -> BillServices:
    if live:
        from eval_extractor import OUT_DIR, LiveCaller

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        call_model = LiveCaller(OUT_DIR / "dev_server_calls.jsonl")
    else:
        from build_bill_samples import StubGateway

        call_model = StubGateway()
    return BillServices(
        store=store,
        call_model=call_model,
        parser=local_parser,
        runner=lambda job_id, emit: LocalSubprocessRunner(timeout_s=20),
    )


def create_app(store: MemoryStore, services: BillServices) -> FastAPI:
    app = FastAPI(title="Proofbox Bill Lens (dev)")
    app.include_router(create_router(lambda: store))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = store.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"job": job, "events": store.job_events(job_id)}

    @app.get("/api/jobs/{job_id}/events")
    async def stream_job_events(job_id: str):
        if job_id not in store.jobs:
            raise HTTPException(status_code=404, detail="Job not found")

        async def event_stream():
            last_id = 0
            while True:
                rows = store.job_events(job_id, last_id)
                status = store.jobs[job_id]["status"]
                for row in rows:
                    last_id = row["id"]
                    yield f"data: {json.dumps({'event': row['event_type'], 'detail': row['detail']})}\n\n"
                if status in {"completed", "failed"} and not store.job_events(job_id, last_id):
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/")
    def home():
        return RedirectResponse("/bill/")

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    def queue_loop():
        while True:
            job = store.claim_next()
            if job:
                run_bill_job(job, services)
            else:
                time.sleep(0.3)

    threading.Thread(target=queue_loop, daemon=True).start()
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stub", action="store_true", help="offline stub models")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--step-delay", type=float, default=0.35, help="seconds between progress events")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass
    live = not args.stub and bool(os.getenv("VULTR_INFERENCE_KEY"))
    store = SlowStore(args.step_delay)
    app = create_app(store, build_services(store, live))
    print(f"Bill Lens dev server ({'live models' if live else 'stub models'}): http://127.0.0.1:{args.port}/bill/")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
