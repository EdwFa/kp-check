"""Арифметика заявки: строка, скидка, НДС и итог.

Ставка НДС берётся только из строки. Код ОКПД2 её не подставляет.
Две суммы строк считаются прямым и обратным проходом и сверяются.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any

from kp_tz_check.calculations import extract_declared_total, parse_money, parse_quantity

TECHNICAL_TOLERANCE = Decimal("0.01")
SUBSTANTIVE = "содержательная ошибка"
TECHNICAL = "техническое расхождение"
INSUFFICIENT = "недостаточно данных"
OK = "ок"


def check_applications(applications: list[dict[str, Any]] | None) -> dict[str, Any]:
    reports = [check_application(item) for item in applications or []]
    findings: list[dict[str, str]] = []
    for report in reports:
        findings.extend(report["findings"])
    return {"reports": reports, "findings": findings}


def check_application(application: dict[str, Any]) -> dict[str, Any]:
    source = str(application.get("source_file") or "заявка")
    lines = [check_line(item) for item in application.get("items") or []]
    amounts = [line["net"] for line in lines if line.get("net") is not None]
    forward = _sum_forward(amounts)
    backward = _sum_backward(amounts)
    declared = extract_declared_total(application.get("body") or "")
    declared_amount = _decimal(declared.get("value"))
    written = _written_total(application.get("body") or "")
    findings: list[dict[str, str]] = []
    for line in lines:
        if line["severity"] == "справка":
            continue
        for text in line["notes"]:
            findings.append(
                {
                    "code": "application-line",
                    "text": f"{line['position']}: {text}",
                    "source": source,
                    "severity": line["severity"],
                }
            )
    math_status = OK
    if forward is None or backward is None:
        math_status = INSUFFICIENT
    elif abs(forward - backward) > TECHNICAL_TOLERANCE:
        math_status = "требует ручной проверки"
        findings.append(
            {
                "code": "application-total",
                "text": (
                    "Требует ручной проверки: прямой и обратный проход не совпали. "
                    f"Прямой итог {_show(forward)}, обратный итог {_show(backward)}."
                ),
                "source": source,
                "severity": "замечание",
            }
        )
    elif declared_amount is not None and forward is not None:
        gap = abs(forward - declared_amount)
        if gap > TECHNICAL_TOLERANCE:
            math_status = SUBSTANTIVE
            findings.append(
                {
                    "code": "application-total",
                    "text": f"Содержательная ошибка: сумма строк {_show(forward)} не равна итогу заявки {_show(declared_amount)}.",
                    "source": source,
                    "severity": "критичная",
                }
            )
        elif gap > 0:
            math_status = TECHNICAL
            findings.append(
                {
                    "code": "application-total",
                    "text": f"Техническое расхождение итога заявки: {_show(gap)}.",
                    "source": source,
                    "severity": "замечание",
                }
            )
    written_status = _compare_written(forward, written)
    if written_status == SUBSTANTIVE:
        findings.append(
            {
                "code": "application-written",
                "text": "Сумма прописью не совпадает с числовым итогом.",
                "source": source,
                "severity": "критичная",
            }
        )
    if any(item["severity"] == "критичная" for item in findings):
        math_status = SUBSTANTIVE
    elif math_status == OK and any(line["status"] == INSUFFICIENT for line in lines):
        math_status = INSUFFICIENT
    elif math_status == OK and any(line["status"] == TECHNICAL for line in lines):
        math_status = TECHNICAL
    for line in lines:
        if isinstance(line.get("net"), Decimal):
            line["net"] = float(line["net"])
    return {
        "source_file": source,
        "lines": lines,
        "forward_total": _float(forward),
        "backward_total": _float(backward),
        "declared_total": _float(declared_amount),
        "written_total": written,
        "written_status": written_status,
        "status": math_status,
        "findings": findings,
    }


def check_line(item: dict[str, Any]) -> dict[str, Any]:
    extra = item.get("extra") or {}
    position = str(item.get("name") or item.get("no") or "—")
    quantity = parse_quantity(item.get("qty"))
    price = parse_money(extra.get("price"))
    declared = parse_money(extra.get("line_sum"))
    notes: list[str] = []
    status = OK
    severity = "справка"
    net: Decimal | None = None
    vat_amount: Decimal | None = None
    if quantity is None or price is None:
        return _line(position, INSUFFICIENT, "недостаточно данных: нет количества или цены", None, None, "замечание")
    base = _money(Decimal(str(quantity)) * Decimal(str(price)))
    discount_status, discounted = _discount(base, extra)
    if discount_status == INSUFFICIENT:
        notes.append("Скидка: недостаточно данных, нужны и процент, и сумма скидки.")
        status = INSUFFICIENT
        severity = "замечание"
        net = base
    else:
        net = discounted
    if declared is None:
        notes.append("Сумма строки не извлечена.")
        status = INSUFFICIENT
        severity = "замечание"
    else:
        gap = abs(_money(Decimal(str(declared))) - net)
        if gap > TECHNICAL_TOLERANCE:
            notes.append(f"Содержательная ошибка: количество × цена = {_show(net)}, в строке {_show(declared)}.")
            status = SUBSTANTIVE
            severity = "критичная"
        elif gap > 0:
            notes.append(f"Техническое расхождение строки: {_show(gap)}.")
            if status == OK:
                status = TECHNICAL
                severity = "замечание"
    rate = _vat_rate(extra.get("vat"))
    if rate is None:
        notes.append("Ставка НДС в строке не указана.")
        if status == OK:
            status = INSUFFICIENT
            severity = "замечание"
    else:
        vat_amount = _money(net * rate / (Decimal("100") + rate))
    if not notes:
        notes.append("Строка сходится.")
    return _line(position, status, notes[0] if len(notes) == 1 else "; ".join(notes), net, vat_amount, severity, notes=notes)


def _discount(base: Decimal, extra: dict[str, Any]) -> tuple[str, Decimal]:
    percent_raw = extra.get("discount_percent") or ""
    sum_raw = extra.get("discount_sum") or ""
    single = extra.get("discount") or ""
    if not percent_raw and not sum_raw:
        if _blank_discount(single):
            return OK, base
        return INSUFFICIENT, base
    if _blank_discount(percent_raw) and _blank_discount(sum_raw):
        return OK, base
    if not percent_raw or not sum_raw or _blank_discount(percent_raw) ^ _blank_discount(sum_raw):
        return INSUFFICIENT, base
    percent = _decimal(parse_money(str(percent_raw).replace("%", "")))
    discount_sum = _decimal(parse_money(str(sum_raw)))
    if percent is None or discount_sum is None:
        return INSUFFICIENT, base
    return OK, _money(base - discount_sum)


def _vat_rate(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    return Decimal(match.group(0).replace(",", "."))


def _written_total(text: str) -> str | None:
    match = re.search(r"прописью\s*[:\-]?\s*([^\n]+)", text or "", re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip() or None


def _compare_written(amount: Decimal | None, written: str | None) -> str:
    if amount is None or not written:
        return "не извлечено"
    parsed = _decimal(parse_money(written))
    if parsed is None:
        return "не извлечено"
    if abs(amount - parsed) > TECHNICAL_TOLERANCE:
        return SUBSTANTIVE
    if abs(amount - parsed) > 0:
        return TECHNICAL
    return OK


def _blank_discount(value: Any) -> bool:
    text = str(value or "").strip().replace("%", "").replace(" ", "").replace(",", ".")
    if not text:
        return True
    try:
        return Decimal(text) == 0
    except Exception:
        return False


def _sum_forward(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    total = Decimal("0")
    for value in values:
        total += value
    return _money(total)


def _sum_backward(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    total = Decimal("0")
    for value in reversed(values):
        total += value
    return _money(total)


def _money(value: Decimal) -> Decimal:
    return value.quantize(TECHNICAL_TOLERANCE, rounding=ROUND_HALF_UP)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return _money(Decimal(str(value)))
    except Exception:
        return None


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _show(value: Any) -> str:
    if isinstance(value, Decimal):
        return f"{value:.2f}".replace(".", ",")
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",")
    return str(value)


def _line(
    position: str,
    status: str,
    note: str,
    net: Decimal | None,
    vat_amount: Decimal | None,
    severity: str,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "position": position,
        "status": status,
        "note": note,
        "notes": notes or [note],
        "net": net,
        "vat_amount": _float(vat_amount),
        "severity": severity,
    }
