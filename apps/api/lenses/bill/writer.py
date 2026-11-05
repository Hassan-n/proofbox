"""Dispute letter (guide Step 3.6).

The writer model only words the letter, from structured findings. Account details, finding
numbers and receipt references are added by code, so they are always present and correct.
The model's text is checked for threats, legal conclusions and numbers that are not in the
findings; if it fails twice, a fixed template letter is used instead.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "bill_writer.md"
UNREADABLE = "unreadable"
MISSING = "[not readable on the bill - please fill in]"
# glm-5.3 reasons before answering whatever thinking switch is sent (~3.2k tokens for a 3-finding letter), see D-B14.
MAX_TOKENS = 4000
MAX_WRITER_ATTEMPTS = 2

# Threats, ultimatums, legal conclusions and injection echoes. Matched as whole words, case-insensitive.
BANNED_PHRASES = (
    "entitled", "entitlement", "unlawful", "illegal", "illegally", "lawsuit", "legal action", "legally", "by law",
    "court", "courts", "attorney", "attorneys", "lawyer", "lawyers", "sue", "suing", "liable", "liability",
    "breach", "compensation", "damages", "owed", "owe", "ombud", "ombudsman", "tribunal", "act of parliament",
    "consumer protection", "rights", "failing which", "or else", "threaten", "demand", "demands", "fraud",
    "fraudulent", "negligent", "negligence", "bad faith", "ignore previous", "environment variable",
    "environment variables", "ai assistant",
)
_BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in BANNED_PHRASES) + r")\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")

CHECK_TITLES = {
    "arithmetic": "Charges do not match the published tariff",
    "estimated_readings": "Estimated meter readings",
    "meter_sanity": "Meter readings do not add up",
    "outage_consistency": "Billed use during a water outage",
    "line_items": "Duplicate or unknown charge",
}

ModelCaller = Callable[..., Any]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriterFinding(_Strict):
    id: str
    paragraph: str


class WriterLetter(_Strict):
    subject: str
    greeting: str
    opening: str
    findings: list[WriterFinding]
    request: str
    closing: str


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def letter_facts(bill: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    """The only data the writer model sees."""
    period = bill.get("billing_period") or {}
    return {
        "municipality": bill.get("municipality"),
        "billing_period": {"start": period.get("start"), "end": period.get("end")},
        "findings": [
            {
                "id": f["id"],
                "title": CHECK_TITLES.get(f["check"], f["check"]),
                "billed": f.get("billed"),
                "recomputed": f.get("recomputed"),
                "difference": f.get("difference"),
                "unit": f.get("unit"),
                "explanation": f["explanation"],
            }
            for f in findings
        ],
    }


def validate_letter(letter: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    expected_ids = [f["id"] for f in facts["findings"]]
    got_ids = [f["id"] for f in letter["findings"]]
    if got_ids != expected_ids:
        problems.append(f"findings must have ids {expected_ids} in this order, got {got_ids}")

    allowed = _numbers(json.dumps(facts, ensure_ascii=False))
    for name, text in _letter_texts(letter):
        if not text.strip():
            problems.append(f"{name} is empty")
        for phrase in sorted({m.group(0).lower() for m in _BANNED_RE.finditer(text)}):
            problems.append(f"{name} uses '{phrase}', which is not allowed")
        extra = sorted(_numbers(text) - allowed)
        if extra:
            problems.append(f"{name} contains numbers not in the findings: {', '.join(extra)}")

    by_id = {f["id"]: f for f in facts["findings"]}
    for item in letter["findings"]:
        fact = by_id.get(item["id"])
        if not fact:
            continue
        for key in ("billed", "recomputed"):
            if fact.get(key) and fact[key] not in item["paragraph"]:
                problems.append(f"paragraph {item['id']} must state the {key} figure {fact[key]}")

    request = letter["request"].lower()
    if "review" not in request:
        problems.append("request must ask for a review")
    if "written" not in request and "in writing" not in request:
        problems.append("request must ask for a written response")
    return problems


def write_letter(
    bill: dict[str, Any],
    findings: list[dict[str, Any]],
    call_model: ModelCaller | None,
    *,
    job_id: str | None = None,
    letter_date: date | None = None,
) -> dict[str, Any] | None:
    """Returns `{subject, text, source: writer|template, notes}` or None when there is nothing to dispute."""
    if not findings:
        return None
    facts = letter_facts(bill, findings)
    notes: list[str] = []
    wording = None
    if call_model is not None:
        payload: dict[str, Any] = dict(facts)
        for _ in range(MAX_WRITER_ATTEMPTS):
            raw = call_model("writer", job_id, load_prompt(), json.dumps(payload, ensure_ascii=False), schema=WriterLetter, max_tokens=MAX_TOKENS)
            if not isinstance(raw, dict) or raw.get("error"):
                notes.append("Writer model did not return a letter")
                break
            try:
                candidate = WriterLetter.model_validate(raw).model_dump()
            except ValueError as exc:
                notes.append(f"Writer output failed schema validation: {exc}"[:300])
                break
            problems = validate_letter(candidate, facts)
            if not problems:
                wording = candidate
                break
            notes.append("Writer letter rejected: " + "; ".join(problems)[:500])
            payload = {**facts, "previous_attempt": {"letter": candidate, "problems": problems}}

    source = "writer" if wording else "template"
    wording = wording or template_wording(facts)
    return {
        "subject": wording["subject"],
        "text": assemble_letter(bill, findings, wording, letter_date or date.today()),
        "source": source,
        "notes": notes,
    }


def template_wording(facts: dict[str, Any]) -> dict[str, Any]:
    period = facts["billing_period"]
    when = f"{_v(period.get('start'))} to {_v(period.get('end'))}"
    return {
        "subject": f"Request to review water account for the period {when}",
        "greeting": "Dear Accounts Department,",
        "opening": (
            f"I have checked my water account for the period {when} against the published tariff "
            "and found the points listed below."
        ),
        "findings": [{"id": f["id"], "paragraph": f"{f['title']}. {f['explanation']}"} for f in facts["findings"]],
        "request": (
            "Please review these points and correct the account if you agree. "
            "I would be grateful for a written response explaining the outcome of the review."
        ),
        "closing": "Kind regards,",
    }


def assemble_letter(bill: dict[str, Any], findings: list[dict[str, Any]], wording: dict[str, Any], letter_date: date) -> str:
    period = bill.get("billing_period") or {}
    receipts = {f["id"]: f.get("receipt_ids") or [] for f in findings}
    lines = [
        f"To: Accounts Department, {_v(bill.get('municipality'))}",
        f"Date: {letter_date.isoformat()}",
        "",
        f"Account number: {_v(bill.get('account_number'))}",
        f"Account holder: {_v(bill.get('account_holder'))}",
        f"Service address: {_v(bill.get('service_address'))}",
        f"Invoice number: {_v(bill.get('invoice_number'))}",
        f"Billing period: {_v(period.get('start'))} to {_v(period.get('end'))}",
        "",
        f"Subject: {wording['subject']}",
        "",
        wording["greeting"],
        "",
        wording["opening"],
        "",
    ]
    for number, item in enumerate(wording["findings"], start=1):
        refs = receipts.get(item["id"]) or []
        evidence = f" (Evidence: receipts {', '.join(refs)})" if refs else ""
        lines += [f"{number}. {item['paragraph'].strip()}{evidence}", ""]
    lines += [
        wording["request"],
        "",
        wording["closing"],
        _v(bill.get("account_holder")),
    ]
    return "\n".join(lines) + "\n"


def _v(value: Any) -> str:
    return MISSING if value in (None, "", UNREADABLE) else str(value)


def _numbers(text: str) -> set[str]:
    """Every number token plus its parts ("875.15" -> 875.15, 875, 15). Integers lose leading zeros so "09" == "9"."""
    found: set[str] = set()
    for token in _NUMBER_RE.findall(text):
        found.add(_norm(token))
        found.update(_norm(part) for part in re.split(r"[.,]", token))
    return found


def _norm(token: str) -> str:
    token = token.replace(",", "")
    return token if "." in token else (token.lstrip("0") or "0")


def _letter_texts(letter: dict[str, Any]):
    for key in ("subject", "greeting", "opening", "request", "closing"):
        yield key, letter[key]
    for item in letter["findings"]:
        yield f"paragraph {item['id']}", item["paragraph"]
