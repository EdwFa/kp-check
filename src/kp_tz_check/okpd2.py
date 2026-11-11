"""Локальная проверка кодов ОКПД2 без нормативных догадок."""

from __future__ import annotations

import re
from typing import Any

from kp_tz_check.okpd2_catalog import row_is_smp

OKPD2_RE = re.compile(
    r"(?<!\d)(\d{2}(?:\.\d{2}){1,2}(?:\.\d{3})?)(?!\d)",
    re.IGNORECASE,
)
OKPD2_LABEL_RE = re.compile(r"окпд\s*2?", re.IGNORECASE)


def extract_okpd2(text: str) -> list[str]:
    """Извлечь уникальные коды ОКПД2 из текста."""
    values: list[str] = []
    for match in OKPD2_RE.finditer(text or ""):
        code = match.group(1)
        window = (text or "")[max(0, match.start() - 32) : match.start()]
        if OKPD2_LABEL_RE.search(window):
            if code not in values:
                values.append(code)
    return values


def check_okpd2(
    requests: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Сверить коды ОКПД2 из запросов и ТЗ."""
    tz_codes: list[str] = []
    tz_sources: list[str] = []
    for tz in tzs:
        codes = extract_okpd2(tz.get("body", "") or tz.get("title", ""))
        tz_codes.extend(code for code in codes if code not in tz_codes)
        if codes:
            tz_sources.append(str(tz.get("source_file", "—")))

    results: list[dict[str, Any]] = []
    for request in requests:
        request_codes = extract_okpd2(request.get("body", ""))
        source = str(request.get("source_file", "—"))
        if not request_codes or not tz_codes:
            status = "REVIEW"
            reason = "Код ОКПД2 не найден в запросе или ТЗ."
        elif set(request_codes) == set(tz_codes):
            status = "PASS"
            reason = "Коды ОКПД2 совпадают."
        else:
            status = "FAIL"
            reason = "Коды ОКПД2 в запросе и ТЗ различаются."
        results.append(
            {
                "status": status,
                "request_file": source,
                "request_codes": request_codes,
                "tz_codes": tz_codes,
                "tz_sources": tz_sources,
                "reason": reason,
                "evidence": {
                    "request": request_codes,
                    "tz": tz_codes,
                    "source_request": source,
                    "source_tz": tz_sources,
                },
            }
        )
    return results


def validate_okpd2_code(code: str) -> bool:
    """Проверить синтаксическую форму кода, без проверки справочника."""
    return bool(OKPD2_RE.fullmatch(code.strip()))


def _distance(left: str, right: str) -> int:
    if abs(len(left) - len(right)) > 4:
        return 99
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def check_catalog_codes(
    positions: list[dict[str, Any]],
    catalog: list[dict[str, str]],
) -> dict[str, Any]:
    """Проверить коды позиций по справочнику, не подменяя исходный код."""
    by_code = {row["code"]: row for row in catalog}
    findings: list[dict[str, str]] = []
    smp_count = 0
    other_count = 0
    unknown = False
    for position in positions:
        code = str((position.get("extra") or {}).get("okpd2") or position.get("code") or "").strip()
        name = str(position.get("name") or "")
        source = str(position.get("source") or "позиция")
        if not code:
            continue
        if not validate_okpd2_code(code):
            findings.append({"text": f"Синтаксис кода «{code}» неверен. Исходный код не заменён.", "source": source})
            unknown = True
            continue
        row = by_code.get(code)
        if row is None:
            prefix_hits = [item for item in by_code if item.startswith(code) and len(item) > len(code)]
            if prefix_hits:
                findings.append(
                    {
                        "text": f"Код «{code}» неполный: в справочнике есть {prefix_hits[0]}. Исходный код не заменён.",
                        "source": source,
                    }
                )
            else:
                nearest = min(by_code, key=lambda item: _distance(code, item))
                distance = _distance(code, nearest)
                if distance <= 2:
                    findings.append(
                        {
                            "text": f"Опечатка: исходный код «{code}», близкий код «{nearest}». Исходный код не заменён.",
                            "source": source,
                        }
                    )
                else:
                    findings.append({"text": f"Код «{code}» отсутствует в справочнике.", "source": source})
            unknown = True
            continue
        if row_is_smp(row):
            smp_count += 1
        else:
            other_count += 1
        official = row.get("official_name") or ""
        if official and name and _fold(official) not in _fold(name) and _fold(name) not in _fold(official):
            findings.append(
                {
                    "text": f"Наименование «{name}» не совпало со справочным «{official}». Это замечание, не запрет закупки.",
                    "source": source,
                }
            )
    if unknown:
        smp_flag = None
    elif smp_count and not other_count:
        smp_flag = True
    elif other_count:
        smp_flag = False
    else:
        smp_flag = None
    return {
        "findings": findings,
        "smp_count": smp_count,
        "other_count": other_count,
        "smp": smp_flag,
        "summary": f"Позиций СМП: {smp_count}. Позиций не СМП: {other_count}.",
    }


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()

