"""Вторая реализация среднего и CV.

Формула та же, что в calculate_market_statistics: σ делится на n.
Эта функция её не вызывает. Сначала считаются отклонения от первого значения,
затем среднее, затем отклонения от среднего, σ и V.
"""

from __future__ import annotations

import math
from typing import Any

from kp_tz_check.calculations import CV_FORMULA, CV_THRESHOLD

STATISTICS_TOLERANCE = 0.01


def calculate_market_statistics_alt(
    values: list[float | int],
    *,
    threshold: float = CV_THRESHOLD,
) -> dict[str, Any]:
    formula = CV_FORMULA
    try:
        parsed = [float(value) for value in values]
    except (TypeError, ValueError):
        return _empty(threshold, formula, "Цена не является числом")
    if not parsed or any(not math.isfinite(value) for value in parsed):
        return _empty(threshold, formula, "Нет конечных числовых цен", values=tuple(parsed))
    provisional = parsed[0]
    raw_deviations = [value - provisional for value in parsed]
    count = len(parsed)
    mean = provisional + sum(raw_deviations) / count
    if mean <= 0:
        return _result(parsed, mean, None, None, threshold, "insufficient_data", formula, "Средняя цена должна быть больше нуля")
    deviations = [value - mean for value in parsed]
    squared = 0.0
    for deviation in deviations:
        squared += deviation * deviation
    sigma = math.sqrt(squared / count)
    coefficient = (sigma * 100.0) / mean
    status = "heterogeneous" if coefficient > threshold else "homogeneous"
    return _result(parsed, mean, sigma, coefficient, threshold, status, formula, None)


def reconcile_statistics(
    primary: dict[str, Any],
    alternate: dict[str, Any],
    *,
    tolerance: float = STATISTICS_TOLERANCE,
) -> dict[str, Any]:
    """Сравнить среднее и CV. Расхождение больше допуска — ручная проверка и оба итога."""
    primary_mean = primary.get("mean")
    alternate_mean = alternate.get("mean")
    primary_cv = primary.get("coefficient_of_variation")
    alternate_cv = alternate.get("coefficient_of_variation")
    agreed = _close(primary_mean, alternate_mean, tolerance) and _close(primary_cv, alternate_cv, tolerance)
    n = len(primary.get("values") or alternate.get("values") or [])
    formula = str(primary.get("formula") or alternate.get("formula") or CV_FORMULA)
    text = _statistics_text(
        formula=formula,
        n=n,
        primary=primary,
        alternate=alternate,
        agreed=agreed,
    )
    return {
        "status": "agreed" if agreed else "manual_review",
        "tolerance": tolerance,
        "n": n,
        "formula": formula,
        "primary": _snapshot(primary),
        "alternate": _snapshot(alternate),
        "text": text,
    }


def _statistics_text(
    *,
    formula: str,
    n: int,
    primary: dict[str, Any],
    alternate: dict[str, Any],
    agreed: bool,
) -> str:
    if agreed:
        return (
            f"Формула: {formula}. n = {n}. "
            f"Среднее {_num(primary.get('mean'))}. "
            f"σ {_num(primary.get('standard_deviation'))}. "
            f"V {_num(primary.get('coefficient_of_variation'))}."
        )
    return (
        "Требует ручной проверки: два расчёта не совпали. "
        f"Формула: {formula}. n = {n}. "
        f"Среднее {_num(primary.get('mean'))} и {_num(alternate.get('mean'))}. "
        f"σ {_num(primary.get('standard_deviation'))} и {_num(alternate.get('standard_deviation'))}. "
        f"V {_num(primary.get('coefficient_of_variation'))} и {_num(alternate.get('coefficient_of_variation'))}."
    )


def _snapshot(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "mean": stats.get("mean"),
        "standard_deviation": stats.get("standard_deviation"),
        "coefficient_of_variation": stats.get("coefficient_of_variation"),
    }


def _close(left: Any, right: Any, tolerance: float) -> bool:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    if not math.isfinite(float(left)) or not math.isfinite(float(right)):
        return False
    return abs(float(left) - float(right)) <= tolerance


def _num(value: Any) -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return "не рассчитано"
    return f"{float(value):.2f}".replace(".", ",")


def _empty(threshold: float, formula: str, reason: str, values: tuple[float, ...] = ()) -> dict[str, Any]:
    return _result(list(values), None, None, None, threshold, "insufficient_data", formula, reason)


def _result(
    values: list[float],
    mean: float | None,
    sigma: float | None,
    coefficient: float | None,
    threshold: float,
    status: str,
    formula: str,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "values": list(values),
        "mean": mean,
        "standard_deviation": sigma,
        "coefficient_of_variation": coefficient,
        "threshold": threshold,
        "status": status,
        "formula": formula,
        "reason": reason,
    }
