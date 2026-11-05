# Stub analyst_coder output (MODEL_GATEWAY_MODE=stub). Runs with INPUT_DIR prepended by the runner.
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

def load(name):
    try:
        with open(f"{INPUT_DIR}/{name}", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None

def num(v):
    return None if v in (None, "unreadable") else Decimal(v)

bill, tariff, history = load("bill.json"), load("tariff.json"), load("history.json")
cent, tenth = Decimal("0.01"), Decimal("0.1")
out = dict.fromkeys(["subtotal", "vat", "total", "normal_kl", "period_days", "outage_days", "supplied_days", "implied_kl"])

use = num(bill.get("consumption_kl"))
if use is not None:
    lines = []
    for tier in tariff["water_tiers"]:
        low = Decimal(tier["from_kl"])
        high = use if tier["to_kl"] is None else min(use, Decimal(tier["to_kl"]))
        if high > low:
            lines.append(((high - low) * Decimal(tier["rate_per_kl"])).quantize(cent, ROUND_HALF_UP))
    lines += [Decimal(c["amount"]).quantize(cent, ROUND_HALF_UP) for c in tariff["fixed_charges"]]
    subtotal = sum(lines, Decimal("0"))
    vat = (subtotal * Decimal(tariff["vat_rate"])).quantize(cent, ROUND_HALF_UP)
    out.update(subtotal=str(subtotal), vat=str(vat), total=str(subtotal + vat))

if history and history.get("account_number") == bill.get("account_number"):
    prev = [num(b.get("consumption_kl")) for b in history.get("previous_bills", [])]
    prev = [p for p in prev if p is not None]
    if len(prev) >= 2:
        normal = sum(prev) / len(prev)
        out["normal_kl"] = str(normal.quantize(tenth, ROUND_HALF_UP))
        period = bill.get("billing_period", {})
        if "unreadable" not in (period.get("start"), period.get("end")) and history.get("outage_log"):
            start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
            days = (end - start).days + 1
            off = {e["date"] for e in history["outage_log"] if e.get("supply") == "none" and start <= date.fromisoformat(e["date"]) <= end}
            supplied = days - len(off)
            out.update(period_days=days, outage_days=len(off), supplied_days=supplied,
                       implied_kl=str((normal * supplied / days).quantize(tenth, ROUND_HALF_UP)))

print(json.dumps(out))
