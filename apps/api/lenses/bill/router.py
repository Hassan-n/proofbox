"""HTTP routes for Bill Lens (owned by Person B). Person A includes them in apps/api/main.py:

    from lenses.bill.router import router as bill_router
    app.include_router(bill_router)

POST /api/bill/intake         {filename, pdf_base64, history?, session_id?} -> {job_id, status}
GET  /api/bill/receipts/{id}  -> {receipt: {id, job_id, kind, sha256, content, meta}}

Progress and results use the shared job routes: /api/jobs/{id} and /api/jobs/{id}/events.
The PDF travels as base64 in JSON so the API needs no multipart dependency (D-B15).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .store import BillStore

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_HISTORY_BYTES = 256 * 1024
MAX_HISTORY_ROWS = 400
RECEIPT_ID_RE = re.compile(r"^rcpt-[0-9a-f]{10}$")


class BillIntake(BaseModel):
    filename: str = Field(default="bill.pdf", max_length=200)
    # 1 MB headroom so a slightly oversized PDF gets the clear 413 below rather than a generic 422.
    pdf_base64: str = Field(max_length=((MAX_PDF_BYTES + 1024 * 1024) * 4) // 3 + 64)
    history: dict[str, Any] | None = None
    session_id: str | None = Field(default=None, max_length=64)

    @field_validator("filename")
    @classmethod
    def clean_filename(cls, value: str) -> str:
        name = re.split(r"[\\/]", value)[-1]
        name = re.sub(r"[^\w .()-]", "_", name).strip() or "bill.pdf"
        return name[:120]

    @field_validator("history")
    @classmethod
    def check_history(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if not value:
            return None
        if len(json.dumps(value)) > MAX_HISTORY_BYTES:
            raise ValueError("History is too large")
        for key in ("previous_bills", "outage_log"):
            rows = value.get(key, [])
            if not isinstance(rows, list) or len(rows) > MAX_HISTORY_ROWS:
                raise ValueError(f"History field {key} must be a list of at most {MAX_HISTORY_ROWS} items")
        return value


def decode_pdf(data: str) -> bytes:
    if "," in data[:100] and data.lstrip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        pdf = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=422, detail="The file could not be decoded.") from error
    if not pdf:
        raise HTTPException(status_code=422, detail="The file is empty.")
    if len(pdf) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail=f"The PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB.")
    if not pdf.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="Only PDF bills are supported.")
    return pdf


def create_router(get_store: Callable[[], BillStore]) -> APIRouter:
    router = APIRouter(prefix="/api/bill", tags=["bill"])

    @router.post("/intake")
    def bill_intake(req: BillIntake) -> dict[str, str]:
        pdf = decode_pdf(req.pdf_base64)
        job_id = get_store().create_job(req.session_id, req.filename, pdf, req.history)
        return {"job_id": job_id, "status": "queued"}

    @router.get("/receipts/{receipt_id}")
    def bill_receipt(receipt_id: str) -> dict[str, Any]:
        receipt = get_store().get_receipt(receipt_id) if RECEIPT_ID_RE.match(receipt_id) else None
        if not receipt:
            raise HTTPException(status_code=404, detail="Receipt not found")
        return {"receipt": receipt}

    return router


_store: BillStore | None = None


def _postgres_store() -> BillStore:
    global _store
    if _store is None:
        from .store import PostgresStore

        _store = PostgresStore()
    return _store


router = create_router(_postgres_store)
