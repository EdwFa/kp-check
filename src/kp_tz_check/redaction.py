"""Два контура: аналитический отчёт без ФИО и договор с реквизитами."""

from __future__ import annotations

import hashlib


def build_contours(source: dict) -> dict:
    customer = str(source.get("customer") or "")
    director = str(source.get("director") or "")
    operator = str(source.get("operator") or "")
    winner = dict(source.get("winner") or {})
    items = [dict(item) for item in source.get("items") or []]
    analytics = {
        "customer": _code("заказчик", customer),
        "director": _code("фио", director),
        "operator": _code("фио", operator),
        "winner": _code("фио", str(winner.get("director") or "")),
        "items": items,
    }
    contract = {
        "customer": customer,
        "director": director,
        "operator": operator,
        "winner": winner,
        "items": [dict(item) for item in items],
    }
    return {
        "analytics": analytics,
        "contract": contract,
        "journal_code": analytics["operator"] or analytics["director"],
    }


def _code(prefix: str, value: str) -> str:
    if not value.strip():
        return ""
    digest = hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{digest}"
