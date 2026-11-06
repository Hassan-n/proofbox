"""Letter Lens job orchestration."""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Any, Callable

from .bill.runners import CodeRunner
from .letter import run_letter_lens

log = logging.getLogger("proofbox.letter")


@dataclass
class LetterServices:
    load_documents: Callable[[dict[str, Any]], tuple[bytes, str, list[tuple[bytes, str]]]]
    parser: Callable[[str, Callable[[str, str], None]], Callable[[bytes], dict[str, Any]]]
    runner: Callable[[str, Callable[[str, str], None]], CodeRunner]
    call_model: Callable[..., Any]
    save_receipt: Callable[..., str]
    emit: Callable[[str, str], None]
    complete: Callable[[str, dict[str, Any], str], None]
    fail: Callable[[str, str], None]


def run_letter_job(job: dict[str, Any], services: LetterServices) -> dict[str, Any] | None:
    job_id = job["id"]

    def emit(event_type: str, detail: str) -> None:
        services.emit(job_id, event_type, detail)

    try:
        letter_pdf, letter_filename, supporting_pdfs = services.load_documents(job)
        emit("letter_received", f"Received a letter and {len(supporting_pdfs)} supporting PDF(s); parsing in an isolated sandbox.")
        parser = services.parser(job_id, emit)
        letter_document = parser(letter_pdf)
        letter_document["filename"] = letter_filename
        documents = []
        for pdf, filename in supporting_pdfs:
            parsed = parser(pdf)
            parsed["filename"] = filename
            documents.append(parsed)
        result = run_letter_lens(
            letter_document=letter_document,
            supporting_documents=documents,
            call_model=services.call_model,
            runner=services.runner(job_id, emit),
            save_receipt=services.save_receipt,
            emit=emit,
            job_id=job_id,
        )
        result["status"] = result.get("status", "ok")
        summary = result.get("summary", "Letter check completed.")
        services.complete(job_id, result, summary)
        return result
    except Exception as error:  # noqa: BLE001 - mark the job failed and let the queue continue
        log.exception("Letter job %s failed", job_id)
        services.fail(job_id, f"Letter check failed: {str(error)[:250] or type(error).__name__}")
        return None


_services: LetterServices | None = None


def production_services() -> LetterServices:
    global _services
    if _services is None:
        from .bill.store import PostgresStore
        from .bill.worker_client import WorkerClient, WorkerCodeRunner, WorkerDocumentParser
        from .bill.model_caller import gateway_caller

        store = PostgresStore()
        client = WorkerClient()

        def load_documents(job: dict[str, Any]) -> tuple[bytes, str, list[tuple[bytes, str]]]:
            with store.pool.connection() as conn:
                rows = conn.execute(
                    """SELECT id, kind, content_json, blob_base64 FROM receipts
                       WHERE job_id = %s ORDER BY created_at, id""",
                    (job["id"],),
                ).fetchall()
            primary = next((row for row in rows if row["id"] == job["input_ref"]), None)
            if not primary or not primary["blob_base64"]:
                raise LookupError("The uploaded letter was not found.")
            metadata = primary["content_json"] or {}
            supporting = []
            for row in rows:
                if row["kind"] != "letter_supporting_pdf":
                    continue
                data = row["content_json"] or {}
                supporting.append((base64.b64decode(row["blob_base64"], validate=True), str(data.get("filename", "document.pdf"))))
            return (
                base64.b64decode(primary["blob_base64"], validate=True),
                str(metadata.get("filename", "letter.pdf")),
                supporting,
            )

        def save_receipt(job_id: str, kind: str, content: str, metadata: dict[str, Any]) -> str:
            return store.save_receipt(job_id, kind, content, metadata)

        _services = LetterServices(
            load_documents=load_documents,
            parser=lambda job_id, emit: WorkerDocumentParser(client, job_id, emit),
            runner=lambda job_id, emit: WorkerCodeRunner(client, job_id, emit),
            call_model=gateway_caller(),
            save_receipt=save_receipt,
            emit=store.emit,
            complete=store.complete,
            fail=store.fail,
        )
    return _services


async def process_letter_job(job: dict[str, Any], services: LetterServices | None = None) -> None:
    try:
        services = services or production_services()
    except Exception as error:  # noqa: BLE001 - report setup errors as job failures
        log.exception("Letter services could not start")
        from .bill.store import PostgresStore

        await asyncio.to_thread(PostgresStore().fail, job["id"], f"Letter Lens is not configured: {str(error)[:200]}")
        return
    await asyncio.to_thread(run_letter_job, job, services)
