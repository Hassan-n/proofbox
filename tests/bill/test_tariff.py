import copy
import json
from decimal import Decimal

import pytest

from lenses.bill.tariff import TARIFF_PATH_ENV, Tariff, calculate_bill, default_tariff_path, load_tariff

D = Decimal


@pytest.fixture(scope="module")
def tariff():
    return load_tariff()


@pytest.fixture
def tariff_data():
    with default_tariff_path().open(encoding="utf-8") as tariff_file:
        return json.load(tariff_file)


@pytest.mark.parametrize(
    ("consumption", "water_total", "subtotal", "vat", "total"),
    [
        ("0", "0", "215.00", "32.25", "247.25"),
        ("1", "15.00", "230.00", "34.50", "264.50"),
        ("6", "90.00", "305.00", "45.75", "350.75"),
        ("7", "115.00", "330.00", "49.50", "379.50"),
        ("15", "315.00", "530.00", "79.50", "609.50"),
        ("16", "353.00", "568.00", "85.20", "653.20"),
        ("20", "505.00", "720.00", "108.00", "828.00"),
        ("12.5", "252.50", "467.50", "70.13", "537.63"),
        ("1000", "37745.00", "37960.00", "5694.00", "43654.00"),
    ],
)
def test_bill_totals(tariff, consumption, water_total, subtotal, vat, total):
    bill = calculate_bill(consumption, tariff)

    assert bill.water_total == D(water_total)
    assert bill.subtotal == D(subtotal)
    assert bill.vat == D(vat)
    assert bill.total == D(total)


def test_default_tariff_matches_guide(tariff):
    assert [(t.from_kl, t.to_kl, t.rate_per_kl) for t in tariff.water_tiers] == [
        (D("0"), D("6"), D("15.00")),
        (D("6"), D("15"), D("25.00")),
        (D("15"), None, D("38.00")),
    ]
    assert {c.code: c.amount for c in tariff.fixed_charges} == {
        "water_service": D("120.00"),
        "refuse": D("95.00"),
    }
    assert tariff.vat_rate == D("0.15")


def test_zero_consumption_has_only_fixed_charges(tariff):
    bill = calculate_bill(0, tariff)

    assert bill.water_lines == ()
    assert [line.code for line in bill.fixed_lines] == ["water_service", "refuse"]


def test_tier_quantities_split_exactly_at_second_boundary(tariff):
    bill = calculate_bill("15", tariff)

    assert [(line.code, line.quantity_kl, line.amount) for line in bill.water_lines] == [
        ("water_tier_1", D("6"), D("90.00")),
        ("water_tier_2", D("9"), D("225.00")),
    ]


def test_just_above_first_boundary_rounds_line_half_up(tariff):
    bill = calculate_bill("6.001", tariff)

    assert bill.water_lines[-1].amount == D("0.03")
    assert bill.subtotal == D("305.03")
    assert bill.total == D("350.78")


def test_each_charge_line_is_rounded_to_cents(tariff):
    bill = calculate_bill("0.333", tariff)

    assert bill.water_lines[0].amount == D("5.00")


def test_accepts_integer_and_decimal_inputs(tariff):
    assert calculate_bill(7, tariff).total == calculate_bill(D("7"), tariff).total


@pytest.mark.parametrize("value", [-1, "-0.001"])
def test_rejects_negative_consumption(tariff, value):
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate_bill(value, tariff)


@pytest.mark.parametrize("value", [1.5, True])
def test_rejects_float_and_bool_consumption(tariff, value):
    with pytest.raises(TypeError):
        calculate_bill(value, tariff)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "abc"])
def test_rejects_non_finite_or_non_numeric_consumption(tariff, value):
    with pytest.raises(ValueError):
        calculate_bill(value, tariff)


def test_serializes_money_as_exact_strings(tariff):
    result = calculate_bill("15", tariff).to_dict()

    assert result["total"] == "609.50"
    assert result["water_lines"][1] == {
        "code": "water_tier_2",
        "description": "Water 6-15 kl",
        "quantity_kl": "9",
        "rate_per_kl": "25.00",
        "amount": "225.00",
    }


def test_vat_rate_is_configurable(tariff_data):
    tariff_data["vat_rate"] = "0"

    bill = calculate_bill("7", Tariff.from_dict(tariff_data))

    assert bill.vat == D("0.00")
    assert bill.total == D("330.00")


def test_tariff_path_can_be_configured(monkeypatch, tmp_path, tariff_data):
    tariff_data["tariff_id"] = "custom"
    tariff_file = tmp_path / "custom.json"
    tariff_file.write_text(json.dumps(tariff_data), encoding="utf-8")
    monkeypatch.setenv(TARIFF_PATH_ENV, str(tariff_file))

    assert load_tariff().tariff_id == "custom"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["water_tiers"][1].update(from_kl="7"), "contiguous"),
        (lambda d: d["water_tiers"][2].update(to_kl="30"), "open-ended"),
        (lambda d: d["water_tiers"][0].update(rate_per_kl="-1"), "negative"),
        (lambda d: d.update(vat_rate="-0.15"), "VAT"),
        (lambda d: d["rounding"].update(mode="ROUND_DOWN"), "rounding mode"),
        (lambda d: d.pop("vat_rate"), "vat_rate"),
    ],
)
def test_rejects_invalid_tariffs(tariff_data, change, message):
    invalid = copy.deepcopy(tariff_data)
    change(invalid)

    with pytest.raises(ValueError, match=message):
        Tariff.from_dict(invalid)
