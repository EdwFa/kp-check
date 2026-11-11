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
_TOTAL_RE = re.compile(
    r"(?:итого|всего|общая\s+стоимость|к\s+оплате|сумма)"
    r"\s*(?:по\s+договору|кп|заказа)?\s*[:\-]?\s*"
    r"(\d[\d\s]*(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)


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


_CANONICAL_MONEY = re.compile(r"^(?:\d{1,3}|\d{1,3}(?: \d{3})+),\d{2}$")
_SHORT_INTEGER = re.compile(r"^\d{1,3}$")


def money_format_issue(raw: str | None) -> str | None:
    """Замечание формата. Разобранное число при этом всё равно считается отдельно."""
    if raw is None:
        return None
    text = str(raw).replace("\u00a0", " ").strip()
    if not text or _SHORT_INTEGER.fullmatch(text) or _CANONICAL_MONEY.fullmatch(text):
        return None
    return "Формат суммы: нужны разряды и десятичная запятая. Расчёт использует разобранное число."


def check_antidumping(price: float | None, nmck: float | None) -> dict[str, Any] | None:
    """Флаг, если цена ниже пересчитанной НМЦК на 25% и больше. Без НМЦК флага нет."""
    if price is None or nmck is None or nmck <= 0 or not math.isfinite(price) or not math.isfinite(nmck):
        return None
    deviation = (price - nmck) / nmck
    if deviation > -0.25:
        return None
    shown = f"{abs(deviation) * 100:.2f}".replace(".", ",")
    return {
        "deviation": deviation,
        "text": f"Цена ниже пересчитанной НМЦК на {shown}%. Антидемпинг, п. 1.9.23.",
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


def extract_declared_total(text: str | None) -> dict[str, Any]:
    """Найти явно подписанную итоговую сумму в тексте КП."""
    matches = list(_TOTAL_RE.finditer(text or ""))
    if not matches:
        return {"status": "insufficient_data", "value": None, "raw": None}
    raw = matches[-1].group(1)
    value = parse_money(raw)
    if value is None:
        return {"status": "insufficient_data", "value": None, "raw": raw}
    return {"status": "ok", "value": value, "raw": raw}


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


def calculate_offer_totals(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Рассчитать суммы строк и итог по каждому КП."""
    reports: list[dict[str, Any]] = []
    for offer in offers:
        lines: list[dict[str, Any]] = []
        for item in offer.get("items") or []:
            comparable = comparable_price(item)
            quantity = parse_quantity(item.get("qty"))
            if comparable["status"] != "ok" or quantity is None:
                lines.append(
                    {
                        "position": item.get("name") or item.get("no") or "—",
                        "status": "insufficient_data",
                        "reason": comparable.get("reason") or "Количество не распознано",
                    }
                )
                continue
            unit_price = float(comparable["price"])
            line_total = (
                unit_price * quantity
                if comparable["price_kind"] == "price_unit"
                else unit_price * quantity
            )
            lines.append(
                {
                    "position": item.get("name") or item.get("no") or "—",
                    "quantity": quantity,
                    "unit": comparable.get("unit") or "—",
                    "unit_price": unit_price,
                    "line_total": line_total,
                    "price_kind": comparable["price_kind"],
                    "vat": comparable.get("vat") or "—",
                    "status": "ok",
                    "formula": f"{quantity:g} × {unit_price:,.2f} = {line_total:,.2f}",
                }
            )
        valid_lines = [line for line in lines if line["status"] == "ok"]
        calculated_total = sum(line["line_total"] for line in valid_lines)
        declared = extract_declared_total(offer.get("body", ""))
        if declared["status"] != "ok":
            arithmetic_status = "review"
            arithmetic_reason = "Итоговая сумма КП не найдена в тексте документа"
            difference = None
        else:
            difference = calculated_total - declared["value"]
            arithmetic_status = "pass" if abs(difference) <= 0.01 else "fail"
            arithmetic_reason = (
                None
                if arithmetic_status == "pass"
                else "Итоговая сумма КП не совпадает с суммой строк"
            )
        reports.append(
            {
                "supplier": offer.get("supplier") or "—",
                "source_file": offer.get("source_file") or "—",
                "lines": lines,
                "total": calculated_total,
                "status": "ok" if valid_lines and len(valid_lines) == len(lines) else "review",
                "declared_total": declared["value"],
                "declared_total_raw": declared["raw"],
                "difference": difference,
                "arithmetic_status": arithmetic_status,
                "arithmetic_reason": arithmetic_reason,
                "formula": "Итог КП = Σ (количество × цена за единицу)",
            }
        )
    return reports


def calculate_nmck(
    offers: list[dict[str, Any]],
    tz_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Рассчитать НМЦК по средним сопоставимым ценам рынка."""
    market = collect_market_prices(offers)
    rows: list[dict[str, Any]] = []
    tz_items = tz_items or []
    for position, group in market.get("groups", {}).items():
        quantity = None
        for item in tz_items:
            item_key = str(item.get("name") or item.get("no") or "")
            if item_key.lower() == position.lower() or position.lower() in item_key.lower():
                quantity = parse_quantity(item.get("qty"))
                break
        unit_nmck = group.get("mean")
        rows.append(
            {
                "position": position,
                "method": "Среднее арифметическое сопоставимых цен",
                "unit_nmck": unit_nmck,
                "quantity": quantity,
                "total_nmck": unit_nmck * quantity if unit_nmck is not None and quantity else None,
                "offer_count": group.get("offer_count", 0),
                "supplier_count": (group.get("suppliers") or {}).get("supplier_count", 0),
                "status": group.get("status", "insufficient_data"),
                "source_files": group.get("source_files", []),
                "formula": "НМЦК = средняя цена за единицу × количество",
            }
        )
    return {
        "method": "Среднее арифметическое сопоставимых цен",
        "rows": rows,
        "status": market.get("status", "insufficient_data"),
    }


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
