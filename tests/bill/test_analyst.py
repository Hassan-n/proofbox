import copy
import json
import sys
from pathlib import Path

import pytest

from lenses.bill.analyst import InMemoryReceipts, attach_receipts, check_code, compare, run_analyst
from lenses.bill.checks import reference_figures, run_checks
from lenses.bill.runners import LocalSubprocessRunner
from lenses.bill.tariff import load_tariff

ROOT = Path(__file__).resolve().parents[2]
STUBS = ROOT / "fixtures" / "stubs"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_fixtures  # noqa: E402

GOOD_CODE = (STUBS / "bill_analyst_coder.py").read_text(encoding="utf-8")


class ScriptedGateway:
    """Returns the queued replies in order and records every call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, role, job_id, system_prompt, untrusted_data, schema=None, max_tokens=1500, **_):
        self.calls.append({"role": role, "data": json.loads(untrusted_data), "max_tokens": max_tokens})
        reply = self.replies.pop(0)
        return {"code": reply} if isinstance(reply, str) else reply


@pytest.fixture(scope="module")
def tariff():
    return load_tariff()


@pytest.fixture(scope="module")
def runner():
    return LocalSubprocessRunner(timeout_s=10)


@pytest.fixture(scope="module")
def a5():
    return json.loads((STUBS / "bill_extractor_A5.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a6():
    return json.loads((STUBS / "bill_extractor_A6.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a8(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixtures")
    generate_fixtures.generate(out, stubs_dir=out / "stubs")
    return json.loads((out / "A8_history.json").read_text(encoding="utf-8"))


def test_reference_figures_a6(a6, a8, tariff):
    ref = reference_figures(a6, a8, tariff)
    assert ref == {
        "subtotal": "644.00",
        "vat": "96.60",
        "total": "740.60",
        "normal_kl": "18.0",
        "period_days": 30,
        "outage_days": 9,
        "supplied_days": 21,
        "implied_kl": "12.6",
    }


def test_reference_figures_without_history(a5, tariff):
    ref = reference_figures(a5, None, tariff)
    assert ref["total"] == "740.60" and ref["normal_kl"] is None and ref["implied_kl"] is None


def test_good_code_agrees_first_time(a6, a8, tariff, runner):
    gateway = ScriptedGateway(GOOD_CODE)
    receipts = InMemoryReceipts()
    result = run_analyst(a6, a8, gateway, runner, tariff=tariff, save_receipt=receipts, job_id="job-1")
    assert result["status"] == "agreed", result
    assert result["figures"]["total"] == "740.60" and result["figures"]["implied_kl"] == "12.6"
    assert all(item["agree"] for item in result["comparison"].values())
    assert len(result["attempts"]) == 1 and result["skipped_checks"] == []
    code_receipt = receipts.items[result["receipt_ids"]["code"]]
    output_receipt = receipts.items[result["receipt_ids"]["output"]]
    assert code_receipt["kind"] == "code" and code_receipt["content"].startswith("INPUT_DIR = '/inputs'")
    assert json.loads(output_receipt["content"])["total"] == "740.60"
    assert code_receipt["job_id"] == "job-1"
    call = gateway.calls[0]
    assert call["role"] == "analyst_coder" and call["max_tokens"] == 2500
    assert set(call["data"]) == {"bill", "tariff", "history"}


def test_good_code_without_history(a5, tariff, runner):
    result = run_analyst(a5, None, ScriptedGateway(GOOD_CODE), runner, tariff=tariff)
    assert result["status"] == "agreed"
    assert set(result["comparison"]) == {"subtotal", "vat", "total"}


def test_error_is_fed_back_then_fixed(a6, a8, tariff, runner):
    broken = GOOD_CODE.replace('bill.get("consumption_kl")', 'bill["consumption"]')
    gateway = ScriptedGateway(broken, GOOD_CODE)
    result = run_analyst(a6, a8, gateway, runner, tariff=tariff)
    assert result["status"] == "agreed"
    assert [a["outcome"] for a in result["attempts"]] == ["error", "ran"]
    feedback = gateway.calls[1]["data"]["previous_attempt"]
    assert feedback["code"] == broken
    assert "KeyError" in feedback["error"]
    assert "proofbox-analyst-" not in feedback["error"]
    assert '/work/main.py", line 21' in feedback["error"]


def test_gives_up_after_two_retries(a6, a8, tariff, runner):
    gateway = ScriptedGateway("raise SystemExit(3)", "print('not json')", "1/0")
    result = run_analyst(a6, a8, gateway, runner, tariff=tariff)
    assert result["status"] == "failed"
    assert len(gateway.calls) == 3
    assert [a["outcome"] for a in result["attempts"]] == ["error", "error", "error"]
    assert "ZeroDivisionError" in result["attempts"][-1]["error"]
    [skip] = result["skipped_checks"]
    assert skip["check"] == "analyst_coder" and "skipped" in skip["reason"]
    assert result["receipt_ids"] == {}


def test_disallowed_code_is_rejected_without_running(a6, a8, tariff):
    class NeverRun:
        def run(self, code, inputs):
            raise AssertionError("must not run rejected code")

    gateway = ScriptedGateway("import os\nprint(os.environ)", "import subprocess", "print(().__class__)")
    result = run_analyst(a6, a8, gateway, NeverRun(), tariff=tariff)
    assert result["status"] == "failed"
    assert [a["outcome"] for a in result["attempts"]] == ["rejected"] * 3
    assert "Import of 'os' is not allowed" in gateway.calls[1]["data"]["previous_attempt"]["error"]


def test_wrong_figures_disagree(a6, a8, tariff, runner):
    wrong = GOOD_CODE.replace('Decimal(tier["rate_per_kl"])', '(Decimal(tier["rate_per_kl"]) + 1)')
    result = run_analyst(a6, a8, ScriptedGateway(wrong), runner, tariff=tariff)
    assert result["status"] == "disagreed"
    assert result["comparison"]["total"]["agree"] is False
    assert result["comparison"]["implied_kl"]["agree"] is True
    assert "disagreed" in result["skipped_checks"][0]["reason"]
    assert result["receipt_ids"] == {}


def test_timeout(a6, a8, tariff):
    gateway = ScriptedGateway("while True:\n    pass", "while True:\n    pass", "while True:\n    pass")
    result = run_analyst(a6, a8, gateway, LocalSubprocessRunner(timeout_s=1), tariff=tariff)
    assert result["status"] == "failed"
    assert result["attempts"][0]["error"] == "The program timed out"


def test_gateway_unreadable(a6, a8, tariff, runner):
    gateway = ScriptedGateway({"error": "unreadable", "detail": "invalid json"})
    result = run_analyst(a6, a8, gateway, runner, tariff=tariff)
    assert result["status"] == "failed" and len(gateway.calls) == 1
    assert result["attempts"][0]["outcome"] == "no_code"


@pytest.mark.parametrize(
    "code, problem",
    [
        ("import os", "Import of 'os'"),
        ("from subprocess import run", "Import of 'subprocess'"),
        ("import json, socket", "Import of 'socket'"),
        ("eval('1')", "'eval'"),
        ("__import__('os')", "'__import__'"),
        ("x = ().__class__", "Dunder attribute"),
        ("getattr(1, 'real')", "'getattr'"),
        ("INPUT_DIR = '/'", "INPUT_DIR"),
        ("def (", "SyntaxError"),
        ("x = 1\n" * 5000, "longer than"),
    ],
)
def test_check_code_rejects(code, problem):
    assert any(problem in p for p in check_code(code))


def test_check_code_accepts_reference_program():
    assert check_code(GOOD_CODE) == []


@pytest.mark.parametrize(
    "key, expected, got, agree",
    [
        ("total", "740.60", "740.60", True),
        ("total", "740.60", 740.6, True),
        ("total", "740.60", "740.61", True),
        ("total", "740.60", "740.62", False),
        ("total", "740.60", "NaN", False),
        ("total", "740.60", None, False),
        ("implied_kl", "12.6", "12.60", True),
        ("implied_kl", "12.6", "12.7", False),
        ("outage_days", 9, 9, True),
        ("outage_days", 9, "9", False),
        ("outage_days", 9, True, False),
    ],
)
def test_compare(key, expected, got, agree):
    assert compare({key: expected}, {key: got})[key]["agree"] is agree


def test_attach_receipts_links_recomputed_findings(a6, a8, tariff, runner):
    checks = run_checks(a6, a8, tariff)
    analyst = run_analyst(a6, a8, ScriptedGateway(GOOD_CODE), runner, tariff=tariff)
    merged = attach_receipts(checks, analyst)
    ids = list(analyst["receipt_ids"].values())
    by_check = {f["check"]: f for f in merged["findings"]}
    assert by_check["arithmetic"]["receipt_ids"] == ids
    assert by_check["outage_consistency"]["receipt_ids"] == ids
    assert by_check["estimated_readings"]["receipt_ids"] == []


def test_attach_receipts_records_skip_on_failure(a6, a8, tariff, runner):
    checks = run_checks(a6, a8, tariff)
    analyst = run_analyst(a6, a8, ScriptedGateway("1/0", "1/0", "1/0"), runner, tariff=tariff)
    merged = attach_receipts(copy.deepcopy(checks), analyst)
    assert len(merged["findings"]) == 3
    assert all(f["receipt_ids"] == [] for f in merged["findings"])
    assert merged["skipped_checks"][-1]["check"] == "analyst_coder"
