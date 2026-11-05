"""Deterministic Bill Lens checks (guide §8). The tariff engine is the source of truth.

Five checks, each skipped (with a reason) when the inputs it needs are unreadable:
  arithmetic          billed total vs tariff_v1 recomputation (flag > R0.05)
  estimated_readings  two or more consecutive estimates, or a large true-up
  meter_sanity        readings in order, non-decreasing, consumption = last - previous
  outage_consistency  billed use vs normal use when the outage log shows no supply
  line_items          duplicate lines and lines not in the tariff

Wording rule: findings state facts and implied figures only. They never claim a
legal entitlement or tell the customer what they are owed.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any

from .extractor import UNREADABLE
from .tariff import Tariff, calculate_bill, load_tariff

ARITHMETIC_THRESHOLD = Decimal("0.05")
METER_TOLERANCE_KL = Decimal("0.05")
MIN_CONSECUTIVE_ESTIMATES = 2
TRUE_UP_FACTOR = Decimal("1.5")
MIN_OUTAGE_DAYS = 3
OUTAGE_TOLERANCE = Decimal("0.10")
MIN_HISTORY_BILLS = 2

CENT = Decimal("0.01")
TENTH = Decimal("0.1")


def run_checks(bill: dict[str, Any], history: dict[str, Any] | None = None, tariff: Tariff | None = None) -> dict[str, Any]:
    tariff = tariff or load_tariff()
    report = _Report()
    calculation = _arithmetic(bill, tariff, report)
    normal_kl = _normal_consumption(bill, history, report)
    _estimated_readings(bill, normal_kl, report)
    _meter_sanity(bill, report)
    _outage_consistency(bill, history, normal_kl, report)
    _line_items(bill, tariff, report)
    return {
        "findings": report.findings,
        "skipped_checks": report.skipped,
        "checks_run": report.run,
        "recomputation": calculation.to_dict() if calculation else None,
    }


class _Report:
    def __init__(self) -> None:
        self.findings: list[dict[str, Any]] = []
        self.skipped: list[dict[str, str]] = []
        self.run: list[str] = []
        self._history_notes: list[str] = []

    def add(self, check: str, explanation: str, *, billed=None, recomputed=None, unit=None, data=None) -> None:
        difference = None
        if billed is not None and recomputed is not None:
            difference = billed - recomputed
        self.findings.append(
            {
                "id": f"F{len(self.findings) + 1}",
                "check": check,
                "billed": _fmt(billed, unit),
                "recomputed": _fmt(recomputed, unit),
                "difference": _fmt(difference, unit),
                "unit": unit,
                "explanation": explanation,
                "data": data or {},
                "receipt_ids": [],
            }
        )

    def skip(self, check: str, reason: str) -> None:
        self.skipped.append({"check": check, "reason": reason})

    def ran(self, check: str) -> None:
        if check not in self.run:
            self.run.append(check)


def _fmt(value: Decimal | None, unit: str | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(TENTH if unit == "kl" else CENT))


def _dec(value: Any) -> Decimal | None:
    if value is None or value == UNREADABLE:
        return None
    return Decimal(str(value))


def _date(value: Any) -> date | None:
    if not value or value == UNREADABLE:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _arithmetic(bill: dict[str, Any], tariff: Tariff, report: _Report):
    check = "arithmetic"
    consumption = _dec(bill.get("consumption_kl"))
    billed_total = _dec(bill.get("total_due"))
    if consumption is None or billed_total is None:
        report.skip(check, "Consumption or total due could not be read from the bill")
        return None
    report.ran(check)
    calc = calculate_bill(consumption, tariff)
    difference = billed_total - calc.total
    if abs(difference) <= ARITHMETIC_THRESHOLD:
        return calc

    expected = {_norm(line.description): line for line in (*calc.water_lines, *calc.fixed_lines)}
    differences = []
    for billed_line in (*bill.get("tariff_lines", []), *bill.get("fixed_charges", [])):
        description = billed_line.get("description", "")
        amount = _dec(billed_line.get("amount"))
        correct = expected.get(_norm(description))
        if correct is None or amount is None or abs(amount - correct.amount) <= ARITHMETIC_THRESHOLD:
            continue
        item = {"line": description, "billed": str(amount), "recomputed": str(correct.amount)}
        billed_rate = _dec(billed_line.get("rate_per_kl"))
        if billed_rate is not None and correct.rate_per_kl is not None and billed_rate != correct.rate_per_kl:
            item.update(billed_rate=str(billed_rate), tariff_rate=str(correct.rate_per_kl))
        differences.append(item)

    parts = [f"Billed total is R{billed_total:.2f}; {tariff.tariff_id} gives R{calc.total:.2f} for {consumption} kl."]
    for item in differences:
        if "tariff_rate" in item:
            parts.append(
                f"'{item['line']}' is charged at R{item['billed_rate']}/kl; the tariff rate is R{item['tariff_rate']}/kl "
                f"(R{item['billed']} billed vs R{item['recomputed']})."
            )
        else:
            parts.append(f"'{item['line']}' is R{item['billed']} on the bill vs R{item['recomputed']} recomputed.")
    report.add(
        check,
        " ".join(parts),
        billed=billed_total,
        recomputed=calc.total,
        unit="R",
        data={"consumption_kl": str(consumption), "line_differences": differences},
    )
    return calc


def _normal_consumption(bill: dict[str, Any], history: dict[str, Any] | None, report: _Report) -> Decimal | None:
    if not history:
        return None
    if history.get("account_number") != bill.get("account_number"):
        report._history_notes.append("History belongs to a different account number")
        return None
    values = [_dec(b.get("consumption_kl")) for b in history.get("previous_bills", [])]
    values = [v for v in values if v is not None]
    if len(values) < MIN_HISTORY_BILLS:
        report._history_notes.append(f"Fewer than {MIN_HISTORY_BILLS} previous bills with readable consumption")
        return None
    return sum(values) / len(values)


def _history_reason(report: _Report, default: str) -> str:
    return report._history_notes[0] if report._history_notes else default


def _sorted_readings(bill: dict[str, Any]) -> list[dict[str, Any]] | None:
    readings = bill.get("meter_readings", [])
    if any(_date(r.get("date")) is None for r in readings):
        return None
    return sorted(readings, key=lambda r: r["date"])


def _estimated_readings(bill: dict[str, Any], normal_kl: Decimal | None, report: _Report) -> None:
    check = "estimated_readings"
    readings = _sorted_readings(bill)
    if not readings or any(r.get("type") == UNREADABLE for r in readings):
        report.skip(check, "Meter reading dates or types could not be read from the bill")
        return
    report.ran(check)

    run: list[dict[str, Any]] = []
    longest: list[dict[str, Any]] = []
    for reading in readings:
        run = run + [reading] if reading["type"] == "estimated" else []
        if len(run) > len(longest):
            longest = run
    if len(longest) >= MIN_CONSECUTIVE_ESTIMATES:
        dates = [r["date"] for r in longest]
        report.add(
            check,
            f"{len(longest)} consecutive meter readings are estimated ({', '.join(dates)}), so the charge for this "
            "period is not based on an actual reading.",
            unit="kl",
            data={"consecutive_estimates": len(longest), "dates": dates},
        )

    consumption = _dec(bill.get("consumption_kl"))
    if (
        len(readings) >= 2
        and readings[-1]["type"] == "actual"
        and readings[-2]["type"] == "estimated"
        and consumption is not None
        and normal_kl
        and consumption > normal_kl * TRUE_UP_FACTOR
    ):
        report.add(
            check,
            f"An actual reading follows an estimate and this period's use ({consumption} kl) is more than "
            f"{TRUE_UP_FACTOR}x the normal {normal_kl.quantize(TENTH)} kl, which suggests a catch-up (true-up) charge.",
            billed=consumption,
            recomputed=normal_kl,
            unit="kl",
            data={"true_up": True},
        )


def _meter_sanity(bill: dict[str, Any], report: _Report) -> None:
    check = "meter_sanity"
    readings = _sorted_readings(bill)
    values = [_dec(r.get("reading_kl")) for r in readings] if readings else []
    if not readings or len(readings) < 2 or any(v is None for v in values):
        report.skip(check, "At least two readable, dated meter readings are needed")
        return
    report.ran(check)

    for previous, current, prev_value, value in zip(readings, readings[1:], values, values[1:]):
        if value < prev_value:
            report.add(
                check,
                f"The meter reading goes down from {prev_value} kl ({previous['date']}) to {value} kl ({current['date']}).",
                unit="kl",
                data={"from": previous["date"], "to": current["date"]},
            )

    consumption = _dec(bill.get("consumption_kl"))
    if consumption is None:
        return
    implied = values[-1] - values[-2]
    if abs(consumption - implied) > METER_TOLERANCE_KL:
        report.add(
            check,
            f"Billed consumption is {consumption} kl, but the last two readings ({values[-2]} and {values[-1]} kl) "
            f"differ by {implied} kl.",
            billed=consumption,
            recomputed=implied,
            unit="kl",
        )


def _outage_consistency(bill: dict[str, Any], history: dict[str, Any] | None, normal_kl: Decimal | None, report: _Report) -> None:
    check = "outage_consistency"
    if not history or not history.get("outage_log"):
        report.skip(check, "No outage log was provided")
        return
    if normal_kl is None:
        report.skip(check, _history_reason(report, "No previous bills to establish normal use"))
        return
    start = _date(bill.get("billing_period", {}).get("start"))
    end = _date(bill.get("billing_period", {}).get("end"))
    consumption = _dec(bill.get("consumption_kl"))
    if start is None or end is None or consumption is None:
        report.skip(check, "Billing period or consumption could not be read from the bill")
        return
    report.ran(check)

    outage_days, days, supplied, implied = _outage_figures(start, end, history["outage_log"], normal_kl)
    if len(outage_days) < MIN_OUTAGE_DAYS:
        return
    if consumption <= implied * (1 + OUTAGE_TOLERANCE):
        return
    report.add(
        check,
        f"Billed use ({consumption} kl) is close to the normal average of {normal_kl.quantize(TENTH)} kl from previous "
        f"bills, although {len(outage_days)} of {days} days in this period had no supply according to the outage log. "
        f"Normal daily use over the {supplied} supplied days implies about {implied.quantize(TENTH)} kl.",
        billed=consumption,
        recomputed=implied,
        unit="kl",
        data={
            "period_days": days,
            "outage_days": len(outage_days),
            "outage_dates": outage_days,
            "normal_kl": str(normal_kl.quantize(TENTH)),
        },
    )


def _outage_figures(start: date, end: date, outage_log: list[dict[str, Any]], normal_kl: Decimal):
    outage_days = sorted(
        {
            entry["date"]
            for entry in outage_log
            if entry.get("supply") == "none" and (d := _date(entry.get("date"))) and start <= d <= end
        }
    )
    days = (end - start).days + 1
    supplied = days - len(outage_days)
    return outage_days, days, supplied, normal_kl * supplied / days


def reference_figures(bill: dict[str, Any], history: dict[str, Any] | None = None, tariff: Tariff | None = None) -> dict[str, Any]:
    """Engine values the analyst coder must reproduce. None means the engine could not compute it."""
    tariff = tariff or load_tariff()
    figures: dict[str, Any] = dict.fromkeys(
        ("subtotal", "vat", "total", "normal_kl", "period_days", "outage_days", "supplied_days", "implied_kl")
    )
    consumption = _dec(bill.get("consumption_kl"))
    if consumption is not None:
        calc = calculate_bill(consumption, tariff)
        figures.update(subtotal=str(calc.subtotal), vat=str(calc.vat), total=str(calc.total))
    normal_kl = _normal_consumption(bill, history, _Report())
    if normal_kl is None:
        return figures
    figures["normal_kl"] = str(normal_kl.quantize(TENTH))
    start = _date(bill.get("billing_period", {}).get("start"))
    end = _date(bill.get("billing_period", {}).get("end"))
    if start and end and history and history.get("outage_log"):
        outage_days, days, supplied, implied = _outage_figures(start, end, history["outage_log"], normal_kl)
        figures.update(
            period_days=days, outage_days=len(outage_days), supplied_days=supplied, implied_kl=str(implied.quantize(TENTH))
        )
    return figures


def _line_items(bill: dict[str, Any], tariff: Tariff, report: _Report) -> None:
    check = "line_items"
    lines = [*bill.get("tariff_lines", []), *bill.get("fixed_charges", [])]
    if not lines:
        report.skip(check, "No charge lines could be read from the bill")
        return
    report.ran(check)

    known = {_norm(c.description) for c in tariff.fixed_charges}
    probe = calculate_bill(Decimal("1000000"), tariff)
    known |= {_norm(line.description) for line in probe.water_lines}

    counts = Counter(_norm(line.get("description", "")) for line in lines)
    reported: set[str] = set()
    for line in lines:
        description = line.get("description", "")
        key = _norm(description)
        amount = _dec(line.get("amount"))
        if description == UNREADABLE or key in reported:
            continue
        if counts[key] > 1:
            reported.add(key)
            report.add(
                check,
                f"'{description}' appears {counts[key]} times on the bill.",
                billed=amount,
                unit="R",
                data={"line": description, "duplicate_count": counts[key]},
            )
        elif key not in known:
            reported.add(key)
            report.add(
                check,
                f"'{description}' is not a charge in {tariff.tariff_id}.",
                billed=amount,
                unit="R",
                data={"line": description, "unknown": True},
            )
