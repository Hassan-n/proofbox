import json
import sys
from datetime import date
from pathlib import Path

from lenses.bill.runners import LocalSubprocessRunner
from lenses.letter import run_letter_lens

ROOT = Path(__file__).resolve().parents[2]
CHECKS_CODE = ROOT / "apps" / "api" / "lenses" / "letter_checks.py"
CHECK_DATE = date(2026, 11, 6)
sys.path.insert(0, str(ROOT / "scripts"))
import generate_letter_fixtures


def _synthetic_id():
    body = "850102500000"
    digits = [int(value) for value in body]
    checksum = sum(
        (digit * 2 - 9 if digit * 2 > 9 else digit * 2) if index % 2 == 0 else digit
        for index, digit in enumerate(reversed(digits))
    )
    return body + str((-checksum) % 10)


def _run_checks(documents, applicant_name="Jordan River"):
    payload = {
        "check_date": CHECK_DATE.isoformat(),
        "bank_statement_months_required": 3,
        "letter": {
            "applicant_name": applicant_name,
            "response_deadline": "2026-11-20",
            "appointment_date": "2026-11-27",
            "required_documents": ["ID copy", "proof of address", "bank statement", "signed declaration"],
        },
        "documents": documents,
    }
    run = LocalSubprocessRunner().run(CHECKS_CODE.read_text(encoding="utf-8"), {"letter.json": payload})
    assert run.exit_code == 0, run.stderr
    return json.loads(run.stdout)


def _good_documents():
    return [
        {"filename": "identity_copy.pdf", "page_texts": [f"Name: Jordan River\nID number: {_synthetic_id()}"]},
        {"filename": "proof_of_address.pdf", "page_texts": ["Name: Jordan River\nDocument date: 2026-10-06"]},
        {
            "filename": "bank_statement.pdf",
            "page_texts": [
                "Name: Jordan River\nStatement period: 2026-08-06 to 2026-11-06\nPage 1 of 2",
                "Name: Jordan River\nPage 2 of 2",
            ],
        },
    ]


def test_deterministic_checklist_detects_old_address_and_missing_declaration():
    documents = _good_documents()
    documents[1]["page_texts"] = ["Name: Jordan River\nDocument date: 2026-06-06"]
    checks = _run_checks(documents)["checks"]

    assert [item["status"] for item in checks] == ["have", "needs_fixing", "have", "missing"]
    assert "three months" in checks[1]["reason"]


def test_name_initials_require_manual_check_and_bank_pages_are_verified():
    documents = _good_documents()
    documents[1]["page_texts"] = ["Name: J River\nDocument date: 2026-10-06"]
    documents[2]["page_texts"][1] = "Name: Jordan River\nPage 3 of 2"
    checks = _run_checks(documents)["checks"]

    assert checks[1]["status"] == "needs_fixing"
    assert "initials" in checks[1]["reason"]
    assert checks[2]["status"] == "needs_fixing"


def test_id_is_validated_but_never_returned_in_check_output():
    documents = _good_documents()
    output = json.dumps(_run_checks(documents))
    assert _synthetic_id() not in output
    invalid_id = _synthetic_id()[:-1] + ("1" if _synthetic_id()[-1] != "1" else "2")
    documents[0]["page_texts"] = [f"Name: Jordan River\nID number: {invalid_id}"]
    assert _run_checks(documents)["checks"][0]["status"] == "needs_fixing"


def test_letter_pipeline_sends_only_letter_text_to_model_and_creates_clocks_and_receipts():
    seen = []
    saved = []

    def call_model(role, job_id, prompt, text, schema, max_tokens):
        seen.append((role, text))
        return {
            "agency": "Synthetic agency",
            "applicant_name": "Jordan River",
            "reference_number": _synthetic_id(),
            "summary": "Please provide the requested documents.",
            "response_deadline": "2026-11-20",
            "appointment_date": "2026-11-27",
            "appointment_time": "10:30",
            "appointment_place": "Civic Centre",
            "required_documents": ["ID copy", "proof of address"],
            "link": "",
        }

    def save_receipt(job_id, kind, content, metadata):
        saved.append((kind, content))
        return f"receipt-{len(saved)}"

    result = run_letter_lens(
        letter_document={"text": "Synthetic letter text only", "filename": "A9_letter.pdf", "pages": 1},
        supporting_documents=_good_documents(),
        call_model=call_model,
        runner=LocalSubprocessRunner(),
        save_receipt=save_receipt,
        emit=lambda *_: None,
        job_id="job-test",
        check_date=CHECK_DATE,
    )

    assert seen == [("extractor", "Synthetic letter text only")]
    assert [item["status"] for item in result["derived_facts"]["checklist"]] == ["have", "have"]
    assert [item["name"] for item in result["derived_facts"]["clocks"]] == ["Response deadline", "Appointment"]
    assert len(result["receipts"]) == 3
    assert _synthetic_id() not in json.dumps(saved)
    assert _synthetic_id() not in json.dumps(result)


def test_letter_fixtures_are_synthetic_and_reproducible(tmp_path):
    first = generate_letter_fixtures.generate(tmp_path)
    second = generate_letter_fixtures.generate(tmp_path)

    assert first["files"] == second["files"]
    assert first["synthetic_only"] is True
    assert "A10_id_copy.pdf" in first["files"]
