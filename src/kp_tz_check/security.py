"""Извлечение требований к обеспечению заявки и договора."""

from __future__ import annotations

import re
from typing import Any

PERCENT_RE = re.compile(
    r"(обеспечени\w*|гаранти\w*)[^%\n]{0,100}?(\d+(?:[.,]\d+)?)\s*%",
    re.IGNORECASE,
)
MONEY_RE = re.compile(
    r"(обеспечени\w*|гаранти\w*)[^.\n]{0,100}?"
    r"(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:руб\.?|₽)",
    re.IGNORECASE,
)


def extract_security_requirements(text: str) -> dict[str, Any]:
    percentages = [
        {"context": match.group(1), "value": float(match.group(2).replace(",", "."))}
        for match in PERCENT_RE.finditer(text or "")
    ]
    amounts = [
        {
            "context": match.group(1),
            "value": float(match.group(2).replace(" ", "").replace(",", ".")),
        }
        for match in MONEY_RE.finditer(text or "")
    ]
    return {"percentages": percentages, "amounts": amounts}


def check_security_requirements(
    requests: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tz_text = "\n".join(str(item.get("body", "")) for item in tzs)
    tz_requirements = extract_security_requirements(tz_text)
    results: list[dict[str, Any]] = []
    for request in requests:
        request_requirements = extract_security_requirements(request.get("body", ""))
        percentages = request_requirements["percentages"] + tz_requirements["percentages"]
        amounts = request_requirements["amounts"] + tz_requirements["amounts"]
        if not percentages and not amounts:
            status = "REVIEW"
            reason = "Требования к обеспечению не найдены."
        else:
            status = "REVIEW"
            reason = (
                "Требования извлечены. Наличие и действительность гарантии "
                "нужно подтвердить по отдельному документу."
            )
        results.append(
            {
                "status": status,
                "request_file": str(request.get("source_file", "—")),
                "percentages": percentages,
                "amounts": amounts,
                "reason": reason,
                "evidence": {
                    "request": request_requirements,
                    "tz": tz_requirements,
                },
            }
        )
    return results


NMCK_LIMIT = 5_000_000


def evaluate_security(
    *,
    nmck_total: float | None,
    smp: bool | None,
    application_percent: float | None,
    contract_percent: float | None,
    advance: float | None,
    advance_security: float | None,
) -> list[dict[str, str]]:
    """Пороги п. 4.2.4.8. Граница 5 000 000 входит в правило «применяется»."""
    return [
        _application_rule(nmck_total, smp, application_percent),
        _contract_rule(smp, contract_percent),
        _advance_rule(advance, advance_security),
    ]


def classify_security_amounts(text: str) -> dict[str, float | None]:
    """Разложить проценты и суммы по виду обеспечения. Ненайденное остаётся пустым."""
    application_percent = None
    contract_percent = None
    advance = None
    advance_security = None
    for match in PERCENT_RE.finditer(text or ""):
        window = match.group(0).lower()
        value = float(match.group(2).replace(",", "."))
        if "заяв" in window:
            application_percent = value
        elif "исполн" in window or "контракт" in window or "договор" in window:
            contract_percent = value
    for match in MONEY_RE.finditer(text or ""):
        window = match.group(0).lower()
        value = float(match.group(2).replace(" ", "").replace(",", "."))
        if "аванс" in window and "обеспеч" in window:
            advance_security = value
        elif "аванс" in window:
            advance = value
    return {
        "application_percent": application_percent,
        "contract_percent": contract_percent,
        "advance": advance,
        "advance_security": advance_security,
    }


def _application_rule(nmck_total: float | None, smp: bool | None, percent: float | None) -> dict[str, str]:
    if nmck_total is None:
        return _security_row("заявка", "ТРЕБУЕТ УТОЧНЕНИЯ", "НМЦК неизвестна, порог обеспечения заявки не выбран.")
    if nmck_total < NMCK_LIMIT:
        return _security_row("заявка", "НЕ ПРИМЕНЯЕТСЯ", "НМЦК ниже 5 000 000, обеспечение заявки не применяется.")
    if smp is None:
        return _security_row("заявка", "ТРЕБУЕТ УТОЧНЕНИЯ", "Признак СМП неизвестен, порог не выбран.")
    if percent is None:
        return _security_row("заявка", "ТРЕБУЕТ УТОЧНЕНИЯ", "Процент обеспечения заявки не извлечён.")
    limit = 2.0 if smp else 5.0
    if percent <= limit:
        return _security_row("заявка", "ОК", f"Обеспечение заявки {_pct(percent)} не выше {_pct(limit)}.")
    return _security_row("заявка", "ОШИБКА", f"Обеспечение заявки {_pct(percent)} выше {_pct(limit)}.")


def _contract_rule(smp: bool | None, percent: float | None) -> dict[str, str]:
    if smp is None:
        return _security_row("исполнение", "ТРЕБУЕТ УТОЧНЕНИЯ", "Признак СМП неизвестен, порог исполнения не выбран.")
    if percent is None:
        return _security_row("исполнение", "ТРЕБУЕТ УТОЧНЕНИЯ", "Процент обеспечения исполнения не извлечён.")
    if smp:
        if percent <= 5:
            return _security_row("исполнение", "ОК", f"Обеспечение исполнения {_pct(percent)} не выше 5% для СМП.")
        return _security_row("исполнение", "ОШИБКА", f"Обеспечение исполнения {_pct(percent)} выше 5% для СМП.")
    if 5 <= percent <= 30:
        return _security_row("исполнение", "ОК", f"Обеспечение исполнения {_pct(percent)} в диапазоне 5–30%.")
    return _security_row("исполнение", "ОШИБКА", f"Обеспечение исполнения {_pct(percent)} вне диапазона 5–30%.")


def _advance_rule(advance: float | None, security_amount: float | None) -> dict[str, str]:
    if advance is None or security_amount is None:
        return _security_row("аванс", "ТРЕБУЕТ УТОЧНЕНИЯ", "Нет суммы аванса или обеспечения аванса.")
    if abs(advance - security_amount) <= 0.01:
        return _security_row("аванс", "ОК", "Обеспечение аванса равно авансу.")
    return _security_row("аванс", "ОШИБКА", "Обеспечение аванса не равно авансу.")


def _security_row(kind: str, status: str, text: str) -> dict[str, str]:
    return {"kind": kind, "status": status, "text": f"{status}: {text}"}


def _pct(value: float) -> str:
    return f"{f'{value:g}'.replace('.', ',')}%"

