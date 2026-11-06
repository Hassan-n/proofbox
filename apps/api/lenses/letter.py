"""Letter Lens: extract letter fields with a model and verify supplied documents in code."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from clock_engine import LOCAL_TIMEZONE
from .bill.runners import CodeRunner

CHECKS_CODE = Path(__file__).with_name("letter_checks.py")
EXTRACTION_PROMPT = """Extract only the explicitly stated details from the letter text.
Do not infer missing dates, deadlines, requirements, or applicant identity. Supporting
documents are not included. Return an empty string or empty list for unreadable fields."""


class LetterFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agency: str = Field(default="", max_length=200)
    applicant_name: str = Field(default="", max_length=200)
    reference_number: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=1000)
    response_deadline: str = Field(default="", max_length=40)
    appointment_date: str = Field(default="", max_length=40)
    appointment_time: str = Field(default="", max_length=40)
    appointment_place: str = Field(default="", max_length=240)
    required_documents: list[str] = Field(default_factory=list, max_length=12)
    link: str = Field(default="", max_length=500)


def extract_letter(
    letter_text: str,
    call_model: Callable[..., Any],
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    result = call_model(
        "extractor",
        job_id,
        EXTRACTION_PROMPT,
        letter_text,
        schema=LetterFields,
        max_tokens=1200,
    )
    if not isinstance(result, dict) or result.get("error"):
        return {"status": "unreadable", "fields": {}, "notes": ["The letter fields could not be read."]}
    try:
        fields = LetterFields.model_validate(result).model_dump()
    except Exception:
        return {"status": "unreadable", "fields": {}, "notes": ["The letter fields could not be validated."]}
    fields = {
        key: (
            [re.sub(r"(?<!\d)\d{13}(?!\d)", "[redacted]", item) for item in value]
            if isinstance(value, list)
            else re.sub(r"(?<!\d)\d{13}(?!\d)", "[redacted]", value)
            if isinstance(value, str)
            else value
        )
        for key, value in fields.items()
    }
    for key in ("response_deadline", "appointment_date"):
        value = fields[key]
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                fields[key] = ""
    fields["required_documents"] = [item.strip()[:160] for item in fields["required_documents"] if item.strip()]
    return {"status": "ok", "fields": fields, "notes": []}


def run_letter_lens(
    *,
    letter_document: dict[str, Any],
    supporting_documents: list[dict[str, Any]],
    call_model: Callable[..., Any],
    runner: CodeRunner,
    save_receipt: Callable[..., str],
    emit: Callable[[str, str], None],
    job_id: str,
    check_date: date | None = None,
    bank_statement_months_required: int = 3,
) -> dict[str, Any]:
    letter_text = str(letter_document.get("text", ""))[:100_000]
    extraction = extract_letter(letter_text, call_model, job_id=job_id)
    if extraction["status"] != "ok":
        return {
            "status": "unreadable",
            "summary": "The letter could not be read; no document checks or clocks were created.",
            "derived_facts": {"extraction": extraction, "checklist": [], "clocks": []},
            "receipts": {},
        }

    fields = extraction["fields"]
    safe_documents = [
        {
            "filename": _safe_filename(str(document.get("filename", ""))),
            "page_texts": [str(page)[:100_000] for page in document.get("page_texts", [])],
        }
        for document in supporting_documents
    ]
    check_input = {
        "check_date": (check_date or datetime.now(LOCAL_TIMEZONE).date()).isoformat(),
        "bank_statement_months_required": bank_statement_months_required,
        "letter": fields,
        "documents": safe_documents,
    }
    code = CHECKS_CODE.read_text(encoding="utf-8")
    run = runner.run(code, {"letter.json": check_input})
    if run.exit_code != 0 or run.timed_out:
        raise RuntimeError(f"Letter document checks failed in the code sandbox: {run.stderr[:200]}")
    try:
        checked = json.loads(run.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise RuntimeError("Letter document checks returned invalid output.") from error
    if checked.get("status") != "ok":
        raise RuntimeError("Letter document checks did not complete successfully.")

    receipts = {
        "extract": save_receipt(
            job_id,
            "letter_extract",
            json.dumps(fields, ensure_ascii=False, sort_keys=True),
            {"label": "Letter fields"},
        ),
        "code": save_receipt(
            job_id,
            "code",
            run.executed_code,
            {"label": "Document-check code", "duration_ms": run.duration_ms},
        ),
        "output": save_receipt(
            job_id,
            "output",
            json.dumps(checked, ensure_ascii=False, sort_keys=True),
            {"label": "Document-check results"},
        ),
    }
    emit("letter_checks_completed", f"Checked {len(checked['checks'])} requested document categories")
    clocks = checked.get("clocks", [])
    for clock in clocks:
        emit("letter_clock_found", f"Found {clock['name'].lower()} on {clock['due_at']}")
    summary = fields.get("summary") or "Letter fields and supporting documents checked."
    return {
        "status": "ok",
        "summary": summary,
        "derived_facts": {
            **fields,
            "checklist": checked["checks"],
            "clocks": clocks,
            "check_date": check_input["check_date"],
            "last_verified": None,
        },
        "document": {
            "filename": _safe_filename(str(letter_document.get("filename", ""))),
            "pages": letter_document.get("pages"),
            "sha256": letter_document.get("sha256"),
        },
        "receipts": receipts,
    }


def _safe_filename(value: str) -> str:
    value = re.split(r"[\\/]", value)[-1]
    return re.sub(r"(?<!\d)\d{13}(?!\d)", "[redacted]", value)[:120]
