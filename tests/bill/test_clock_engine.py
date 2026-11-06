from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from clock_engine import (
    BusinessCalendar,
    add_business_days,
    compute_state,
    due_date,
    load_calendar,
    reminder_dates,
)

API_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
CALENDAR = load_calendar(API_DIR / "rules" / "calendar.yaml")


@pytest.mark.parametrize(
    ("sent", "offset", "expected"),
    [
        (date(2026, 11, 19), 10, date(2026, 12, 3)),
        (date(2026, 12, 4), 10, date(2026, 12, 21)),
        (date(2026, 12, 5), 10, date(2026, 12, 21)),
        (date(2026, 12, 16), 1, date(2026, 12, 17)),
        (date(2026, 12, 24), 1, date(2026, 12, 28)),
        (date(2026, 11, 19), 0, date(2026, 11, 19)),
    ],
)
def test_business_day_due_dates(sent, offset, expected):
    assert add_business_days(sent, offset, CALENDAR) == expected


def test_business_day_calculator_uses_supplied_calendar():
    extra_holiday = BusinessCalendar(holidays=frozenset({date(2026, 11, 20)}))
    assert add_business_days(date(2026, 11, 19), 1, extra_holiday) == date(2026, 11, 23)


def test_non_business_sent_date_counts_from_next_business_day():
    assert due_date({"type": "business_days", "days": 10}, date(2026, 12, 5), CALENDAR) == date(2026, 12, 21)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (date(2026, 12, 2), "due_soon"),
        (date(2026, 11, 25), "upcoming"),
        (date(2026, 12, 3), "due_soon"),
        (date(2026, 12, 4), "overdue"),
    ],
)
def test_clock_state_boundaries(now, expected):
    assert compute_state({"due_date": date(2026, 12, 3)}, now, CALENDAR) == expected


def test_confirmed_reply_meets_clock_even_when_late():
    clock = {"due_date": date(2026, 12, 3), "confirmed_at": date(2026, 12, 4)}
    assert compute_state(clock, date(2026, 12, 10), CALENDAR) == "met"


def test_fixed_due_date_and_reminders():
    assert due_date(
        {"type": "fixed", "due_date": "2026-12-16"}, date(2026, 12, 1), CALENDAR
    ) == date(2026, 12, 16)
    assert reminder_dates(date(2026, 12, 16)) == (
        date(2026, 12, 9),
        date(2026, 12, 13),
        date(2026, 12, 15),
    )


def test_clock_uses_south_african_local_date():
    instant = datetime(2026, 12, 3, 22, 30, tzinfo=timezone.utc)
    assert compute_state({"due_date": date(2026, 12, 4)}, instant, CALENDAR) == "due_soon"


def test_negative_business_day_offset_is_rejected():
    with pytest.raises(ValueError, match="cannot be negative"):
        add_business_days(date(2026, 12, 1), -1, CALENDAR)
