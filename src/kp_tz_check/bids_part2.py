"""Часть 2 заявки: форма 1 и сведения о товаре."""

from __future__ import annotations

import re

from kp_tz_check.bids import PART_CRITICAL, PART_OK, PART_REVIEW
from kp_tz_check.calculations import check_spec_constraint
from kp_tz_check.competition import REGIME_CRITICAL, _eaeu, _measure
from kp_tz_check.okpd2 import check_catalog_codes


_ROW_NUMBER = re.compile(r"(?:№|строка)\s*(\d+)", re.IGNORECASE)
_FIELD = re.compile(r"(производител\w*|страна|окпд2|срок годности)\s*[:\-]\s*([^|]+)", re.IGNORECASE)


def check_part2(
    text: str,
    tz_items: list[dict] | None = None,
    *,
    catalog: list[dict] | None = None,
    regime: list[dict] | None = None,
) -> dict:
    findings = _form_findings(text or "")
    rows = _product_rows(text or "")
    for row in rows:
        findings.extend(_row_findings(row, tz_items or [], catalog, regime))
    if rows and regime is None:
        findings.append("перечень № 1875 не загружен. Проверка запрета не выполняется.")
    critical = any(item.startswith("Ошибка") or REGIME_CRITICAL in item for item in findings)
    if critical:
        status = PART_CRITICAL
    elif findings:
        status = PART_REVIEW
    else:
        status = PART_OK
    return {"status": status, "findings": findings, "rows": rows}


def _form_findings(text: str) -> list[str]:
    folded = text.casefold()
    findings = []
    if "форма 1" not in folded and "форма № 1" not in folded:
        findings.append("Ошибка части 2: нет признаков формы 1.")
    if not ("1211" in folded and "223" in folded and "рнп" in folded):
        findings.append("Ошибка части 2: нет согласия на включение в РНП по постановлению № 1211 и ст. 5 223-ФЗ.")
    if not any(token in folded for token in ("эцп", "факсимиле", "бумажн")):
        findings.append("Ошибка части 2: нет признака подписи (ЭЦП, факсимиле или бумажный носитель).")
    return findings


def _product_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not _ROW_NUMBER.search(line):
            continue
        fields = {match.group(1).casefold(): match.group(2).strip() for match in _FIELD.finditer(line)}
        if not fields:
            continue
        number = _ROW_NUMBER.search(line).group(1)
        rows.append(
            {
                "no": number,
                "manufacturer": _pick(fields, "производител"),
                "country": fields.get("страна") or "",
                "okpd2": _pick(fields, "окпд2"),
                "shelf": _pick(fields, "срок годности"),
            }
        )
    return rows


def _row_findings(
    row: dict,
    tz_items: list[dict],
    catalog: list[dict] | None,
    regime: list[dict] | None,
) -> list[str]:
    number = row["no"]
    prefix = f"Строка {number}"
    findings = []
    tz_item = next((item for item in tz_items if str(item.get("no") or "") == number), None)
    if tz_item is not None:
        constraint = check_spec_constraint(str(tz_item.get("specs") or ""), row["shelf"])
        if constraint["status"] == "fail":
            findings.append(f"Ошибка. {prefix}: срок годности не соответствует порогу ТЗ.")
        tz_code = str((tz_item.get("extra") or {}).get("okpd2") or "").strip()
        if tz_code and row["okpd2"] and row["okpd2"] != tz_code:
            findings.append(
                f"Ошибка. {prefix}: код ОКПД2 «{row['okpd2']}» отличается от кода ТЗ «{tz_code}»."
            )
    if catalog is not None and row["okpd2"]:
        checked = check_catalog_codes(
            [{"no": number, "name": row["manufacturer"], "extra": {"okpd2": row["okpd2"]}, "source": prefix}],
            catalog,
        )
        findings.extend(f"{prefix}: {item['text']}" for item in checked["findings"])
    measure = _measure(row["okpd2"], regime)
    if measure and row["country"] and not _eaeu(row["country"]):
        findings.append(f"{REGIME_CRITICAL}. {prefix}, страна: {row['country']}.")
    return findings


def _pick(fields: dict[str, str], prefix: str) -> str:
    for key, value in fields.items():
        if key.startswith(prefix):
            return value
    return ""
