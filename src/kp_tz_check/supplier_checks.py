"""Локальная проверка поставщика и реквизитов в коммерческих предложениях."""

from __future__ import annotations

import re
from typing import Any

from kp_tz_check.match import suppliers_conflict
from kp_tz_check.registries import DisabledRegistry, RegistryLookup

REQUISITE_PATTERNS = {
    "inn": re.compile(r"\bИ\s*Н\s*Н\b\s*[:№]?\s*(\d{10,12})", re.IGNORECASE),
    "kpp": re.compile(r"\bК\s*П\s*П\b\s*[:№]?\s*(\d{9})", re.IGNORECASE),
    "ogrn": re.compile(r"\bО\s*Г\s*Р\s*Н\b\s*[:№]?\s*(\d{13,15})", re.IGNORECASE),
}

CRITERIA = (
    ("koap_19_28", "КоАП 19.28"),
    ("rnp_223", "РНП 223-ФЗ"),
    ("rnp_44", "РНП 44-ФЗ"),
    ("liquidation", "Ликвидация"),
    ("bankruptcy", "Банкротство"),
    ("exclusion", "Предстоящее исключение"),
    ("unreliable", "Недостоверность сведений"),
    ("disqualification", "Дисквалификация"),
    ("extremism", "Экстремизм/терроризм"),
    ("foreign_agent", "Иноагент"),
    ("ecg", "ЭКГ ≥ 51"),
)


def extract_requisites(text: str) -> dict[str, str | None]:
    """Извлекает реквизиты из текста документа без сетевых запросов."""
    return {
        name: (match.group(1) if (match := pattern.search(text or "")) else None)
        for name, pattern in REQUISITE_PATTERNS.items()
    }


def check_suppliers(
    results: list[dict[str, Any]],
    *,
    kps: list[dict[str, Any]] | None = None,
    registry: RegistryLookup | None = None,
) -> list[dict[str, Any]]:
    """Возвращает проверку каждой пары КП с доказательствами."""
    kp_by_file = {
        str(item.get("source_file")): item
        for item in (kps or [])
        if item.get("source_file")
    }
    checks: list[dict[str, Any]] = []
    for result in results:
        kp = result.get("kp") or {}
        request = result.get("request") or {}
        if not kp:
            continue
        source_file = str(kp.get("source_file") or "")
        source = kp_by_file.get(source_file, kp)
        requisites = extract_requisites(source.get("body", ""))
        missing = [name.upper() for name, value in requisites.items() if not value]
        request_supplier = request.get("supplier")
        kp_supplier = kp.get("supplier")
        conflict = suppliers_conflict(request_supplier, kp_supplier)
        registry = registry or DisabledRegistry()
        registry_key = requisites.get("inn") or requisites.get("ogrn") or kp_supplier or ""
        criteria = _criteria(registry, registry_key)
        egrul = getattr(registry, "card_for", lambda key: None)(registry_key)
        if conflict:
            status = "FAIL"
            reason = "Название поставщика в КП не совпадает с адресатом запроса."
            card = "Выявлены риски"
        elif missing:
            status = "REVIEW"
            reason = f"Не найдены реквизиты: {', '.join(missing)}."
            card = "Проверка реестров не выполнялась"
        else:
            status = "PASS"
            reason = "Поставщик и обязательные реквизиты найдены."
            card = "Проверка реестров не выполнялась"
        if any(row["status"] == "not_checked" for row in criteria):
            card = "Выявлены риски" if conflict else "Проверка реестров не выполнялась"
        checks.append(
            {
                "status": status,
                "reason": reason,
                "supplier": kp_supplier or "—",
                "request_supplier": request_supplier or "—",
                "source_file": source_file or "—",
                "requisites": requisites,
                "missing": missing,
                "supplier_conflict": conflict,
                "criteria": criteria,
                "card": card,
                "egrul": egrul if isinstance(egrul, dict) and egrul.get("status") != "нужен ИНН или ОГРН" else None,
            }
        )
    return checks


def _criteria(registry: RegistryLookup, key: str) -> list[dict[str, Any]]:
    rows = []
    for kind, title in CRITERIA:
        found = registry.lookup(kind, key)
        rows.append(
            {
                "criterion": title,
                "status": found.get("status") or "not_checked",
                "value": found.get("value"),
                "source": found.get("source_url") or "",
            }
        )
    return rows
