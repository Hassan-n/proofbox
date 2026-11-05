"""Bill Lens extractor: model output -> validated, document-grounded bill JSON.

Three layers, in order:
1. Schema (`BillExtraction`, Pydantic, extra fields forbidden). Passed to the model
   gateway, which retries twice with the validation error and then returns
   `{"error": "unreadable"}`.
2. Grounding: every number and identifier must appear in the parsed document
   text; anything that does not is replaced with "unreadable" rather than trusted.
3. Sanity rules: dates parse, period start <= end, VAT rate plausible.

The model caller is injected so this module never imports the gateway (and its
database pool) directly. Its signature matches the gateway's `call_model`.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, field_validator

UNREADABLE = "unreadable"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "bill_extractor.md"
MAX_VAT_RATE = Decimal("0.30")

_NUMBER_RE = re.compile(r"^\d+(\.\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TEXT_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

ModelCaller = Callable[..., Any]


def _number(value: str) -> str:
    if value != UNREADABLE and not _NUMBER_RE.fullmatch(value):
        raise ValueError(f'must be digits with optional decimals, or "{UNREADABLE}" (got {value!r})')
    return value


def _date(value: str) -> str:
    if value != UNREADABLE and not _DATE_RE.fullmatch(value):
        raise ValueError(f'must be YYYY-MM-DD or "{UNREADABLE}" (got {value!r})')
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BillingPeriod(_Strict):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def check_dates(cls, value: str) -> str:
        return _date(value)


class MeterReading(_Strict):
    date: str
    reading_kl: str
    type: Literal["actual", "estimated", "unreadable"]

    @field_validator("date")
    @classmethod
    def check_date(cls, value: str) -> str:
        return _date(value)

    @field_validator("reading_kl")
    @classmethod
    def check_number(cls, value: str) -> str:
        return _number(value)


class TariffLine(_Strict):
    description: str
    quantity_kl: str
    rate_per_kl: str
    amount: str

    @field_validator("quantity_kl", "rate_per_kl", "amount")
    @classmethod
    def check_numbers(cls, value: str) -> str:
        return _number(value)


class FixedCharge(_Strict):
    description: str
    amount: str

    @field_validator("amount")
    @classmethod
    def check_number(cls, value: str) -> str:
        return _number(value)


class BillExtraction(_Strict):
    municipality: str
    account_number: str
    account_holder: str
    service_address: str
    invoice_number: str
    issue_date: str
    billing_period: BillingPeriod
    meter_number: str
    meter_readings: list[MeterReading]
    consumption_kl: str
    tariff_lines: list[TariffLine]
    fixed_charges: list[FixedCharge]
    subtotal: str
    vat_rate: str
    vat: str
    total_due: str

    @field_validator("issue_date")
    @classmethod
    def check_date(cls, value: str) -> str:
        return _date(value)

    @field_validator("consumption_kl", "subtotal", "vat_rate", "vat", "total_due")
    @classmethod
    def check_numbers(cls, value: str) -> str:
        return _number(value)


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def extract_bill(parsed: dict[str, Any], call_model: ModelCaller, job_id: str | None = None) -> dict[str, Any]:
    """Run the extractor role on parse_bill output and return a validated result.

    Returns `{"status": "ok" | "unreadable", "bill": dict | None,
    "unreadable_fields": [...], "notes": [...]}`.
    """
    text = parsed.get("text") or ""
    if not text.strip():
        return _unreadable("No text could be read from the document")

    raw = call_model("extractor", job_id, load_prompt(), text, schema=BillExtraction)
    if not isinstance(raw, dict) or raw.get("error"):
        detail = raw.get("detail", "") if isinstance(raw, dict) else "unexpected gateway response"
        return _unreadable(f"Extractor did not return a valid bill after retries: {detail}"[:500])

    try:
        bill = BillExtraction.model_validate(raw).model_dump()
    except ValueError as exc:
        return _unreadable(f"Extractor output failed schema validation: {exc}"[:500])

    unreadable_fields: list[str] = []
    notes: list[str] = []
    _ground(bill, text, unreadable_fields)
    _sanity(bill, unreadable_fields, notes)
    unreadable_fields.extend(path for path, value in _walk(bill) if value == UNREADABLE and path not in unreadable_fields)
    return {"status": "ok", "bill": bill, "unreadable_fields": unreadable_fields, "notes": notes}


def _unreadable(note: str) -> dict[str, Any]:
    return {"status": "unreadable", "bill": None, "unreadable_fields": [], "notes": [note]}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _document_numbers(text: str) -> set[Decimal]:
    numbers = set()
    for token in _TEXT_NUMBER_RE.findall(text):
        try:
            numbers.add(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    return numbers


def _ground(bill: dict[str, Any], text: str, unreadable_fields: list[str]) -> None:
    normalised = _normalise(text)
    lines = [_normalise(line) for line in text.splitlines()]
    numbers = _document_numbers(text)
    percents = {Decimal(p) for p in _PERCENT_RE.findall(text)}

    def mark(container: dict[str, Any], key: str, path: str) -> None:
        container[key] = UNREADABLE
        unreadable_fields.append(path)

    def check_number(container: dict[str, Any], key: str, path: str) -> None:
        if container[key] != UNREADABLE and Decimal(container[key]) not in numbers:
            mark(container, key, path)

    def check_text(container: dict[str, Any], key: str, path: str) -> None:
        value = container[key]
        if value != UNREADABLE and _normalise(value) not in normalised:
            mark(container, key, path)

    for key in ("municipality", "account_number", "account_holder", "service_address", "invoice_number", "meter_number", "issue_date"):
        check_text(bill, key, key)
    for key in ("start", "end"):
        check_text(bill["billing_period"], key, f"billing_period.{key}")
    for key in ("consumption_kl", "subtotal", "vat", "total_due"):
        check_number(bill, key, key)
    if bill["vat_rate"] != UNREADABLE and Decimal(bill["vat_rate"]) * 100 not in percents:
        mark(bill, "vat_rate", "vat_rate")

    for index, reading in enumerate(bill["meter_readings"]):
        path = f"meter_readings[{index}]"
        check_text(reading, "date", f"{path}.date")
        check_number(reading, "reading_kl", f"{path}.reading_kl")
        if reading["type"] != UNREADABLE:
            date_text = _normalise(reading["date"])
            reading_lines = [line for line in lines if date_text != UNREADABLE and date_text in line]
            if not any(reading["type"] in line for line in reading_lines):
                mark(reading, "type", f"{path}.type")
    for index, line in enumerate(bill["tariff_lines"]):
        path = f"tariff_lines[{index}]"
        check_text(line, "description", f"{path}.description")
        for key in ("quantity_kl", "rate_per_kl", "amount"):
            check_number(line, key, f"{path}.{key}")
    for index, charge in enumerate(bill["fixed_charges"]):
        path = f"fixed_charges[{index}]"
        check_text(charge, "description", f"{path}.description")
        check_number(charge, "amount", f"{path}.amount")


def _sanity(bill: dict[str, Any], unreadable_fields: list[str], notes: list[str]) -> None:
    def parse(value: str, path: str) -> date | None:
        if value == UNREADABLE:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            notes.append(f"{path} is not a real date: {value}")
            unreadable_fields.append(path)
            return None

    period = bill["billing_period"]
    start = parse(period["start"], "billing_period.start")
    end = parse(period["end"], "billing_period.end")
    if start is None and period["start"] != UNREADABLE:
        period["start"] = UNREADABLE
    if end is None and period["end"] != UNREADABLE:
        period["end"] = UNREADABLE
    if start and end and start > end:
        notes.append("Billing period start is after its end; period marked unreadable")
        period["start"] = period["end"] = UNREADABLE
        unreadable_fields.extend(["billing_period.start", "billing_period.end"])

    if parse(bill["issue_date"], "issue_date") is None and bill["issue_date"] != UNREADABLE:
        bill["issue_date"] = UNREADABLE
    for index, reading in enumerate(bill["meter_readings"]):
        if parse(reading["date"], f"meter_readings[{index}].date") is None and reading["date"] != UNREADABLE:
            reading["date"] = UNREADABLE

    if bill["vat_rate"] != UNREADABLE and Decimal(bill["vat_rate"]) > MAX_VAT_RATE:
        notes.append(f"VAT rate {bill['vat_rate']} is implausible; marked unreadable")
        bill["vat_rate"] = UNREADABLE
        unreadable_fields.append("vat_rate")


def _walk(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    else:
        yield path, value


class StubExtractor:
    """Offline stand-in for the gateway (MODEL_GATEWAY_MODE=stub).

    Returns the canned `fixtures/stubs/bill_extractor_*.json` whose account number
    appears in the document text, or the gateway's unreadable result if none does.
    """

    def __init__(self, stubs_dir: str | Path):
        self.stubs = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(Path(stubs_dir).glob("bill_extractor_*.json"))
        ]
        self.calls: list[dict[str, Any]] = []

    def __call__(self, role, job_id, system_prompt, untrusted_data, schema=None, **_kwargs):
        self.calls.append({"role": role, "job_id": job_id, "text": untrusted_data})
        for stub in self.stubs:
            if stub["account_number"] in untrusted_data:
                return schema.model_validate(stub).model_dump() if schema else stub
        return {"error": UNREADABLE, "detail": "no stub matches this document"}
