import json
import sys
from datetime import date
from pathlib import Path

import pytest

from lenses.bill.analyst import InMemoryReceipts
from lenses.bill.extractor import StubExtractor
from lenses.bill.pipeline import run_bill_lens
from lenses.bill.runners import LocalSubprocessRunner
from lenses.bill.writer import _BANNED_RE

ROOT = Path(__file__).resolve().parents[2]
STUBS = ROOT / "fixtures" / "stubs"
sys.path.insert(0, str(ROOT / "sandbox" / "code"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_fixtures as gf  # noqa: E402
import parse_bill as pb  # noqa: E402
from test_analyst import GOOD_CODE  # noqa: E402


class RoleGateway:
    """Stub extractor + canned analyst code; the writer returns an error so the template is used."""

    def __init__(self, writer_reply=None):
        self.extractor = StubExtractor(STUBS)
        self.writer_reply = writer_reply or {"error": "unreadable", "detail": "stub"}
        self.roles = []

    def __call__(self, role, job_id, system_prompt, untrusted_data, schema=None, **kwargs):
        self.roles.append(role)
        if role == "extractor":
            return self.extractor(role, job_id, system_prompt, untrusted_data, schema=schema)
        if role == "analyst_coder":
            return {"code": GOOD_CODE}
        return self.writer_reply


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixtures")
    gf.generate(out, out / "stubs")
    return {
        "A5": pb.parse_pdf(out / "A5_bill_clean.pdf"),
        "A6": pb.parse_pdf(out / "A6_bill_errors.pdf"),
        "A7": pb.parse_pdf(out / "A7_bill_injection.pdf"),
        "history": json.loads((out / "A8_history.json").read_text(encoding="utf-8")),
    }


def run(doc, history, gateway=None, runner=..., events=None):
    receipts = InMemoryReceipts()
    result = run_bill_lens(
        doc,
        history=history,
        call_model=gateway or RoleGateway(),
        runner=LocalSubprocessRunner(timeout_s=10) if runner is ... else runner,
        save_receipt=receipts,
        emit=(lambda t, d: events.append(t)) if events is not None else None,
        job_id="job-1",
        letter_date=date(2026, 11, 4),
    )
    return result, receipts


def test_clean_bill_has_no_findings_and_no_letter(docs):
    result, _ = run(docs["A5"], None)
    assert result["status"] == "ok" and result["findings"] == [] and result["dispute_letter"] is None
    assert result["summary"]["billed_total"] == result["summary"]["recomputed_total"] == "740.60"


def test_errors_bill_every_finding_has_receipts(docs):
    events = []
    result, receipts = run(docs["A6"], docs["history"], events=events)
    assert [f["check"] for f in result["findings"]] == ["arithmetic", "estimated_readings", "outage_consistency"]
    for finding in result["findings"]:
        assert finding["receipt_ids"], finding
        assert all(r in receipts.items for r in finding["receipt_ids"])
        assert all(r in result["receipts"] for r in finding["receipt_ids"])
    arithmetic = result["findings"][0]
    assert len(arithmetic["receipt_ids"]) == 4
    assert result["analyst"]["status"] == "agreed"
    assert result["summary"] == {"findings": 3, "billed_total": "875.15", "recomputed_total": "740.60"}
    assert result["dispute_letter"]["source"] == "template"
    assert "Account number: 1004 7781 02" in result["dispute_letter"]["text"]
    assert not _BANNED_RE.search(result["dispute_letter"]["text"])
    assert events[:2] == ["bill_extracted", "checks_completed"] and "letter_drafted" in events
    extract = json.loads(receipts.items[arithmetic["receipt_ids"][0]]["content"])
    assert extract["extracted"]["total_due"] == "875.15" and "document_text" in extract


def test_injection_bill_is_contained(docs):
    events = []
    a6, _ = run(docs["A6"], docs["history"])
    a7, _ = run(docs["A7"], docs["history"], events=events)
    assert [f["check"] for f in a7["findings"]] == [f["check"] for f in a6["findings"]]
    assert a7["events"] and a7["events"][0]["type"] == "instruction_ignored"
    assert events[0] == "instruction_ignored"
    assert "ignore previous" not in a7["dispute_letter"]["text"].lower()


def test_without_runner_analyst_is_skipped(docs):
    result, _ = run(docs["A6"], docs["history"], runner=None)
    assert result["analyst"]["status"] == "failed"
    assert any(s["check"] == "analyst_coder" for s in result["skipped_checks"])
    assert all(f["receipt_ids"] for f in result["findings"])


def test_unreadable_document(docs):
    doc = {"text": "nothing useful here", "events": []}
    result, _ = run(doc, None)
    assert result["status"] == "unreadable" and result["findings"] == []
    assert result["dispute_letter"] is None and result["skipped_checks"][-1]["check"] == "all"
