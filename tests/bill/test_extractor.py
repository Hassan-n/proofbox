import copy
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from lenses.bill import extractor as ex

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sandbox" / "code"))
sys.path.insert(0, str(REPO / "scripts"))

import generate_fixtures as gf  # noqa: E402
import parse_bill as pb  # noqa: E402

STUBS = REPO / "fixtures" / "stubs"


class FakeGateway:
    """Mirrors apps/api/gateway.py call_model: 3 attempts, schema-validated, then unreadable."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def __call__(self, role, job_id, system_prompt, untrusted_data, schema=None, **_):
        last_error = ""
        for attempt in range(3):
            self.prompts.append(untrusted_data + (f"\nPrevious response failed validation: {last_error}" if attempt else ""))
            raw = self.responses.pop(0) if self.responses else "{}"
            try:
                return schema.model_validate_json(raw).model_dump()
            except Exception as error:
                last_error = str(error)
        return {"error": "unreadable", "detail": last_error}


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    gf.generate(out, tmp_path_factory.mktemp("stubs"))
    return {
        "A5": pb.parse_pdf(out / "A5_bill_clean.pdf"),
        "A6": pb.parse_pdf(out / "A6_bill_errors.pdf"),
        "A7": pb.parse_pdf(out / "A7_bill_injection.pdf"),
    }


def stub(fixture_id):
    return json.loads((STUBS / f"bill_extractor_{fixture_id}.json").read_text(encoding="utf-8"))


def run_with(parsed_doc, bill):
    return ex.extract_bill(parsed_doc, FakeGateway([json.dumps(bill)]))


@pytest.mark.parametrize("fixture_id", ["A5", "A6"])
def test_stub_extraction_is_fully_grounded(parsed, fixture_id):
    result = ex.extract_bill(parsed[fixture_id], ex.StubExtractor(STUBS), job_id="job-1")

    assert result["status"] == "ok"
    assert result["unreadable_fields"] == []
    assert result["notes"] == []
    assert result["bill"] == stub(fixture_id)


def test_a7_extracts_same_bill_as_a6_and_model_never_sees_injection(parsed):
    model = ex.StubExtractor(STUBS)

    a6 = ex.extract_bill(parsed["A6"], model)
    a7 = ex.extract_bill(parsed["A7"], model)

    assert a7 == a6
    assert "ignore previous instructions" not in model.calls[-1]["text"].lower()
    assert model.calls[-1]["role"] == "extractor"


def test_stub_extractor_returns_unreadable_for_unknown_document():
    result = ex.extract_bill({"text": "--- page 1 ---\nSome other document"}, ex.StubExtractor(STUBS))

    assert result["status"] == "unreadable"
    assert result["bill"] is None


def test_empty_text_is_unreadable_without_model_call():
    model = FakeGateway([])

    result = ex.extract_bill({"text": "  \n "}, model)

    assert result["status"] == "unreadable"
    assert model.prompts == []


def test_retries_twice_then_unreadable(parsed):
    model = FakeGateway(["not json", '{"total_due": "1"}', json.dumps({**stub("A6"), "verdict": "approved"})])

    result = ex.extract_bill(parsed["A6"], model)

    assert len(model.prompts) == 3
    assert "Previous response failed validation" in model.prompts[1]
    assert result["status"] == "unreadable"
    assert "after retries" in result["notes"][0]


def test_recovers_on_second_attempt(parsed):
    model = FakeGateway(["```garbage", json.dumps(stub("A6"))])

    result = ex.extract_bill(parsed["A6"], model)

    assert len(model.prompts) == 2
    assert result["status"] == "ok"
    assert result["unreadable_fields"] == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(verdict="approved"),
        lambda b: b.update(total_due="R 875.15"),
        lambda b: b.update(total_due="875,15"),
        lambda b: b.update(issue_date="05/10/2026"),
        lambda b: b["meter_readings"][0].update(type="guess"),
        lambda b: b["tariff_lines"][0].update(amount="-90.00"),
        lambda b: b.pop("vat"),
    ],
)
def test_schema_rejects_bad_shapes(mutate):
    bill = stub("A6")
    mutate(bill)

    with pytest.raises(ValidationError):
        ex.BillExtraction.model_validate(bill)


def test_unreadable_values_pass_schema():
    bill = stub("A6")
    bill.update(total_due="unreadable", issue_date="unreadable")
    bill["meter_readings"][0]["type"] = "unreadable"

    assert ex.BillExtraction.model_validate(bill).total_due == "unreadable"


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda b: b.update(total_due="999.99"), "total_due"),
        (lambda b: b.update(account_number="9999 0000 01"), "account_number"),
        (lambda b: b.update(account_holder="Someone Else"), "account_holder"),
        (lambda b: b.update(vat_rate="0.14"), "vat_rate"),
        (lambda b: b["billing_period"].update(end="2026-10-31"), "billing_period.end"),
        (lambda b: b["tariff_lines"][1].update(rate_per_kl="25.00"), "tariff_lines[1].rate_per_kl"),
        (lambda b: b["fixed_charges"][0].update(amount="125.00"), "fixed_charges[0].amount"),
        (lambda b: b["meter_readings"][2].update(type="actual"), "meter_readings[2].type"),
        (lambda b: b["meter_readings"][0].update(reading_kl="2380.0"), "meter_readings[0].reading_kl"),
    ],
)
def test_values_not_in_document_become_unreadable(parsed, mutate, path):
    bill = stub("A6")
    mutate(bill)

    result = run_with(parsed["A6"], bill)

    assert result["status"] == "ok"
    assert result["unreadable_fields"] == [path]
    node = result["bill"]
    for part in path.replace("]", "").replace("[", ".").split("."):
        node = node[int(part)] if part.isdigit() else node[part]
    assert node == "unreadable"


def test_grounding_does_not_correct_real_bill_errors(parsed):
    result = run_with(parsed["A6"], stub("A6"))

    assert result["bill"]["tariff_lines"][1]["rate_per_kl"] == "38.00"
    assert result["bill"]["total_due"] == "875.15"


def test_number_formatting_differences_are_accepted():
    text = "Total due R 1,234.50\nConsumption 18 kl"

    assert ex._document_numbers(text) >= {ex.Decimal("1234.50"), ex.Decimal("18")}


def test_model_reported_unreadable_is_listed(parsed):
    bill = stub("A6")
    bill["vat"] = "unreadable"
    bill["meter_readings"][1]["reading_kl"] = "unreadable"

    result = run_with(parsed["A6"], bill)

    assert sorted(result["unreadable_fields"]) == ["meter_readings[1].reading_kl", "vat"]


def test_reversed_period_is_unreadable():
    bill = stub("A6")
    bill["billing_period"] = {"start": "2026-09-30", "end": "2026-09-01"}
    text = json.dumps(bill)

    result = run_with({"text": text}, bill)

    assert result["bill"]["billing_period"] == {"start": "unreadable", "end": "unreadable"}
    assert "start is after its end" in result["notes"][0]


def test_impossible_date_is_unreadable():
    bill = stub("A6")
    bill["issue_date"] = "2026-02-30"

    result = run_with({"text": json.dumps(bill)}, bill)

    assert result["bill"]["issue_date"] == "unreadable"
    assert "issue_date" in result["unreadable_fields"]


def test_implausible_vat_rate_is_unreadable():
    bill = stub("A6")
    bill["vat_rate"] = "0.50"
    text = json.dumps(bill) + "\nVAT 50%"

    result = run_with({"text": text}, bill)

    assert result["bill"]["vat_rate"] == "unreadable"
    assert "implausible" in result["notes"][0]


def test_input_bill_is_not_mutated_by_caller_stub(parsed):
    bill = stub("A6")
    original = copy.deepcopy(bill)

    run_with(parsed["A6"], bill)

    assert bill == original


def test_prompt_warns_about_untrusted_instructions():
    prompt = ex.load_prompt()

    assert "untrusted" in prompt
    assert '"unreadable"' in prompt
    assert "Never guess" in prompt
