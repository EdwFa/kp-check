"""Отклонение цены от НМЦК. Внешняя рыночная цена пустая, пока адаптер выключен."""

from __future__ import annotations

import math


DUMPING = "Риск демпинга, требуется обоснование"
HIGH = "Цена выше рыночной, требуется уточнение"
ANOMALY = "Аномалия"
MARKET_UNCHECKED = "не проверена"
JUSTIFIED = "Цены обоснованы"


def rows_from_offers(kps: list[dict], nmck_rows: list[dict]) -> list[dict]:
    by_name = {str(row.get("position") or "").casefold(): row.get("unit_nmck") for row in nmck_rows}
    collected = []
    for offer in kps:
        for item in offer.get("items") or []:
            extra = item.get("extra") or {}
            name = item.get("name") or item.get("no") or "—"
            collected.append(
                {
                    "supplier": offer.get("supplier"),
                    "position": name,
                    "price": extra.get("price"),
                    "nmck": by_name.get(str(name).casefold()),
                }
            )
    return collected


def assess_prices(
    rows: list[dict],
    *,
    cv_passed: bool,
    market_price: float | None,
) -> dict:
    sample = [price for row in rows if (price := _float(row.get("price"))) is not None]
    mean, sigma = _moments(sample)
    assessed = []
    for row in rows:
        price = _float(row.get("price"))
        nmck = _float(row.get("nmck"))
        deviation = None if price is None or nmck in (None, 0) else (price - nmck) / nmck
        notes = []
        if deviation is not None and deviation <= -0.25:
            notes.append(DUMPING)
        if deviation is not None and deviation >= 0.20:
            notes.append(HIGH)
        if price is not None and sigma and abs(price - mean) > 2 * sigma:
            notes.append(ANOMALY)
        assessed.append(
            {
                "supplier": row.get("supplier") or "—",
                "position": row.get("position") or "—",
                "price": price,
                "nmck": nmck,
                "deviation": deviation,
                "market_price": market_price,
                "market_status": MARKET_UNCHECKED if market_price is None else "получена",
                "cv_passed": cv_passed,
                "notes": notes,
            }
        )
    justified = bool(assessed) and market_price is not None and cv_passed and all(not item["notes"] for item in assessed)
    return {
        "rows": assessed,
        "verdict": JUSTIFIED if justified else "Цены не обоснованы",
        "mean": mean,
        "sigma": sigma,
    }


def _moments(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    mean = sum(values) / len(values)
    sigma = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    return mean, sigma


def _float(value: object) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = (
        str(value)
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
