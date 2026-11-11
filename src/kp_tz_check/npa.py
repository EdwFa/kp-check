"""Извлечение упоминаний НПА. Локальный CSV не заменяет правовую базу."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import re


UNCHECKED = "Не проверен — требуется ручная сверка"
METHOD = "автоматическая проверка не выполнялась"
LOCAL_NOTE = "локальный перечень, не правовая база"
CATALOG_ENV = "KP_NPA_CATALOG"

_PATTERNS = (
    re.compile(r"ГОСТ\s+Р\s+[\d.\-]+", re.IGNORECASE),
    re.compile(r"ГОСТ\s+[\d.\-]+", re.IGNORECASE),
    re.compile(r"\d+\s*-\s*ФЗ"),
    re.compile(r"СП\s+[\d.\-]+", re.IGNORECASE),
    re.compile(r"СанПиН\s+[\d.\-]+", re.IGNORECASE),
    re.compile(r"постановление\s+Правительства(?:\s+РФ)?\s*№\s*\d+", re.IGNORECASE),
    re.compile(r"ТР\s+ЕАЭС\s+[\d/]+", re.IGNORECASE),
)


def load_npa_catalog(path: Path | str | None = None) -> list[dict[str, str]] | None:
    raw = path if path is not None else os.environ.get(CATALOG_ENV)
    if not raw:
        return None
    file = Path(raw)
    with file.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    catalog = []
    for row in rows:
        citation = (row.get("citation") or "").strip()
        if not citation:
            continue
        catalog.append(
            {
                "citation": citation,
                "status": (row.get("status") or "").strip(),
                "replaced_by": (row.get("replaced_by") or "").strip(),
            }
        )
    return catalog


def extract_npa(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _PATTERNS:
        for match in pattern.finditer(text or ""):
            citation = re.sub(r"\s+", " ", match.group(0)).strip()
            key = citation.casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append(citation)
    return found


def build_npa_report(
    tzs: list[dict] | None = None,
    applications: list[dict] | None = None,
    catalog: list[dict[str, str]] | None = None,
    *,
    load_catalog: bool = True,
) -> dict:
    if load_catalog:
        catalog = load_npa_catalog()
    by_citation = {(row.get("citation") or "").casefold(): row for row in catalog or []}
    rows = []
    for source, record in _documents(tzs, applications):
        for citation in extract_npa(_blob(record)):
            known = by_citation.get(citation.casefold())
            if known and known.get("status"):
                status = known["status"]
                note = LOCAL_NOTE
                if known.get("replaced_by"):
                    note = f"{LOCAL_NOTE}; заменён на {known['replaced_by']}"
            else:
                status = UNCHECKED
                note = METHOD
            if status.casefold() == "действует" and not known:
                status = UNCHECKED
            rows.append(
                {
                    "citation": citation,
                    "source": source,
                    "status": status,
                    "method": note,
                }
            )
    return {"rows": rows, "catalog_loaded": catalog is not None}


def _documents(tzs: list[dict] | None, applications: list[dict] | None) -> list[tuple[str, dict]]:
    documents = []
    for record in tzs or []:
        documents.append((str(record.get("source_file") or "ТЗ"), record))
    for record in applications or []:
        documents.append((str(record.get("source_file") or "Заявка"), record))
    return documents


def _blob(record: dict) -> str:
    parts = [str(record.get("body") or ""), str(record.get("title") or "")]
    for item in record.get("items") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("name") or ""))
            parts.append(str(item.get("specs") or ""))
    return "\n".join(parts)
