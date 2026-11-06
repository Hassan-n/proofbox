import json
import re
import unicodedata
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path


def _read_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _subtract_months(value, months):
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _normalized_name(value):
    decomposed = unicodedata.normalize("NFKD", value or "")
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", plain.casefold()).split())


def _name_status(expected, actual):
    left, right = _normalized_name(expected), _normalized_name(actual)
    if not left or not right:
        return "needs_checking"
    if left == right:
        return "match"
    left_parts, right_parts = left.split(), right.split()
    if left_parts[-1:] == right_parts[-1:] and min(len(left_parts), len(right_parts)) > 1:
        shorter, longer = (left_parts, right_parts) if len(left_parts) < len(right_parts) else (right_parts, left_parts)
        if all(a == b or (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b)) for a, b in zip(shorter, longer)):
            return "needs_checking"
    return "mismatch"


def _id_valid(value, reference_date):
    if not re.fullmatch(r"\d{13}", value):
        return False
    digits = [int(char) for char in value]
    checksum = sum(
        (digit * 2 - 9 if digit * 2 > 9 else digit * 2) if index % 2 == 0 else digit
        for index, digit in enumerate(reversed(digits[:-1]))
    )
    if (checksum + digits[-1]) % 10:
        return False
    year = int(value[:2])
    cutoff = reference_date.year % 100
    year += 2000 if year <= cutoff else 1900
    try:
        date(year, int(value[2:4]), int(value[4:6]))
    except ValueError:
        return False
    return True


def _field(text, pattern):
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _classify(filename, pages):
    value = _normalized_name(filename)
    tokens = set(value.split())
    text = "\n".join(pages).casefold()
    if tokens.intersection({"id", "identity", "identification"}) or "id number" in text or "identity number" in text:
        return "id_copy"
    if any(part in value for part in ("address", "proof", "residence")):
        return "proof_of_address"
    if "bank" in value or "statement" in value or "statement period" in text:
        return "bank_statement"
    if "declaration" in value or "signed" in value:
        return "signed_declaration"
    return ""


def _check_id(documents, reference_date):
    matches = [doc for doc in documents if doc["kind"] == "id_copy"]
    if not matches:
        return {"key": "id_copy", "label": "ID copy", "status": "missing", "reason": "No ID copy was provided."}
    for doc in matches:
        text = "\n".join(doc["page_texts"])
        numbers = re.findall(r"(?<!\d)\d{13}(?!\d)", text)
        if any(_id_valid(number, reference_date) for number in numbers):
            return {"key": "id_copy", "label": "ID copy", "status": "have", "reason": "A valid ID number and check digit were found."}
    return {"key": "id_copy", "label": "ID copy", "status": "needs_fixing", "reason": "The ID number could not be validated; check that the copy is readable."}


def _check_address(documents, expected_name, reference_date):
    matches = [doc for doc in documents if doc["kind"] == "proof_of_address"]
    if not matches:
        return {"key": "proof_of_address", "label": "Proof of address", "status": "missing", "reason": "No proof of address was provided."}
    cutoff = _subtract_months(reference_date, 3)
    has_initials_match = False
    has_missing_date = False
    for doc in matches:
        text = "\n".join(doc["page_texts"])
        actual_name = _field(text, r"^\s*Name\s*:\s*(.+?)\s*$")
        date_text = _field(text, r"^\s*(?:Document\s+date|Date)\s*:\s*(\d{4}-\d{2}-\d{2})\s*$")
        document_date = _read_date(date_text)
        name_status = _name_status(expected_name, actual_name)
        if not document_date:
            has_missing_date = True
            continue
        if document_date < cutoff or name_status == "mismatch":
            continue
        if name_status == "match":
            return {"key": "proof_of_address", "label": "Proof of address", "status": "have", "reason": "The named document is dated within the last three months."}
        has_initials_match = name_status == "needs_checking"
    if has_initials_match:
        return {"key": "proof_of_address", "label": "Proof of address", "status": "needs_fixing", "reason": "The name differs by initials or is unreadable; please check it manually."}
    if has_missing_date:
        return {"key": "proof_of_address", "label": "Proof of address", "status": "needs_fixing", "reason": "The document date could not be read."}
    return {"key": "proof_of_address", "label": "Proof of address", "status": "needs_fixing", "reason": "The document is older than three months."}


