from __future__ import annotations

import re
from datetime import date

MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,  # мая / май
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}

NUMERIC_DATE = re.compile(
    r"(?<!\d)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})(?!\d)"
)
ISO_DATE = re.compile(r"(?<!\d)(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?!\d)")
FILENAME_OT_DATE = re.compile(
    r"от[-_ ]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    re.IGNORECASE,
)
MIN_YEAR = 1990
MAX_YEAR = 2100
RU_DATE = re.compile(
    r"[«\"']?(\d{1,2})[»\"']?\s+([А-Яа-яЁё]+)\s+(\d{4})\s*г?\.?",
    re.IGNORECASE,
)


def _year(raw: str) -> int:
    year = int(raw)
    if year < 100:
        year += 2000 if year < 70 else 1900
    return year


def _plausible(value: date | None) -> date | None:
    if value is None or not (MIN_YEAR <= value.year <= MAX_YEAR):
        return None
    return value


def parse_numeric_date(day: str, month: str, year: str) -> date | None:
    try:
        return _plausible(date(int(_year(year)), int(month), int(day)))
    except ValueError:
        return None


def parse_iso_date(year: str, month: str, day: str) -> date | None:
    try:
        return _plausible(date(int(year), int(month), int(day)))
    except ValueError:
        return None


def month_from_name(name: str) -> int | None:
    lowered = name.lower()
    for prefix, number in MONTHS.items():
        if lowered.startswith(prefix):
            if prefix == "ма" and not lowered.startswith(("ма", "май")):
                continue
            if prefix == "ма" and not (lowered.startswith("мая") or lowered.startswith("май")):
                continue
            return number
    return None


def parse_date_string(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    m = NUMERIC_DATE.search(text)
    if m:
        parsed = parse_numeric_date(m.group(1), m.group(2), m.group(3))
        if parsed:
            return parsed
    m = ISO_DATE.search(text)
    if m:
        parsed = parse_iso_date(m.group(1), m.group(2), m.group(3))
        if parsed:
            return parsed
    m = RU_DATE.search(text)
    if m:
        month = month_from_name(m.group(2))
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    return None


def find_dates(text: str) -> list[tuple[date, str, int]]:
    """Return (date, matched_raw, start_index) without inventing values."""
    found: list[tuple[date, str, int]] = []
    seen: set[tuple[int, str]] = set()
    for pattern, kind in ((NUMERIC_DATE, "num"), (ISO_DATE, "iso"), (RU_DATE, "ru")):
        for m in pattern.finditer(text or ""):
            parsed: date | None
            if kind == "num":
                parsed = parse_numeric_date(m.group(1), m.group(2), m.group(3))
            elif kind == "iso":
                parsed = parse_iso_date(m.group(1), m.group(2), m.group(3))
            else:
                month = month_from_name(m.group(2))
                parsed = None
                if month:
                    try:
                        parsed = date(int(m.group(3)), month, int(m.group(1)))
                    except ValueError:
                        parsed = None
            if not parsed:
                continue
            key = (m.start(), m.group(0))
            if key in seen:
                continue
            seen.add(key)
            found.append((parsed, m.group(0).strip(), m.start()))
    found.sort(key=lambda item: item[2])
    return found


def date_from_filename(name: str) -> tuple[date | None, str | None]:
    ot = FILENAME_OT_DATE.search(name or "")
    if ot:
        parsed = parse_date_string(ot.group(1))
        if parsed:
            return parsed, ot.group(1)
    dotted = [item for item in find_dates(name) if "." in item[1]]
    if dotted:
        value, raw, _ = dotted[-1]
        return value, raw
    matches = find_dates(name)
    if not matches:
        return None, None
    value, raw, _ = matches[-1]
    return value, raw


def format_date(value: date | None, raw: str | None = None, empty: str = "не прочитана") -> str:
    if value:
        return value.strftime("%d.%m.%Y")
    if raw:
        return raw
    return empty
