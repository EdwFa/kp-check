"""Сложение рабочих дней только по загруженному календарю."""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path


CALENDAR_ENV = "KP_BUSINESS_CALENDAR"


def load_business_calendar(path: Path | str | None = None) -> dict[str, set[date]] | None:
    raw = path if path is not None else os.environ.get(CALENDAR_ENV)
    if not raw:
        return None
    payload = json.loads(Path(raw).read_text(encoding="utf-8"))
    return {
        "holidays": {_parse(item) for item in payload.get("holidays") or []},
        "extra_workdays": {_parse(item) for item in payload.get("extra_workdays") or []},
    }


def is_workday(day: date, calendar: dict[str, set[date]]) -> bool:
    """Суббота и воскресенье не рабочие, пока день не перенесён в extra_workdays."""
    if day in calendar["extra_workdays"]:
        return True
    if day in calendar["holidays"] or day.weekday() >= 5:
        return False
    return True


def add_business_days(start: date, count: int, calendar: dict[str, set[date]]) -> tuple[date, list[date]]:
    cursor = start
    counted: list[date] = []
    while len(counted) < count:
        cursor += timedelta(days=1)
        if is_workday(cursor, calendar):
            counted.append(cursor)
    return cursor, counted


def _parse(value: str) -> date:
    return date.fromisoformat(value)
