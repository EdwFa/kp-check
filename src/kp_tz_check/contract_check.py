"""Сравнение спецификации КП с параметрами ТЗ. Интернет не используется."""

from __future__ import annotations

import re


MATCH = "совпадение"
CRITICAL = "критическое"
MAJOR = "значительное"
MINOR = "незначительное"
NO_SPEC = "поиск характеристик не выполнялся"
INSUFFICIENT = "недостаточно данных"


def check_specification(requirements: list[dict] | None, offer: list[dict] | None) -> dict:
    if offer is None:
        return _report(NO_SPEC, None, None, [])
    rows_in = list(requirements or [])
    if not rows_in:
        return _report(INSUFFICIENT, None, None, [])
    rows = [_compare(item, _find(offer, item.get("name") or "")) for item in rows_in]
    required = [row for row in rows if row["required"]]
    if not required:
        return _report(INSUFFICIENT, None, _confidence(rows), rows)
    matched = sum(1 for row in required if row["class"] == MATCH)
    share = matched / len(required)
    if any(row["class"] == CRITICAL for row in rows):
        status = CRITICAL
    elif any(row["class"] == MAJOR for row in rows):
        status = MAJOR
    elif any(row["class"] == MINOR for row in rows):
        status = MINOR
    else:
        status = MATCH
    return _report(status, share, _confidence(rows), rows)


def _compare(requirement: dict, found: dict | None) -> dict:
    required = bool(requirement.get("required", True))
    name = str(requirement.get("name") or "")
    if found is None:
        return _row(
            name,
            CRITICAL if required else MINOR,
            "низкая",
            required,
            "Параметр отсутствует в спецификации КП." if required else "Необязательный параметр не найден.",
        )
    same_unit = _fold(requirement.get("unit")) == _fold(found.get("unit"))
    left = _number(requirement.get("value"))
    right = _number(found.get("value"))
    threshold = float(requirement.get("threshold") or 0)
    if not same_unit:
        kind = MAJOR
        text = "Другая единица измерения."
    elif left is not None and right is not None and abs(left - right) > threshold:
        kind = MAJOR
        text = "Число вне порога."
    elif _fold(requirement.get("value")) == _fold(found.get("value")) and same_unit:
        kind = MATCH
        text = "Параметр совпадает."
    else:
        kind = MINOR
        text = "Отличается формат записи."
    confidence = "высокая" if requirement.get("from_table") and found.get("from_table") else "низкая"
    return _row(name, kind, confidence, required, text)


def _find(offer: list[dict], name: str) -> dict | None:
    folded = _fold(name)
    for item in offer:
        if _fold(item.get("name")) == folded:
            return item
    return None


def _confidence(rows: list[dict]) -> str:
    if rows and all(row["confidence"] == "высокая" for row in rows):
        return "высокая"
    return "низкая"


def _report(status: str, share: float | None, confidence: str | None, rows: list[dict]) -> dict:
    return {
        "status": status,
        "share": share,
        "confidence": confidence,
        "rows": rows,
        "internet_search": False,
    }


def _row(name: str, kind: str, confidence: str, required: bool, text: str) -> dict:
    return {
        "name": name,
        "class": kind,
        "confidence": confidence,
        "required": required,
        "text": text,
    }


def _number(value: object) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", str(value or "").replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _fold(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).casefold().strip()
