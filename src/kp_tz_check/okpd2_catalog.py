"""Локальный справочник ОКПД2. Без файла признак СМП не выводится."""

from __future__ import annotations

import csv
import os
from pathlib import Path

REQUIRED_COLUMNS = ("code", "official_name", "smp")


class CatalogConfigError(ValueError):
    """Файл справочника не содержит обязательных колонок или значений."""


def load_okpd2_catalog(path: str | Path | None = None) -> list[dict[str, str]] | None:
    """Загрузить CSV. Нет пути и нет KP_OKPD2_CATALOG — справочник не загружен."""
    if path is None:
        raw = os.environ.get("KP_OKPD2_CATALOG")
        if not raw:
            return None
        path = Path(raw)
    file_path = Path(path)
    if not file_path.is_file():
        raise CatalogConfigError(f"Справочник ОКПД2 не найден: {file_path}")
    with file_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [name.strip() for name in (reader.fieldnames or [])]
        missing = [name for name in REQUIRED_COLUMNS if name not in fieldnames]
        if missing:
            raise CatalogConfigError(
                "Справочник ОКПД2 без колонок: " + ", ".join(missing)
            )
        rows: list[dict[str, str]] = []
        for raw_row in reader:
            row = {key.strip(): (value or "").strip() for key, value in raw_row.items() if key}
            if not row.get("code"):
                continue
            smp = row.get("smp", "").lower()
            if smp not in {"yes", "no"}:
                raise CatalogConfigError(f"Колонка smp должна быть yes или no, получено «{row.get('smp')}».")
            rows.append({"code": row["code"], "official_name": row["official_name"], "smp": smp})
    return rows


def row_is_smp(row: dict[str, str] | None) -> bool:
    """СМП считается только при явном smp=yes."""
    return bool(row) and row.get("smp") == "yes"
