"""Deterministic calendar and clock calculations for case timelines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

LOCAL_TIMEZONE = ZoneInfo("Africa/Johannesburg")


@dataclass(frozen=True)
class BusinessCalendar:
    holidays: frozenset[date]
    weekend_days: frozenset[int] = frozenset({5, 6})

    def is_business_day(self, day: date) -> bool:
        return day.weekday() not in self.weekend_days and day not in self.holidays


def load_calendar(path: str | Path) -> BusinessCalendar:
    with Path(path).open(encoding="utf-8") as calendar_file:
        data = yaml.safe_load(calendar_file) or {}
    return BusinessCalendar(
        holidays=frozenset(
            value if isinstance(value, date) else date.fromisoformat(value)
            for value in data.get("holidays", [])
        ),
        weekend_days=frozenset(data.get("weekend_days", [5, 6])),
    )


def _local_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=LOCAL_TIMEZONE)
        return value.astimezone(LOCAL_TIMEZONE).date()
    return value


def add_business_days(start: date | datetime, days: int, calendar: BusinessCalendar) -> date:
    if days < 0:
        raise ValueError("Business-day offsets cannot be negative")
    current = _local_date(start)
    if days == 0:
        return current

    added = 0
    while added < days:
        current += timedelta(days=1)
        if calendar.is_business_day(current):
            added += 1
    return current


def due_date(clock_rule: dict, sent_at: date | datetime, calendar: BusinessCalendar) -> date:
    rule_type = clock_rule.get("type", "business_days")
    if rule_type == "fixed":
        value = clock_rule.get("due_date", clock_rule.get("date"))
        if not value:
            raise ValueError("A fixed clock rule requires a due_date")
        return date.fromisoformat(value) if isinstance(value, str) else value
    if rule_type != "business_days":
        raise ValueError(f"Unsupported clock rule type: {rule_type}")
    offset = clock_rule.get("days", clock_rule.get("business_days"))
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ValueError("A business-day clock rule requires an integer days value")
    return add_business_days(sent_at, offset, calendar)


def compute_state(clock: dict, now: date | datetime, calendar: BusinessCalendar) -> str:
    if clock.get("met_at") or clock.get("confirmed_at") or clock.get("state") == "met":
        return "met"

    raw_due_date = clock.get("due_date", clock.get("due_at"))
    if raw_due_date is None:
        raise ValueError("A clock requires a due_date")
    due = date.fromisoformat(raw_due_date) if isinstance(raw_due_date, str) else _local_date(raw_due_date)
    current = _local_date(now)

    if current > due:
        return "overdue"
    if (due - current).days <= 7:
        return "due_soon"
    return "upcoming"


def reminder_dates(due: date, offsets: tuple[int, ...] = (7, 3, 1)) -> tuple[date, ...]:
    if any(offset < 0 for offset in offsets):
        raise ValueError("Reminder offsets cannot be negative")
    return tuple(due - timedelta(days=offset) for offset in offsets)
