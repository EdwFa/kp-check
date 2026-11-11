"""Производители, страна происхождения и локальный перечень нацрежима.

Поставщик не подставляется вместо производителя. Адрес поставщика не становится страной.
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any

from kp_tz_check.instruction import abbreviation_issues, enumeration_issue

REGIME_NOT_LOADED = "перечень № 1875 не загружен. Проверка запрета не выполняется."
REGIME_CRITICAL = "Критическая ошибка: нарушение нацрежима"
INSUFFICIENT = "недостаточно данных"
EAEU = ("россия", "рф", "беларус", "белорус", "казахстан", "армени", "кыргыз", "киргиз")


def load_national_regime(path: str | Path | None = None) -> list[dict[str, str]] | None:
    if path is None:
        raw = os.environ.get("KP_NATIONAL_REGIME_CATALOG")
        if not raw:
            return None
        path = Path(raw)
    file_path = Path(path)
    with file_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for raw_row in reader:
            row = {str(key).strip(): (value or "").strip() for key, value in raw_row.items() if key}
            if row.get("okpd2_prefix") and row.get("measure"):
                rows.append(row)
    return rows


def build_competition_report(
    kps: list[dict[str, Any]] | None = None,
    tzs: list[dict[str, Any]] | None = None,
    catalog: list[dict[str, str]] | None = None,
    *,
    load_catalog: bool = True,
) -> dict[str, Any]:
    offers = list(kps or [])
    requirements = list(tzs or [])
    if load_catalog and catalog is None:
        catalog = load_national_regime()
    groups = _groups(offers)
    has_positions = bool(groups) or any(record.get("items") for record in requirements)
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    if not has_positions:
        return {
            "catalog_loaded": catalog is not None,
            "rows": [],
            "findings": [
                {
                    "code": "3",
                    "text": "Товарные позиции не загружены.",
                    "source": "источник отсутствует",
                    "severity": "справка",
                }
            ],
            "status": "not_checked",
        }
    if catalog is None:
        findings.append(
            {
                "code": "3",
                "text": REGIME_NOT_LOADED,
                "source": _first_source(offers) or _first_source(requirements),
                "severity": "замечание",
            }
        )
    for key, pairs in groups.items():
        row, row_findings = _position_row(key, pairs, requirements, catalog)
        rows.append(row)
        findings.extend(row_findings)
    if not groups and catalog is None:
        pass
    findings.extend(_linguistic_findings(offers, requirements))
    status = "remarks"
    if any(item["severity"] == "критичная" for item in findings):
        status = "critical"
    elif not any(item["severity"] == "замечание" for item in findings):
        status = "clean"
    return {"catalog_loaded": catalog is not None, "rows": rows, "findings": findings, "status": status}


def _position_row(
    key: str,
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    tzs: list[dict[str, Any]],
    catalog: list[dict[str, str]] | None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    item = pairs[0][1]
    position = str(item.get("name") or key)
    source = _present(pairs[0][0].get("source_file"))
    manufacturers = _unique((pair[1].get("extra") or {}).get("manufacturer") for pair in pairs)
    countries = _unique((pair[1].get("extra") or {}).get("country") for pair in pairs)
    missing_manufacturer = any("manufacturer" not in (pair[1].get("extra") or {}) or not str((pair[1].get("extra") or {}).get("manufacturer") or "").strip() for pair in pairs)
    missing_country = any(not str((pair[1].get("extra") or {}).get("country") or "").strip() for pair in pairs)
    code = _position_code(pairs, tzs)
    measure = _measure(code, catalog)
    findings: list[dict[str, str]] = []
    status = "замечаний нет"
    if missing_manufacturer:
        status = INSUFFICIENT
        findings.append(_finding(f"Позиция «{position}»: производитель не указан, {INSUFFICIENT}.", source, "замечание"))
    elif len(manufacturers) < 2:
        status = "замечание"
        names = ", ".join(manufacturers) or "—"
        findings.append(
            _finding(
                f"Позиция «{position}»: уникальных производителей {len(manufacturers)}. Названия: {names}.",
                source,
                "замечание",
            )
        )
    if missing_country:
        if status == "замечаний нет":
            status = INSUFFICIENT
        findings.append(_finding(f"Позиция «{position}»: страна происхождения не указана, {INSUFFICIENT}.", source, "замечание"))
    if catalog is not None and measure is not None:
        foreign = [country for country in countries if country and not _eaeu(country)]
        if foreign:
            status = "критичная ошибка"
            findings.append(
                _finding(
                    f"{REGIME_CRITICAL}. Позиция «{position}», страна: {', '.join(foreign)}.",
                    source,
                    "критичная",
                )
            )
        requires = measure.get("requires") or ""
        if requires == "registry" and any("registry" not in (pair[1].get("extra") or {}) for pair in pairs):
            findings.append(_finding(f"Позиция «{position}»: реестровый номер не указан, требует уточнения.", source, "замечание"))
        if requires == "st1" and any("st1" not in (pair[1].get("extra") or {}) for pair in pairs):
            findings.append(_finding(f"Позиция «{position}»: СТ-1 не указан, требует уточнения.", source, "замечание"))
    return (
        {
            "position": position,
            "manufacturers": ", ".join(manufacturers) or "—",
            "manufacturer_count": len(manufacturers),
            "countries": ", ".join(countries) or "—",
            "measure": (measure or {}).get("measure") or "—",
            "status": status,
        },
        findings,
    )


def _linguistic_findings(kps: list[dict[str, Any]], tzs: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    tz_items = [item for tz in tzs for item in tz.get("items") or []]
    for offer in kps:
        source = _present(offer.get("source_file"))
        body = str(offer.get("body") or "")
        for item in offer.get("items") or []:
            text = f"{item.get('name') or ''} {item.get('specs') or ''}"
            for token in abbreviation_issues(text, body or text):
                findings.append(_finding(f"Сокращение «{token}» без расшифровки.", source, "замечание"))
            tz_item = _tz_match(item, tz_items)
            if tz_item is None:
                continue
            issue = enumeration_issue(str(tz_item.get("specs") or ""), str(item.get("specs") or ""))
            if issue:
                findings.append(_finding(f"Позиция «{item.get('name') or '—'}»: {issue}", source, "замечание"))
    return findings


def _groups(kps: list[dict[str, Any]]) -> dict[str, list[tuple[dict[str, Any], dict[str, Any]]]]:
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for offer in kps:
        for item in offer.get("items") or []:
            key = str(item.get("no") or item.get("name") or "—")
            grouped.setdefault(key, []).append((offer, item))
    return grouped


def _unique(values) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        text = str(value or "").strip()
        folded = _fold(text)
        if folded and folded not in seen:
            seen[folded] = text
    return list(seen.values())


def _position_code(pairs, tzs) -> str:
    for _, item in pairs:
        code = str((item.get("extra") or {}).get("okpd2") or "").strip()
        if code:
            return code
    number = str(pairs[0][1].get("no") or "")
    for tz in tzs:
        for item in tz.get("items") or []:
            if number and str(item.get("no") or "") == number:
                return str((item.get("extra") or {}).get("okpd2") or "")
    return ""


def _measure(code: str, catalog: list[dict[str, str]] | None) -> dict[str, str] | None:
    if not catalog or not code:
        return None
    for row in catalog:
        prefix = row.get("okpd2_prefix") or ""
        if prefix and code.startswith(prefix):
            return row
    return None


def _eaeu(country: str) -> bool:
    folded = _fold(country)
    return any(token in folded for token in EAEU)


def _tz_match(item: dict[str, Any], tz_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    number = str(item.get("no") or "")
    for tz_item in tz_items:
        if number and str(tz_item.get("no") or "") == number:
            return tz_item
    return None


def _finding(text: str, source: str, severity: str) -> dict[str, str]:
    return {"code": "3", "text": text, "source": source, "severity": severity}


def _fold(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def _first_source(records: list[dict[str, Any]]) -> str:
    for record in records:
        if record.get("source_file"):
            return _present(record.get("source_file"))
    return "источник отсутствует"


def _present(value: Any) -> str:
    text = str(value or "").strip()
    return text or "источник отсутствует"
