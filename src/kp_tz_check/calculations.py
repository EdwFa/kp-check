"""Детерминированные расчёты для compliance.

Модуль не читает документы и не использует LLM. Все функции возвращают
исходные значения и формулу, чтобы результат можно было проверить вручную.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

CV_THRESHOLD = 33.0
CV_FORMULA = "V = σ / ц̄ × 100%; σ = sqrt(sum((цᵢ - ц̄)^2) / n)"


@dataclass(frozen=True)
class MarketStatistics:
    values: tuple[float, ...]
    mean: float | None
    standard_deviation: float | None
    coefficient_of_variation: float | None
    threshold: float
    status: str
    formula: str
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "values": list(self.values),
            "mean": self.mean,
            "standard_deviation": self.standard_deviation,
            "coefficient_of_variation": self.coefficient_of_variation,
            "threshold": self.threshold,
            "status": self.status,
            "formula": self.formula,
            "reason": self.reason,
        }


def calculate_market_statistics(
    values: list[float | int],
    *,
    threshold: float = CV_THRESHOLD,
) -> dict[str, Any]:
    """Рассчитать CV по совокупности цен.

    Используется population standard deviation (деление на n), как для
    совокупности значений, участвующих в конкретном расчёте НМЦД.
    """

    formula = CV_FORMULA
    try:
        numbers = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return MarketStatistics((), None, None, None, threshold, "insufficient_data", formula, "Цена не является числом").as_dict()
    if not numbers or any(not math.isfinite(value) for value in numbers):
        return MarketStatistics(numbers, None, None, None, threshold, "insufficient_data", formula, "Нет конечных числовых цен").as_dict()
    mean = sum(numbers) / len(numbers)
    if mean <= 0:
        return MarketStatistics(numbers, mean, None, None, threshold, "insufficient_data", formula, "Средняя цена должна быть больше нуля").as_dict()
    deviation = math.sqrt(sum((value - mean) ** 2 for value in numbers) / len(numbers))
    coefficient = deviation / mean * 100
    status = "heterogeneous" if coefficient > threshold else "homogeneous"
    return MarketStatistics(numbers, mean, deviation, coefficient, threshold, status, formula).as_dict()


def check_supplier_diversity(suppliers: list[str | None]) -> dict[str, Any]:
    normalized = {
        re.sub(r"\s+", " ", supplier.strip().lower())
        for supplier in suppliers
        if supplier and supplier.strip()
    }
    return {
        "supplier_count": len(normalized),
        "suppliers": sorted(normalized),
        "status": "ok" if normalized else "insufficient_data",
        "reason": None if normalized else "Не удалось прочитать поставщиков",
    }


_CONSTRAINT_RE = re.compile(
    r"\b(не\s+менее|не\s+более)\s*([0-9]+(?:[.,][0-9]+)?)",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(r"(?<!\d)(\d[\d\s]*(?:[.,]\d{1,2})?)(?!\d)")
_NUMBER_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)")


def parse_quantity(value: str | None) -> float | None:
    if not value:
        return None
    match = _NUMBER_RE.search(value.replace("\u00a0", " "))
    if not match:
        return None
    try:
        result = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None


def normalize_unit(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[.\s]+", "", value.lower().replace("ё", "е"))
    aliases = {
        "шт": "шт",
        "штук": "шт",
        "штука": "шт",
        "ед": "шт",
        "единица": "шт",
        "упак": "упак",
        "упаковка": "упак",
        "компл": "комплект",
        "комплект": "комплект",
        "набор": "набор",
    }
    return aliases.get(normalized, normalized or None)


def comparable_price(item: dict[str, Any]) -> dict[str, Any]:
    """Вернуть цену в явной базе сравнения или причину отказа."""

    extra = item.get("extra") or {}
    price = parse_money(extra.get("price"))
    if price is None:
        return {"status": "insufficient_data", "reason": "Цена не распознана"}
    kind = extra.get("price_kind")
    if kind == "price_total":
        quantity = parse_quantity(item.get("qty"))
        if quantity is None:
            return {
                "status": "insufficient_data",
                "reason": "Для суммы не распознано количество",
            }
        price = price / quantity
    elif kind != "price_unit":
        return {
            "status": "insufficient_data",
            "reason": "Неизвестна база цены: единица или строка",
        }
    return {
        "status": "ok",
        "price": price,
        "unit": normalize_unit(item.get("unit")),
        "vat": extra.get("vat"),
        "price_kind": kind,
    }


def parse_money(value: str | None) -> float | None:
    """Извлечь цену только из явно ценового поля."""

    if not value:
        return None
    match = _MONEY_RE.search(value.replace("\u00a0", " "))
    if not match:
        return None
    raw = re.sub(r"\s+", "", match.group(1)).replace(",", ".")
    try:
        result = float(raw)
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None


def collect_market_prices(
    offers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Сгруппировать явные цены по сопоставимой товарной позиции."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for offer in offers:
        items = offer.get("items") or []
        for item in items:
            comparable = comparable_price(item)
            if comparable["status"] != "ok":
                continue
            price = comparable["price"]
            article = (item.get("extra") or {}).get("article", "")
            match = re.search(r"(?:FCH|форма)\s*[-_]?\s*3700\s*[/\-]\s*\d+", f"{article} {item.get('name', '')}", re.I)
            key = match.group(0).upper().replace(" ", "") if match else str(item.get("no") or item.get("name") or "unknown")
            grouped.setdefault(key, []).append(
                {
                    "price": price,
                    "supplier": offer.get("supplier"),
                    "source_file": offer.get("source_file"),
                    "unit": comparable["unit"],
                    "vat": comparable["vat"],
                }
            )

    groups: dict[str, dict[str, Any]] = {}
    overall_status = "homogeneous"
    for key, rows in grouped.items():
        stats = calculate_market_statistics([row["price"] for row in rows])
        suppliers = check_supplier_diversity([row["supplier"] for row in rows])
        stats["suppliers"] = suppliers
        stats["source_files"] = [row["source_file"] for row in rows]
        stats["offer_count"] = len(rows)
        if len(rows) < 3 or suppliers["supplier_count"] < 3:
            stats["status"] = "insufficient_data"
            stats["reason"] = "Для позиции недостаточно цен разных поставщиков"
        units = {row["unit"] for row in rows}
        vats = {row["vat"] for row in rows if row["vat"] not in {None, ""}}
        stats["units"] = sorted(unit for unit in units if unit)
        stats["vat_values"] = sorted(vats)
        if len(units - {None}) > 1:
            stats["status"] = "insufficient_data"
            stats["reason"] = "Единицы измерения ценовых строк различаются"
        elif not vats or len(vats) > 1 or any(row["vat"] in {None, ""} for row in rows):
            stats["status"] = "insufficient_data"
            stats["reason"] = "Не удалось подтвердить одинаковый режим НДС"
        groups[key] = stats
        if stats["status"] != "homogeneous":
            overall_status = stats["status"]

    if not groups:
        return {
            "status": "insufficient_data",
            "groups": {},
            "reason": "Не удалось извлечь явные цены из КП",
        }
    return {"status": overall_status, "groups": groups}


def check_spec_constraint(
    tz_specs: str,
    kp_specs: str,
) -> dict[str, Any]:
    """Проверить числовой порог ТЗ против конкретного значения КП."""

    match = _CONSTRAINT_RE.search(tz_specs or "")
    if not match:
        return {"status": "not_applicable", "reason": "Порог в ТЗ не найден"}
    operator = match.group(1).lower().replace(" ", " ")
    threshold = float(match.group(2).replace(",", "."))
    kp_value_match = re.search(r"(?<![A-Za-zА-Яа-я])\d+(?:[.,]\d+)?", kp_specs or "")
    if not kp_value_match:
        return {
            "status": "insufficient_data",
            "operator": operator,
            "threshold": threshold,
            "reason": "Конкретное значение в КП не найдено",
        }
    actual = float(kp_value_match.group(0).replace(",", "."))
    passed = actual >= threshold if "менее" in operator else actual <= threshold
    return {
        "status": "pass" if passed else "fail",
        "operator": operator,
        "threshold": threshold,
        "actual": actual,
        "reason": None if passed else "Значение КП не соответствует порогу ТЗ",
    }
