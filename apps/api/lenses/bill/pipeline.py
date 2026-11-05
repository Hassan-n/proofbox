"""Bill Lens pipeline: parse output -> extractor -> deterministic checks -> analyst coder -> letter.

All side effects are injected so the same code runs with stubs, live models, the dev runner or
the worker sandbox:
  call_model    gateway.call_model(role, job_id, system_prompt, untrusted_data, schema=..., max_tokens=...)
  runner        CodeRunner for the analyst program (worker `code` profile in production)
  save_receipt  save_receipt(job_id, kind, content, meta) -> receipt id
  emit          emit(event_type, detail) progress events (Person A's add_event)
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

from .analyst import InMemoryReceipts, attach_receipts, run_analyst
from .checks import run_checks
from .extractor import extract_bill
from .runners import CodeRunner
from .tariff import Tariff, load_tariff
from .writer import write_letter

DISCLAIMER = (
    "Figures are recomputed from the published tariff and the details read from your bill. "
    "This is not legal advice. Check each point before you send the letter."
)
RECEIPT_LABELS = {
    "extract": "Bill text",
    "recompute": "Tariff recompute",
    "code": "Sandbox code",
    "output": "Sandbox output",
}


def run_bill_lens(
    parsed: dict[str, Any],
    *,
    history: dict[str, Any] | None,
    call_model: Callable[..., Any],
    runner: CodeRunner | None,
    save_receipt: Callable[..., str] | None = None,
    emit: Callable[[str, str], None] | None = None,
    job_id: str | None = None,
    tariff: Tariff | None = None,
    letter_date: date | None = None,
) -> dict[str, Any]:
    tariff = tariff or load_tariff()
    save = save_receipt or InMemoryReceipts()
    say = emit or (lambda _type, _detail: None)
    containment = [e for e in parsed.get("events", []) if e.get("type") == "instruction_ignored"]
    for event in containment:
        say("instruction_ignored", event.get("message", "An instruction inside the document was ignored"))

    extraction = extract_bill(parsed, call_model, job_id)
    if extraction["status"] != "ok":
        say("bill_unreadable", "; ".join(extraction["notes"])[:300])
        return _result(status="unreadable", extraction=extraction, containment=containment, tariff=tariff)
    bill = extraction["bill"]
    say("bill_extracted", f"Read account {bill.get('account_number')}; {len(extraction['unreadable_fields'])} unreadable fields")

    receipts = {
        "extract": save(
            job_id,
            "extract",
            json.dumps({"document_text": parsed.get("text", ""), "extracted": bill}, indent=2, ensure_ascii=False),
            {"label": "Bill text and extracted values", "unreadable_fields": extraction["unreadable_fields"]},
        )
    }
    checks = run_checks(bill, history, tariff)
    receipts["recompute"] = save(
        job_id,
        "recompute",
        json.dumps({"tariff_id": tariff.tariff_id, **checks}, indent=2, ensure_ascii=False),
        {"label": "Tariff engine recomputation and check results"},
    )
    for finding in checks["findings"]:
        finding["receipt_ids"] = [receipts["extract"], receipts["recompute"]]
    say("checks_completed", f"{len(checks['findings'])} findings from {len(checks['checks_run'])} checks")

    if runner is None:
        analyst = {
            "status": "failed",
            "attempts": [],
            "comparison": None,
            "receipt_ids": {},
            "skipped_checks": [{"check": "analyst_coder", "reason": "Extra recomputation checks were skipped. No code sandbox available."}],
        }
    else:
        analyst = run_analyst(bill, history, call_model, runner, tariff=tariff, save_receipt=save, job_id=job_id)
    attach_receipts(checks, analyst)
    receipts.update(analyst["receipt_ids"])
    say(
        "analyst_completed" if analyst["status"] == "agreed" else "analyst_skipped",
        f"Analyst recomputation {analyst['status']} after {len(analyst['attempts'])} attempt(s)",
    )

    letter = write_letter(bill, checks["findings"], call_model, job_id=job_id, letter_date=letter_date)
    if letter:
        say("letter_drafted", f"Dispute letter drafted ({letter['source']})")

    return _result(
        status="ok",
        extraction=extraction,
        containment=containment,
        tariff=tariff,
        checks=checks,
        analyst=analyst,
        letter=letter,
        receipts=receipts,
        saver=save,
    )


def _result(*, status, extraction, containment, tariff, checks=None, analyst=None, letter=None, receipts=None, saver=None) -> dict[str, Any]:
    bill = extraction.get("bill") or {}
    recomputation = (checks or {}).get("recomputation")
    skipped = list((checks or {}).get("skipped_checks", []))
    if status != "ok":
        skipped.append({"check": "all", "reason": "The bill could not be read, so no checks were run."})
    return {
        "lens": "bill",
        "status": status,
        "tariff_id": tariff.tariff_id,
        "extracted": extraction.get("bill"),
        "unreadable_fields": extraction.get("unreadable_fields", []),
        "notes": extraction.get("notes", []),
        "summary": {
            "findings": len((checks or {}).get("findings", [])),
            "billed_total": bill.get("total_due"),
            "recomputed_total": recomputation["total"] if recomputation else None,
        },
        "findings": (checks or {}).get("findings", []),
        "skipped_checks": skipped,
        "checks_run": (checks or {}).get("checks_run", []),
        "recomputation": recomputation,
        "analyst": None
        if analyst is None
        else {"status": analyst["status"], "attempts": len(analyst["attempts"]), "comparison": analyst.get("comparison")},
        "dispute_letter": letter,
        "events": containment,
        "receipts": _receipt_index(receipts or {}, saver),
        "disclaimer": DISCLAIMER,
    }


def _receipt_index(receipts: dict[str, str], saver: Any) -> dict[str, dict[str, Any]]:
    stored = getattr(saver, "items", {})
    index = {}
    for kind, receipt_id in receipts.items():
        item = stored.get(receipt_id, {})
        index[receipt_id] = {"kind": kind, "label": RECEIPT_LABELS.get(kind, kind), "sha256": item.get("sha256")}
    return index
