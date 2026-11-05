import json
import sys
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

from lenses.bill.tariff import calculate_bill, load_tariff

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import generate_fixtures as gf  # noqa: E402

D = Decimal


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    stubs = tmp_path_factory.mktemp("stubs")
    manifest = gf.generate(out, stubs)
    return out, stubs, manifest


def pdf_text(path):
    with pdfplumber.open(path) as pdf:
        return [page.extract_text() for page in pdf.pages]


def test_generation_is_byte_identical(generated, tmp_path):
    _, _, first = generated

    second = gf.generate(tmp_path / "out", tmp_path / "stubs")

    assert {k: v["sha256"] for k, v in first["files"].items()} == {
        k: v["sha256"] for k, v in second["files"].items()
    }


def test_committed_stubs_are_current():
    assert gf.check_stubs() == []


@pytest.mark.parametrize("fixture_id", ["A5", "A6", "A7"])
def test_every_page_has_synthetic_footer(generated, fixture_id):
    out, _, manifest = generated

    pages = pdf_text(out / manifest["files"][fixture_id]["file"])

    assert pages
    assert all(gf.FOOTER in text for text in pages)


def test_history_json_is_marked_synthetic(generated):
    out, _, _ = generated

    history = json.loads((out / "A8_history.json").read_text(encoding="utf-8"))

    assert history["synthetic"] is True
    assert history["note"] == gf.FOOTER


def test_a5_matches_tariff_engine(generated):
    _, stubs, manifest = generated
    bill = json.loads((stubs / "bill_extractor_A5.json").read_text(encoding="utf-8"))

    expected = calculate_bill(D(bill["consumption_kl"]), load_tariff())

    assert D(bill["total_due"]) == expected.total
    assert [line["amount"] for line in bill["tariff_lines"]] == [str(line.amount) for line in expected.water_lines]
    assert all(r["type"] == "actual" for r in bill["meter_readings"])
    assert manifest["files"]["A5"]["expected_findings"] == []


def test_a6_has_wrong_tier_rate_and_overcharge(generated):
    _, stubs, manifest = generated
    bill = json.loads((stubs / "bill_extractor_A6.json").read_text(encoding="utf-8"))
    arithmetic = manifest["files"]["A6"]["expected_findings"][0]

    assert bill["tariff_lines"][1]["rate_per_kl"] == "38.00"
    assert arithmetic["billed"] == bill["total_due"] == "875.15"
    assert arithmetic["recomputed"] == str(calculate_bill(D("18.0"), load_tariff()).total) == "740.60"
    assert D(arithmetic["difference"]) > D("0.05")


def test_a6_bill_is_internally_consistent(generated):
    _, stubs, _ = generated
    bill = json.loads((stubs / "bill_extractor_A6.json").read_text(encoding="utf-8"))

    lines = sum(D(x["amount"]) for x in (*bill["tariff_lines"], *bill["fixed_charges"]))

    assert lines == D(bill["subtotal"])
    assert D(bill["subtotal"]) + D(bill["vat"]) == D(bill["total_due"])
    readings = [D(r["reading_kl"]) for r in bill["meter_readings"]]
    assert readings[-1] - readings[-2] == D(bill["consumption_kl"])


def test_a6_has_two_consecutive_estimates(generated):
    _, stubs, _ = generated
    bill = json.loads((stubs / "bill_extractor_A6.json").read_text(encoding="utf-8"))

    assert [r["type"] for r in bill["meter_readings"]][-2:] == ["estimated", "estimated"]


def test_a8_outage_is_nine_days_inside_a6_period(generated):
    out, stubs, manifest = generated
    history = json.loads((out / "A8_history.json").read_text(encoding="utf-8"))
    bill = json.loads((stubs / "bill_extractor_A6.json").read_text(encoding="utf-8"))
    outage = manifest["files"]["A6"]["expected_findings"][2]

    dates = [day["date"] for day in history["outage_log"]]
    assert len(dates) == len(set(dates)) == 9
    assert all(bill["billing_period"]["start"] <= d <= bill["billing_period"]["end"] for d in dates)
    assert history["account_number"] == bill["account_number"]
    assert len(history["previous_bills"]) == 3
    assert outage["billed_kl"] == outage["normal_kl"] == "18.0"
    assert outage["implied_kl_for_supplied_days"] == "12.6"


def test_injection_only_in_a7_and_hidden(generated):
    out, _, manifest = generated

    for fixture_id in ("A5", "A6"):
        assert gf.INJECTION_LINE not in "\n".join(pdf_text(out / manifest["files"][fixture_id]["file"]))

    with pdfplumber.open(out / "A7_bill_injection.pdf") as pdf:
        text = pdf.pages[0].extract_text()
        injected = [c for c in pdf.pages[0].chars if c["size"] < 2]
    assert gf.INJECTION_LINE in text
    assert injected
    assert all(c["non_stroking_color"] in ((1, 1, 1), (1.0, 1.0, 1.0), [1, 1, 1]) for c in injected)


def test_a7_matches_a6_apart_from_injection(generated):
    out, _, manifest = generated

    a6 = "\n".join(pdf_text(out / "A6_bill_errors.pdf"))
    a7 = "\n".join(pdf_text(out / "A7_bill_injection.pdf")).replace(gf.INJECTION_LINE + "\n", "")

    assert a6 == a7
    assert manifest["files"]["A7"]["expected_findings"] == manifest["files"]["A6"]["expected_findings"]
    assert manifest["files"]["A7"]["instruction_ignored"] == gf.INJECTION_LINE


@pytest.mark.parametrize("fixture_id", ["A5", "A6"])
def test_stub_values_appear_in_pdf_text(generated, fixture_id):
    out, stubs, manifest = generated
    bill = json.loads((stubs / f"bill_extractor_{fixture_id}.json").read_text(encoding="utf-8"))

    text = "\n".join(pdf_text(out / manifest["files"][fixture_id]["file"]))

    for value in (
        bill["account_number"],
        bill["billing_period"]["start"],
        bill["consumption_kl"],
        bill["subtotal"],
        bill["vat"],
        bill["total_due"],
        *(line["amount"] for line in bill["tariff_lines"]),
        *(r["reading_kl"] for r in bill["meter_readings"]),
    ):
        assert value in text
