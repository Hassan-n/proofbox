import copy
import json
import sys
from pathlib import Path

import pytest

from lenses.bill.checks import run_checks
from lenses.bill.tariff import load_tariff

ROOT = Path(__file__).resolve().parents[2]
STUBS = ROOT / "fixtures" / "stubs"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_fixtures  # noqa: E402

LEGAL_WORDS = ("entitled", "entitlement", "owed", "refund", "must pay", "legally", "by law", "rights")


@pytest.fixture(scope="module")
def tariff():
    return load_tariff()


@pytest.fixture(scope="module")
def a5():
    return json.loads((STUBS / "bill_extractor_A5.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a6():
    return json.loads((STUBS / "bill_extractor_A6.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixtures")
    generate_fixtures.generate(out, stubs_dir=out / "stubs")
    return out


@pytest.fixture(scope="module")
def a8(generated):
    return json.loads((generated / "A8_history.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest(generated):
    return json.loads((generated / "manifest.json").read_text(encoding="utf-8"))


def by_check(result, check):
    return [f for f in result["findings"] if f["check"] == check]


def test_a5_clean_bill_has_no_findings(a5, a8, tariff):
    result = run_checks(a5, a8, tariff)
    assert result["findings"] == []
    assert "arithmetic" in result["checks_run"]
    assert result["recomputation"]["total"] == "740.60"


def test_a5_history_for_other_account_skips_outage(a5, a8, tariff):
    result = run_checks(a5, a8, tariff)
    skipped = {s["check"]: s["reason"] for s in result["skipped_checks"]}
    assert "different account" in skipped["outage_consistency"]


def test_a6_matches_manifest(a6, a8, tariff, manifest):
    result = run_checks(a6, a8, tariff)
    expected = manifest["files"]["A6"]["expected_findings"]
    assert sorted(f["check"] for f in result["findings"]) == sorted(e["check"] for e in expected)

    exp = {e["check"]: e for e in expected}
    arithmetic = by_check(result, "arithmetic")[0]
    assert arithmetic["billed"] == exp["arithmetic"]["billed"]
    assert arithmetic["recomputed"] == exp["arithmetic"]["recomputed"]
    assert arithmetic["difference"] == exp["arithmetic"]["difference"]
    [line] = arithmetic["data"]["line_differences"]
    assert line["line"] == exp["arithmetic"]["line"]
    assert line["billed"] == exp["arithmetic"]["billed_line"]
    assert line["recomputed"] == exp["arithmetic"]["recomputed_line"]
    assert line["billed_rate"] == "38.00" and line["tariff_rate"] == "25.00"

    estimates = by_check(result, "estimated_readings")[0]
    assert estimates["data"]["consecutive_estimates"] == exp["estimated_readings"]["consecutive_estimates"]
    assert estimates["data"]["dates"] == exp["estimated_readings"]["dates"]

    outage = by_check(result, "outage_consistency")[0]
    assert outage["data"]["period_days"] == exp["outage_consistency"]["period_days"]
    assert outage["data"]["outage_days"] == exp["outage_consistency"]["outage_days"]
    assert outage["billed"] == exp["outage_consistency"]["billed_kl"]
    assert outage["data"]["normal_kl"] == exp["outage_consistency"]["normal_kl"]
    assert outage["recomputed"] == exp["outage_consistency"]["implied_kl_for_supplied_days"]


def test_a6_without_history_skips_outage_only(a6, tariff):
    result = run_checks(a6, None, tariff)
    assert {f["check"] for f in result["findings"]} == {"arithmetic", "estimated_readings"}
    assert [s["check"] for s in result["skipped_checks"]] == ["outage_consistency"]


def test_findings_shape_and_ids(a6, a8, tariff):
    result = run_checks(a6, a8, tariff)
    for i, finding in enumerate(result["findings"], start=1):
        assert finding["id"] == f"F{i}"
        assert set(finding) >= {"id", "check", "billed", "recomputed", "difference", "explanation", "receipt_ids"}
        assert finding["receipt_ids"] == []
    json.dumps(result)


def test_explanations_avoid_legal_claims(a6, a8, tariff):
    for finding in run_checks(a6, a8, tariff)["findings"]:
        text = finding["explanation"].lower()
        assert not any(word in text for word in LEGAL_WORDS), finding["explanation"]


def test_small_rounding_difference_not_flagged(a5, tariff):
    bill = copy.deepcopy(a5)
    bill["total_due"] = "740.64"
    assert by_check(run_checks(bill, None, tariff), "arithmetic") == []
    bill["total_due"] = "740.66"
    assert len(by_check(run_checks(bill, None, tariff), "arithmetic")) == 1


def test_unreadable_total_skips_arithmetic(a6, tariff):
    bill = copy.deepcopy(a6)
    bill["total_due"] = "unreadable"
    result = run_checks(bill, None, tariff)
    assert by_check(result, "arithmetic") == []
    assert "arithmetic" in [s["check"] for s in result["skipped_checks"]]
    assert result["recomputation"] is None


def test_unreadable_reading_type_skips_estimates(a6, tariff):
    bill = copy.deepcopy(a6)
    bill["meter_readings"][1]["type"] = "unreadable"
    result = run_checks(bill, None, tariff)
    assert "estimated_readings" in [s["check"] for s in result["skipped_checks"]]


def test_meter_going_backwards(a5, tariff):
    bill = copy.deepcopy(a5)
    bill["meter_readings"][1]["reading_kl"] = "1000.0"
    findings = by_check(run_checks(bill, None, tariff), "meter_sanity")
    assert any("goes down" in f["explanation"] for f in findings)


def test_consumption_disagrees_with_readings(a5, tariff):
    bill = copy.deepcopy(a5)
    last = bill["meter_readings"][-1]
    last["reading_kl"] = str(float(last["reading_kl"]) + 5)
    [finding] = by_check(run_checks(bill, None, tariff), "meter_sanity")
    assert finding["billed"] == "18.0" and finding["recomputed"] == "23.0"


def test_true_up_detected(a5, tariff):
    bill = copy.deepcopy(a5)
    readings = bill["meter_readings"]
    readings[-2]["type"] = "estimated"
    readings[-1]["type"] = "actual"
    bill["consumption_kl"] = "40.0"
    readings[-1]["reading_kl"] = str(float(readings[-2]["reading_kl"]) + 40)
    history = {"account_number": bill["account_number"], "previous_bills": [{"consumption_kl": "18.0"}] * 3}
    findings = by_check(run_checks(bill, history, tariff), "estimated_readings")
    assert any(f["data"].get("true_up") for f in findings)


def test_duplicate_and_unknown_lines(a5, tariff):
    bill = copy.deepcopy(a5)
    bill["fixed_charges"].append({"description": "Refuse removal", "amount": "95.00"})
    bill["fixed_charges"].append({"description": "Sewer levy", "amount": "50.00"})
    findings = by_check(run_checks(bill, None, tariff), "line_items")
    assert {f["data"]["line"] for f in findings} == {"Refuse removal", "Sewer levy"}
    assert any(f["data"].get("duplicate_count") == 2 for f in findings)
    assert any(f["data"].get("unknown") for f in findings)


def test_short_outage_not_flagged(a6, a8, tariff):
    history = copy.deepcopy(a8)
    history["outage_log"] = history["outage_log"][:2]
    assert by_check(run_checks(a6, history, tariff), "outage_consistency") == []
