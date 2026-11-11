"""Сверка обоснования НМЦК с ценами КП и двумя расчётами CV.

Количество для итога берётся из согласованной позиции. При расхождении
базовых документов количество не выбирается.
"""

from __future__ import annotations

import re
from typing import Any

from kp_tz_check.calculations import (
    calculate_market_statistics,
    check_antidumping,
    collect_market_prices,
    money_format_issue,
    parse_money,
    parse_quantity,
)
from kp_tz_check.calculations_alt import calculate_market_statistics_alt, reconcile_statistics

JUSTIFICATION_NOTE = "Сверка с файлом обоснования не выполнена."
HETEROGENEOUS = "Требует ручной проверки: неоднородная совокупность цен"
QUANTITY_UNCLEAR = "требует уточнения: количество не выбрано из-за расхождения базовых документов"
PRICE_NOT_IN_KP = "цена обоснования не найдена в КП"
SECURITY_UNCLEAR = "требует уточнения"


def build_nmck_report(
    kps: list[dict[str, Any]] | None = None,
    tz_items: list[dict[str, Any]] | None = None,
    nmck_records: list[dict[str, Any]] | None = None,
    baseline: dict[str, Any] | None = None,
    security_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    offers = list(kps or [])
    records = list(nmck_records or [])
    market = collect_market_prices(offers)
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    checked = bool(records)
    if not checked:
        findings.append(
            {
                "code": "nmck-justification",
                "text": JUSTIFICATION_NOTE,
                "source": _first_source(offers),
                "severity": "замечание",
            }
        )
    if len(offers) < 3:
        findings.append(
            {
                "code": "nmck-count",
                "text": f"Для метода анализа рынка нужно не менее 3 цен разных поставщиков. Сейчас КП: {len(offers)}.",
                "source": _first_source(offers),
                "severity": "замечание",
            }
        )
    groups = market.get("groups") or {}
    if not groups and market.get("reason"):
        findings.append(
            {
                "code": "nmck-prices",
                "text": str(market["reason"]),
                "source": _first_source(offers),
                "severity": "замечание",
            }
        )
    for position, group in groups.items():
        row = _position_row(position, group, offers, tz_items or [], baseline, security_documents)
        rows.append(row)
        source = _present((group.get("source_files") or [None])[0])
        if row["status"] == "heterogeneous":
            findings.append(
                {
                    "code": "nmck-cv",
                    "text": f"{HETEROGENEOUS}. Позиция «{position}». {row['statistics_text']}",
                    "source": source,
                    "severity": "замечание",
                }
            )
        elif row["status"] == "manual_review":
            findings.append(
                {
                    "code": "nmck-statistics",
                    "text": f"Позиция «{position}». {row['statistics_text']}",
                    "source": source,
                    "severity": "замечание",
                }
            )
        elif row["status"] not in {"homogeneous", "manual_review"}:
            findings.append(
                {
                    "code": "nmck-group",
                    "text": f"Позиция «{position}»: {group.get('reason') or 'недостаточно данных для НМЦК'}.",
                    "source": source,
                    "severity": "замечание",
                }
            )
        if row["quantity_status"] == "требует уточнения":
            findings.append(
                {
                    "code": "nmck-qty",
                    "text": f"Позиция «{position}»: {QUANTITY_UNCLEAR}.",
                    "source": source,
                    "severity": "замечание",
                }
            )
        for flag in row["antidumping"]:
            findings.append(
                {
                    "code": "nmck-antidumping",
                    "text": flag["text"],
                    "source": flag["source"],
                    "severity": "замечание",
                }
            )
    diffs = _justification_diffs(records, offers)
    for diff in diffs:
        findings.append(
            {
                "code": "nmck-price",
                "text": diff["text"],
                "source": diff["source"],
                "severity": "замечание",
            }
        )
    format_notes = _format_notes(offers, records)
    for note in format_notes:
        findings.append(
            {
                "code": "nmck-format",
                "text": note["text"],
                "source": note["source"],
                "severity": "замечание",
            }
        )
    return {
        "justification_checked": checked,
        "justification_note": None if checked else JUSTIFICATION_NOTE,
        "rows": rows,
        "justification_diffs": diffs,
        "format_notes": format_notes,
        "findings": findings,
        "formula": CV_FORMULA_SAFE(),
    }


def _position_row(
    position: str,
    group: dict[str, Any],
    offers: list[dict[str, Any]],
    tz_items: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
    security_documents: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    values = [float(value) for value in group.get("values") or []]
    primary = calculate_market_statistics(values) if values else {"status": "insufficient_data", "mean": None}
    alternate = calculate_market_statistics_alt(values) if values else {"status": "insufficient_data", "mean": None}
    reconciled = reconcile_statistics(primary, alternate) if values else {"status": "manual_review", "text": "", "n": 0}
    established = group.get("status") in {"homogeneous", "heterogeneous"} and primary.get("mean") is not None
    if reconciled["status"] == "manual_review" and established:
        status = "manual_review"
    else:
        status = group.get("status") or primary.get("status") or "insufficient_data"
    quantity, quantity_status = _quantity(position, tz_items, baseline)
    unit_nmck = primary.get("mean") if established or status == "manual_review" else None
    if status == "insufficient_data":
        unit_nmck = None
    total = unit_nmck * quantity if unit_nmck is not None and quantity else None
    antidumping = []
    if unit_nmck is not None:
        antidumping = _antidumping_flags(position, offers, float(unit_nmck), security_documents)
    review = status in {"heterogeneous", "manual_review"} or bool(antidumping) or quantity_status == "требует уточнения"
    return {
        "position": position,
        "n": reconciled.get("n") or len(values),
        "mean": primary.get("mean"),
        "sigma": primary.get("standard_deviation"),
        "coefficient": primary.get("coefficient_of_variation"),
        "alternate_mean": alternate.get("mean"),
        "alternate_sigma": alternate.get("standard_deviation"),
        "alternate_coefficient": alternate.get("coefficient_of_variation"),
        "statistics_status": reconciled.get("status"),
        "statistics_text": reconciled.get("text") or "",
        "status": status,
        "quantity": quantity,
        "quantity_status": quantity_status,
        "unit_nmck": unit_nmck,
        "total_nmck": total,
        "antidumping": antidumping,
        "review": review,
        "offer_count": group.get("offer_count", 0),
        "supplier_count": (group.get("suppliers") or {}).get("supplier_count", 0),
    }


def _quantity(
    position: str,
    tz_items: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
) -> tuple[float | None, str]:
    if baseline is not None:
        for row in baseline.get("rows") or []:
            if not _row_matches(row, position):
                continue
            status = str(row.get("status") or "")
            if status != "Полностью согласовано":
                return None, "требует уточнения"
            for source in row.get("sources") or []:
                quantity = parse_quantity(str(source.get("qty") or ""))
                if quantity is not None:
                    return quantity, "ок"
            return None, "требует уточнения"
        return None, "нет согласованной позиции"
    for item in tz_items:
        key = str(item.get("name") or item.get("no") or "")
        if key.lower() == position.lower() or position.lower() in key.lower():
            quantity = parse_quantity(item.get("qty"))
            return quantity, "ок" if quantity else "нет количества в ТЗ"
    return None, "нет количества в ТЗ"


def _row_matches(row: dict[str, Any], position: str) -> bool:
    needle = _fold(position)
    for source in row.get("sources") or []:
        if needle and needle in _fold(source.get("name")) or needle == _fold(source.get("no")):
            return True
    return False


def _antidumping_flags(
    position: str,
    offers: list[dict[str, Any]],
    unit_nmck: float,
    security_documents: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for offer in offers:
        supplier = str(offer.get("supplier") or "—")
        source = _present(offer.get("source_file"))
        for item in offer.get("items") or []:
            if not _same_position(item, position):
                continue
            price = parse_money((item.get("extra") or {}).get("price"))
            flag = check_antidumping(price, unit_nmck)
            if flag is None:
                continue
            key = (supplier, flag["text"])
            if key in seen:
                continue
            seen.add(key)
            security = _security_text(security_documents)
            flags.append(
                {
                    "position": position,
                    "supplier": supplier,
                    "source": source,
                    "text": f"{supplier}, «{position}»: {flag['text']} {security}",
                }
            )
    return flags


def _security_text(documents: list[dict[str, Any]] | None) -> str:
    if not documents:
        return "Документ двукратного обеспечения не загружен: требует уточнения."
    blob = "\n".join(str(item.get("body") or "") for item in documents)
    if re.search(r"двукрат|двухкрат", blob, re.IGNORECASE):
        return "Документ обеспечения загружен, в тексте есть двукратное обеспечение."
    return "В документе обеспечения двукратное обеспечение не найдено: требует уточнения."


def _justification_diffs(records: list[dict[str, Any]], offers: list[dict[str, Any]]) -> list[dict[str, str]]:
    diffs: list[dict[str, str]] = []
    kp_rows = _kp_price_index(offers)
    for record in records:
        source = _present(record.get("source_file"))
        for item in record.get("items") or []:
            extra = item.get("extra") or {}
            supplier = str(extra.get("supplier") or "")
            price = parse_money(extra.get("price"))
            if not supplier or price is None:
                continue
            found = any(
                _same_party(row["supplier"], supplier)
                and _same_position(item, row["position"])
                and row["price"] is not None
                and abs(row["price"] - price) <= 0.01
                for row in kp_rows
            )
            if found:
                continue
            name = item.get("name") or item.get("no") or "—"
            diffs.append(
                {
                    "supplier": supplier,
                    "position": str(name),
                    "source": source,
                    "text": f"{PRICE_NOT_IN_KP}: {supplier}, «{name}», цена {_money(price)}.",
                }
            )
    return diffs


def _format_notes(offers: list[dict[str, Any]], records: list[dict[str, Any]]) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    for offer in offers:
        source = _present(offer.get("source_file"))
        for item in offer.get("items") or []:
            raw = (item.get("extra") or {}).get("price")
            issue = money_format_issue(raw)
            if issue:
                parsed = parse_money(raw)
                notes.append(
                    {
                        "source": source,
                        "text": f"{issue} Исходный текст «{raw}», число {_money(parsed)}.",
                    }
                )
    for record in records:
        source = _present(record.get("source_file"))
        for item in record.get("items") or []:
            raw = (item.get("extra") or {}).get("price_raw") or (item.get("extra") or {}).get("price")
            issue = money_format_issue(raw)
            if issue:
                notes.append({"source": source, "text": f"{issue} Исходный текст «{raw}»."})
    return notes


def _kp_price_index(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offer in offers:
        supplier = str(offer.get("supplier") or "")
        for item in offer.get("items") or []:
            rows.append(
                {
                    "supplier": supplier,
                    "position": str(item.get("name") or item.get("no") or ""),
                    "no": str(item.get("no") or ""),
                    "price": parse_money((item.get("extra") or {}).get("price")),
                    "item": item,
                }
            )
    return rows


def _same_position(item: dict[str, Any], position: str) -> bool:
    needle = _fold(position)
    if not needle:
        return False
    if needle == _fold(item.get("no")) or needle == _fold(item.get("name")):
        return True
    return needle in _fold(item.get("name"))


def _same_party(left: str, right: str) -> bool:
    return _fold(left) == _fold(right) and bool(_fold(left))


def _fold(value: Any) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = text.replace("«", "").replace("»", "").replace('"', "")
    return re.sub(r"\s+", " ", text).strip()


def _money(value: float | None) -> str:
    if value is None:
        return "не разобрано"
    return f"{value:.2f}".replace(".", ",")


def _first_source(records: list[dict[str, Any]]) -> str:
    for record in records:
        if record.get("source_file"):
            return _present(record.get("source_file"))
    return "источник отсутствует"


def _present(value: Any) -> str:
    text = str(value or "").strip()
    return text or "источник отсутствует"


def CV_FORMULA_SAFE() -> str:
    from kp_tz_check.calculations import CV_FORMULA

    return CV_FORMULA