def _check_bank(documents, expected_name, reference_date, months_required):
    matches = [doc for doc in documents if doc["kind"] == "bank_statement"]
    if not matches:
        return {"key": "bank_statement", "label": "Bank statement", "status": "missing", "reason": "No bank statement was provided."}
    cutoff = _subtract_months(reference_date, months_required)
    last_full_month = date(reference_date.year, reference_date.month, 1) - timedelta(days=1)
    for doc in matches:
        text = "\n".join(doc["page_texts"])
        period = re.search(r"Statement\s+period\s*:\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
        if not period:
            continue
        start, end = _read_date(period.group(1)), _read_date(period.group(2))
        page_refs = [tuple(map(int, item)) for item in re.findall(r"\bPage\s+(\d+)\s+of\s+(\d+)\b", text, re.IGNORECASE)]
        pages_complete = bool(page_refs) and all(total == len(doc["page_texts"]) for _, total in page_refs) and {page for page, _ in page_refs} == set(range(1, len(doc["page_texts"]) + 1))
        name_status = _name_status(expected_name, _field(text, r"^\s*Name\s*:\s*(.+?)\s*$"))
        if not start or not end or start > cutoff or end < last_full_month or not pages_complete or name_status == "mismatch":
            continue
        if name_status == "match":
            return {"key": "bank_statement", "label": "Bank statement", "status": "have", "reason": "The statement covers the requested period and all pages are present."}
        return {"key": "bank_statement", "label": "Bank statement", "status": "needs_fixing", "reason": "The name differs by initials or is unreadable; please check it manually."}
    return {"key": "bank_statement", "label": "Bank statement", "status": "needs_fixing", "reason": "Check the statement period, account name, and page sequence."}


def _check_declaration(documents):
    if any(doc["kind"] == "signed_declaration" for doc in documents):
        return {"key": "signed_declaration", "label": "Signed declaration", "status": "have", "reason": "A declaration file was provided; its contents were not inspected."}
    return {"key": "signed_declaration", "label": "Signed declaration", "status": "missing", "reason": "No signed declaration was provided."}


def run_checks(data):
    reference_date = _read_date(data.get("check_date")) or date.today()
    documents = data.get("documents", [])
    for doc in documents:
        doc["kind"] = _classify(doc.get("filename", ""), doc.get("page_texts", []))
    facts = data.get("letter", {})
    checks_by_key = {
        "id_copy": _check_id(documents, reference_date),
        "proof_of_address": _check_address(documents, facts.get("applicant_name", ""), reference_date),
        "bank_statement": _check_bank(documents, facts.get("applicant_name", ""), reference_date, int(data.get("bank_statement_months_required", 3))),
        "signed_declaration": _check_declaration(documents),
    }
    requested = set()
    unrecognized = []
    for requirement in facts.get("required_documents", []):
        value = _normalized_name(requirement)
        if set(value.split()).intersection({"id", "identity", "identification"}):
            requested.add("id_copy")
        elif "address" in value or "residence" in value:
            requested.add("proof_of_address")
        elif "bank" in value or "statement" in value:
            requested.add("bank_statement")
        elif "declaration" in value:
            requested.add("signed_declaration")
        else:
            unrecognized.append(requirement)
    checks = [
        checks_by_key[key]
        for key in ("id_copy", "proof_of_address", "bank_statement", "signed_declaration")
        if key in requested
    ]
    checks.extend(
        {
            "key": "other_request",
            "label": str(requirement)[:160],
            "status": "needs_fixing",
            "reason": "Please check this request manually; no automatic check is available.",
        }
        for requirement in unrecognized
    )
    deadline = _read_date(facts.get("response_deadline"))
    appointment_date = _read_date(facts.get("appointment_date"))
    return {
        "status": "ok",
        "checks": checks,
        "clocks": [
            {"name": "Response deadline", "due_at": deadline.isoformat(), "rule_ref": "grant_review.response_deadline"}
            for _ in [0]
            if deadline
        ] + [
            {"name": "Appointment", "due_at": appointment_date.isoformat(), "rule_ref": "grant_review.appointment"}
            for _ in [0]
            if appointment_date
        ],
    }


def main():
    path = Path(INPUT_DIR) / "letter.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(run_checks(data), ensure_ascii=True))


if __name__ == "__main__":
    main()
