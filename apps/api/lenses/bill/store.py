"""Storage for Bill jobs: uploads, receipts, events and results.

`PostgresStore` writes to Person A's tables (jobs, job_events, receipts) through his `db` module,
imported lazily so this package still imports in tests and tools that have no database.
`MemoryStore` has the same interface for tests and scripts/bill_dev_server.py.

Uploaded PDFs are stored as a receipt of kind `pdf` (contract C6): `blob_base64` holds the file,
`content_json` holds {filename, bytes, history}. The job's `input_ref` is that receipt id.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import uuid
from typing import Any


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ReceiptSaver:
    """`save_receipt(job_id, kind, content, meta) -> id` for run_bill_lens, backed by a store.

    `items` keeps the sha256 of each saved receipt so the result's receipt index can show it.
    """

    def __init__(self, store: "BillStore"):
        self.store = store
        self.items: dict[str, dict[str, Any]] = {}

    def __call__(self, job_id: str | None, kind: str, content: str, meta: dict[str, Any] | None = None) -> str:
        receipt_id = self.store.save_receipt(job_id or "adhoc", kind, content, meta or {})
        self.items[receipt_id] = {"kind": kind, "sha256": sha256_text(content)}
        return receipt_id


class BillStore:
    def create_job(self, session_id: str | None, filename: str, pdf: bytes, history: dict | None) -> str:
        raise NotImplementedError

    def load_upload(self, job: dict[str, Any]) -> tuple[bytes, dict | None, str]:
        raise NotImplementedError

    def save_receipt(self, job_id: str, kind: str, content: str, meta: dict[str, Any]) -> str:
        raise NotImplementedError

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def emit(self, job_id: str, event_type: str, detail: str) -> None:
        raise NotImplementedError

    def complete(self, job_id: str, result: dict[str, Any], detail: str) -> None:
        raise NotImplementedError

    def fail(self, job_id: str, detail: str) -> None:
        raise NotImplementedError


def _public_receipt(receipt_id: str, kind: str, sha256: str | None, content_json: Any, job_id: str) -> dict[str, Any]:
    data = content_json if isinstance(content_json, dict) else json.loads(content_json or "{}")
    if kind == "pdf":
        content = f"Uploaded PDF {data.get('filename', '')} ({data.get('bytes', '?')} bytes). The file itself is not returned."
        meta = {"filename": data.get("filename"), "bytes": data.get("bytes")}
    else:
        content, meta = data.get("content", ""), data.get("meta", {})
    return {"id": receipt_id, "job_id": job_id, "kind": kind, "sha256": sha256, "content": content, "meta": meta}


class PostgresStore(BillStore):
    def __init__(self):
        from db import add_event, pool  # Person A's module, available inside the API container
        from psycopg.types.json import Jsonb

        self.pool, self.add_event, self.Jsonb = pool, add_event, Jsonb

    def create_job(self, session_id, filename, pdf, history):
        job_id, receipt_id = new_id("job"), new_id("rcpt")
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute(
                    """INSERT INTO receipts (id, job_id, kind, sha256, content_json, blob_base64)
                       VALUES (%s, %s, 'pdf', %s, %s, %s)""",
                    (
                        receipt_id,
                        job_id,
                        hashlib.sha256(pdf).hexdigest(),
                        self.Jsonb({"filename": filename, "bytes": len(pdf), "history": history}),
                        base64.b64encode(pdf).decode("ascii"),
                    ),
                )
                conn.execute(
                    """INSERT INTO jobs (id, session_id, lens, status, input_ref)
                       VALUES (%s, %s, 'bill', 'queued', %s)""",
                    (job_id, session_id, receipt_id),
                )
        self.add_event(job_id, "job_queued", f"Queued Bill Lens check for {filename}")
        return job_id

    def load_upload(self, job):
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT content_json, blob_base64 FROM receipts WHERE id = %s AND job_id = %s AND kind = 'pdf'",
                (job["input_ref"], job["id"]),
            ).fetchone()
        if not row:
            raise LookupError("The uploaded bill was not found")
        data = row["content_json"] or {}
        return base64.b64decode(row["blob_base64"]), data.get("history"), data.get("filename", "bill.pdf")

    def save_receipt(self, job_id, kind, content, meta):
        receipt_id = new_id("rcpt")
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO receipts (id, job_id, kind, sha256, content_json) VALUES (%s, %s, %s, %s, %s)",
                (receipt_id, job_id, kind, sha256_text(content), self.Jsonb({"content": content, "meta": meta})),
            )
        return receipt_id

    def get_receipt(self, receipt_id):
        with self.pool.connection() as conn:
            row = conn.execute(
                """SELECT r.id, r.job_id, r.kind, r.sha256, r.content_json FROM receipts r
                   JOIN jobs j ON j.id = r.job_id WHERE r.id = %s AND j.lens = 'bill'""",
                (receipt_id,),
            ).fetchone()
        if not row:
            return None
        return _public_receipt(row["id"], row["kind"], row["sha256"], row["content_json"], row["job_id"])

    def emit(self, job_id, event_type, detail):
        self.add_event(job_id, event_type, detail)

    def complete(self, job_id, result, detail):
        # One transaction, so the SSE loop never sees 'completed' without the job_completed event.
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute(
                    "UPDATE jobs SET status = 'completed', result_json = %s WHERE id = %s",
                    (self.Jsonb(result), job_id),
                )
                conn.execute(
                    "INSERT INTO job_events (job_id, event_type, detail) VALUES (%s, 'job_completed', %s)",
                    (job_id, detail),
                )

    def fail(self, job_id, detail):
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute("UPDATE jobs SET status = 'failed' WHERE id = %s", (job_id,))
                conn.execute(
                    "INSERT INTO job_events (job_id, event_type, detail) VALUES (%s, 'job_failed', %s)",
                    (job_id, detail),
                )


class MemoryStore(BillStore):
    """In-process store with the same behaviour as PostgresStore (tests and the dev server)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.receipts: dict[str, dict[str, Any]] = {}

    def create_job(self, session_id, filename, pdf, history):
        job_id, receipt_id = new_id("job"), new_id("rcpt")
        with self.lock:
            self.receipts[receipt_id] = {
                "job_id": job_id,
                "kind": "pdf",
                "sha256": hashlib.sha256(pdf).hexdigest(),
                "content_json": {"filename": filename, "bytes": len(pdf), "history": history},
                "blob": pdf,
            }
            self.jobs[job_id] = {
                "id": job_id, "session_id": session_id, "lens": "bill",
                "status": "queued", "input_ref": receipt_id, "result_json": None,
            }
        self.emit(job_id, "job_queued", f"Queued Bill Lens check for {filename}")
        return job_id

    def claim_next(self) -> dict[str, Any] | None:
        with self.lock:
            for job in self.jobs.values():
                if job["status"] == "queued":
                    job["status"] = "running"
                    return dict(job)
        return None

    def load_upload(self, job):
        item = self.receipts.get(job["input_ref"])
        if not item or item["kind"] != "pdf" or item["job_id"] != job["id"]:
            raise LookupError("The uploaded bill was not found")
        data = item["content_json"]
        return item["blob"], data.get("history"), data.get("filename", "bill.pdf")

    def save_receipt(self, job_id, kind, content, meta):
        receipt_id = new_id("rcpt")
        with self.lock:
            self.receipts[receipt_id] = {
                "job_id": job_id, "kind": kind, "sha256": sha256_text(content),
                "content_json": {"content": content, "meta": meta},
            }
        return receipt_id

    def get_receipt(self, receipt_id):
        item = self.receipts.get(receipt_id)
        if not item:
            return None
        return _public_receipt(receipt_id, item["kind"], item["sha256"], item["content_json"], item["job_id"])

    def emit(self, job_id, event_type, detail):
        with self.lock:
            self._append(job_id, event_type, detail)

    def _append(self, job_id, event_type, detail):
        self.events.append({"id": len(self.events) + 1, "job_id": job_id, "event_type": event_type, "detail": detail})

    def complete(self, job_id, result, detail):
        with self.lock:
            self.jobs[job_id].update(status="completed", result_json=result)
            self._append(job_id, "job_completed", detail)

    def fail(self, job_id, detail):
        with self.lock:
            self.jobs[job_id]["status"] = "failed"
            self._append(job_id, "job_failed", detail)

    def job_events(self, job_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self.lock:
            return [e for e in self.events if e["job_id"] == job_id and e["id"] > after]
