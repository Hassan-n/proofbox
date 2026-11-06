"""PDF intake for Letter Lens."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from psycopg.types.json import Jsonb

from db import add_event, pool

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_SUPPORTING_DOCUMENTS = 4
router = APIRouter(prefix="/api/letter", tags=["letter"])


class SupportingDocument(BaseModel):
    filename: str = Field(max_length=200)
    pdf_base64: str = Field(max_length=((MAX_PDF_BYTES + 1024 * 1024) * 4) // 3 + 64)

    @field_validator("filename")
    @classmethod
    def clean_filename(cls, value: str) -> str:
        name = re.split(r"[\\/]", value)[-1]
        name = re.sub(r"[^\w .()-]", "_", name).strip() or "document.pdf"
        return re.sub(r"(?<!\d)\d{13}(?!\d)", "[redacted]", name)[:120]


class LetterIntake(BaseModel):
    filename: str = Field(default="letter.pdf", max_length=200)
    pdf_base64: str = Field(max_length=((MAX_PDF_BYTES + 1024 * 1024) * 4) // 3 + 64)
    supporting_documents: list[SupportingDocument] = Field(default_factory=list, max_length=MAX_SUPPORTING_DOCUMENTS)
    session_id: str | None = Field(default=None, max_length=64)

    @field_validator("filename")
    @classmethod
    def clean_filename(cls, value: str) -> str:
        name = re.split(r"[\\/]", value)[-1]
        name = re.sub(r"[^\w .()-]", "_", name).strip() or "letter.pdf"
        return re.sub(r"(?<!\d)\d{13}(?!\d)", "[redacted]", name)[:120]


def _decode_pdf(value: str) -> bytes:
    if "," in value[:100] and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=422, detail="A PDF could not be decoded.") from error
    if not data:
        raise HTTPException(status_code=422, detail="A PDF file is empty.")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="Each PDF must be 5 MB or smaller.")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="Only PDF files are supported.")
    return data


@router.post("/intake", status_code=202)
def letter_intake(request: LetterIntake) -> dict[str, str]:
    letter = _decode_pdf(request.pdf_base64)
    supporting = [(document, _decode_pdf(document.pdf_base64)) for document in request.supporting_documents]
    if len(letter) + sum(len(data) for _, data in supporting) > MAX_TOTAL_BYTES:
        raise HTTPException(status_code=413, detail="The letter and supporting PDFs must total 10 MB or less.")
    job_id = f"job-{uuid.uuid4().hex[:10]}"
    receipt_rows: list[tuple[str, str, str, bytes, dict[str, Any]]] = []
    primary_receipt = f"rcpt-{uuid.uuid4().hex[:10]}"
    receipt_rows.append((primary_receipt, "letter_pdf", request.filename, letter, {"filename": request.filename, "bytes": len(letter)}))
    for document, data in supporting:
        receipt_rows.append(
            (
                f"rcpt-{uuid.uuid4().hex[:10]}",
                "letter_supporting_pdf",
                document.filename,
                data,
                {"filename": document.filename, "bytes": len(data)},
            )
        )
    with pool.connection() as conn:
        with conn.transaction():
            for receipt_id, kind, _, data, metadata in receipt_rows:
                conn.execute(
                    """INSERT INTO receipts (id, job_id, kind, sha256, content_json, blob_base64)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        receipt_id,
                        job_id,
                        kind,
                        hashlib.sha256(data).hexdigest(),
                        Jsonb(metadata),
                        base64.b64encode(data).decode("ascii"),
                    ),
                )
            conn.execute(
                """INSERT INTO jobs (id, session_id, lens, status, input_ref)
                   VALUES (%s, %s, 'letter', 'queued', %s)""",
                (job_id, request.session_id, primary_receipt),
            )
    add_event(
        job_id,
        "job_queued",
        f"Queued Letter Lens check with {len(supporting)} supporting PDF(s); documents are parsed in an isolated sandbox.",
    )
    return {"job_id": job_id, "status": "queued"}
