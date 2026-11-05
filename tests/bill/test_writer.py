import copy
import json
from datetime import date

import pytest

from lenses.bill import writer as wr

BILL = {
    "municipality": "Karoo Bay Metro",
    "account_number": "KBM-4471-0093",
    "account_holder": "T. Mokoena",
    "service_address": "14 Protea Street",
    "invoice_number": "unreadable",
    "billing_period": {"start": "2026-09-01", "end": "2026-09-30"},
}
FINDINGS = [
    {"id": "F1", "check": "arithmetic", "billed": "875.15", "recomputed": "740.60", "difference": "134.55", "unit": "R",
     "explanation": "Billed total is R875.15; the tariff gives R740.60.", "receipt_ids": ["rcpt-1", "rcpt-2"]},
    {"id": "F2", "check": "estimated_readings", "billed": None, "recomputed": None, "difference": None, "unit": "kl",
     "explanation": "2 consecutive meter readings are estimated.", "receipt_ids": ["rcpt-1"]},
]
GOOD = {
    "subject": "Request to review my water account for September 2026",
    "greeting": "Dear Accounts Department,",
    "opening": "I have checked my water account for 2026-09-01 to 2026-09-30 and would like to raise two points.",
    "findings": [
        {"id": "F1", "paragraph": "The bill shows a total of R875.15, but the published tariff gives R740.60, a difference of R134.55."},
        {"id": "F2", "paragraph": "The last 2 meter readings were estimated rather than read from the meter."},
    ],
    "request": "Please review these points and send me a written response with the corrected amount.",
    "closing": "Kind regards,",
}


class Scripted:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, role, job_id, system_prompt, untrusted_data, schema=None, max_tokens=1500, **_):
        self.calls.append({"role": role, "data": json.loads(untrusted_data)})
        return self.replies.pop(0)


def test_no_findings_no_letter():
    assert wr.write_letter(BILL, [], Scripted()) is None


def test_good_letter_is_used_and_code_adds_details():
    gateway = Scripted(copy.deepcopy(GOOD))
    letter = wr.write_letter(BILL, FINDINGS, gateway, letter_date=date(2026, 11, 4))
    assert letter["source"] == "writer" and letter["notes"] == []
    text = letter["text"]
    assert "Account number: KBM-4471-0093" in text
    assert f"Invoice number: {wr.MISSING}" in text
    assert "1. The bill shows a total of R875.15" in text and "(Evidence: receipts rcpt-1, rcpt-2)" in text
    assert "2. The last 2 meter readings" in text
    assert text.rstrip().endswith("T. Mokoena")
    assert gateway.calls[0]["role"] == "writer"
    sent = gateway.calls[0]["data"]
    assert "account_number" not in json.dumps(sent) and [f["id"] for f in sent["findings"]] == ["F1", "F2"]


@pytest.mark.parametrize(
    "mutate, problem",
    [
        (lambda l: l["findings"][0].update(paragraph="The total is R875.15 but should be R740.60. I am entitled to a refund."), "entitled"),
        (lambda l: l.update(request="Please review this and reply in writing within 14 days."), "14"),
        (lambda l: l.update(request="Please review this and fix it."), "written"),
        (lambda l: l["findings"].reverse(), "in this order"),
        (lambda l: l["findings"][0].update(paragraph="The total is wrong."), "billed figure 875.15"),
        (lambda l: l.update(closing="Failing which I will take legal action."), "legal action"),
    ],
)
def test_validation_catches_problems(mutate, problem):
    letter = copy.deepcopy(GOOD)
    mutate(letter)
    problems = wr.validate_letter(letter, wr.letter_facts(BILL, FINDINGS))
    assert any(problem in p for p in problems), problems


def test_good_letter_validates():
    assert wr.validate_letter(GOOD, wr.letter_facts(BILL, FINDINGS)) == []


def test_retry_with_feedback_then_success():
    bad = copy.deepcopy(GOOD)
    bad["closing"] = "Failing which I will contact my lawyer."
    gateway = Scripted(bad, copy.deepcopy(GOOD))
    letter = wr.write_letter(BILL, FINDINGS, gateway)
    assert letter["source"] == "writer" and len(gateway.calls) == 2
    assert "lawyer" in json.dumps(gateway.calls[1]["data"]["previous_attempt"]["problems"])


def test_falls_back_to_template():
    bad = copy.deepcopy(GOOD)
    bad["request"] = "Pay me back now."
    letter = wr.write_letter(BILL, FINDINGS, Scripted(bad, bad))
    assert letter["source"] == "template" and len(letter["notes"]) == 2
    assert "Billed total is R875.15" in letter["text"]
    assert not wr._BANNED_RE.search(letter["text"])


def test_gateway_error_uses_template():
    letter = wr.write_letter(BILL, FINDINGS, Scripted({"error": "unreadable", "detail": "x"}))
    assert letter["source"] == "template"


def test_template_without_model_passes_its_own_validation():
    facts = wr.letter_facts(BILL, FINDINGS)
    assert wr.validate_letter(wr.template_wording(facts), facts) == []
    assert wr.write_letter(BILL, FINDINGS, None)["source"] == "template"
