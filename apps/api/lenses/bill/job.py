"""Bill job runner: what Person A's queue calls for a job with `lens == "bill"`.

    from lenses.bill.job import process_bill_job
    ...
    if job["lens"] == "bill":
        await process_bill_job(job)
        return

Flow: load the uploaded PDF -> parse it in the worker sandbox -> run_bill_lens (extractor,
tariff checks, analyst program in the sandbox, letter) -> store result_json and job_completed.
Every failure ends the job as `failed` with a plain-language `job_failed` event; nothing raises
into the queue loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

from .pipeline import run_bill_lens
from .runners import CodeRunner
from .store import BillStore, ReceiptSaver
from .tariff import Tariff

log = logging.getLogger("proofbox.bill")

Emit = Callable[[str, str], None]


@dataclass
class BillServices:
    store: BillStore
    call_model: Callable[..., Any]
    # Factories take (job_id, emit) so sandbox lifecycle events land on the right job.
    parser: Callable[[str, Emit], Callable[[bytes], dict[str, Any]]]
    runner: Callable[[str, Emit], CodeRunner | None]
    tariff: Tariff | None = None


def completion_detail(result: dict[str, Any]) -> str:
    if result["status"] != "ok":
        return "Finished: the bill could not be read, so no checks were run"
    count = len(result["findings"])
    if not count:
        return "Finished: no discrepancies found"
    letter = " and a dispute letter" if result.get("dispute_letter") else ""
    return f"Finished: {count} finding{'s' if count != 1 else ''}{letter}"


def run_bill_job(job: dict[str, Any], services: BillServices) -> dict[str, Any] | None:
    job_id = job["id"]
    store = services.store

    def emit(event_type: str, detail: str) -> None:
        store.emit(job_id, event_type, detail)

    try:
        pdf, history, filename = store.load_upload(job)
        emit("bill_received", f"Received {filename} ({len(pdf):,} bytes); parsing it in an isolated sandbox")
        parsed = services.parser(job_id, emit)(pdf)
        pages = (parsed.get("input") or {}).get("pages")
        emit("bill_parsed", f"Read {pages} page(s) of text without running anything inside the document")
        if not history:
            emit("history_missing", "No earlier readings supplied; history-based checks will be skipped")
        result = run_bill_lens(
            parsed,
            history=history,
            call_model=services.call_model,
            runner=services.runner(job_id, emit),
            save_receipt=ReceiptSaver(store),
            emit=emit,
            job_id=job_id,
            tariff=services.tariff,
        )
        result["document"] = {"filename": filename, **{k: (parsed.get("input") or {}).get(k) for k in ("sha256", "bytes", "pages")}}
        store.complete(job_id, result, completion_detail(result))
        return result
    except Exception as error:  # noqa: BLE001 - the job fails cleanly; the queue keeps running
        log.exception("Bill job %s failed", job_id)
        store.fail(job_id, f"Bill check failed: {str(error)[:300] or type(error).__name__}")
        return None


_services: BillServices | None = None


def production_services() -> BillServices:
    """Postgres store, worker sandbox for parsing and code, live models through the gateway."""
    global _services
    if _services is None:
        from .model_caller import gateway_caller
        from .store import PostgresStore
        from .worker_client import WorkerClient, WorkerCodeRunner, WorkerParser

        client = WorkerClient()
        _services = BillServices(
            store=PostgresStore(),
            call_model=gateway_caller(),
            parser=lambda job_id, emit: WorkerParser(client, job_id, emit),
            runner=lambda job_id, emit: WorkerCodeRunner(client, job_id, emit),
        )
    return _services


async def process_bill_job(job: dict[str, Any], services: BillServices | None = None) -> None:
    try:
        services = services or production_services()
    except Exception as error:  # noqa: BLE001 - e.g. a missing env var or module in the container
        log.exception("Bill services could not start")
        from .store import PostgresStore

        await asyncio.to_thread(PostgresStore().fail, job["id"], f"Bill Lens is not configured: {str(error)[:200]}")
        return
    await asyncio.to_thread(run_bill_job, job, services)
