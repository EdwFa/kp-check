"""Минимальные сроки процедуры. Не меняет статусы пар запрос—КП."""

from __future__ import annotations

import csv
from datetime import date, timedelta
import html
from pathlib import Path

from kp_tz_check.business_days import add_business_days, load_business_calendar


ROOT = Path(__file__).resolve().parents[2]
DEADLINES = ROOT / "data" / "procedures" / "deadlines.csv"
INSUFFICIENT = "недостаточно данных"
NOT_APPLICABLE = "не применяется"
READY = "рассчитано"

STAGE_NAMES = {
    "submission": "Подача заявок",
    "review": "Рассмотрение",
    "contract": "Заключение договора",
}
UNIT_LABELS = {
    "calendar_day": "календарных дней",
    "business_day": "рабочих дней",
    "none": "не применяется",
}


def load_deadlines(path: Path | str | None = None) -> list[dict[str, str]]:
    file = Path(path or DEADLINES)
    with file.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def calculate_procedure(
    procedure_type: str,
    decision: date,
    publication: date,
    *,
    deadlines: list[dict[str, str]] | None = None,
    calendar: dict | None = None,
    load_calendar: bool = True,
) -> dict:
    row = next(item for item in (deadlines or load_deadlines()) if item["type"] == procedure_type)
    if load_calendar and calendar is None:
        calendar = load_business_calendar()
    stages = {}
    anchor = publication
    for key in ("submission", "review", "contract"):
        stage, anchor = _stage(row, key, anchor, calendar)
        stages[key] = stage
    if all(item["status"] == NOT_APPLICABLE for item in stages.values()):
        status = NOT_APPLICABLE
    elif any(item["status"] == INSUFFICIENT for item in stages.values()):
        status = INSUFFICIENT
    else:
        status = READY
    return {
        "type": procedure_type,
        "decision": decision.isoformat(),
        "publication": publication.isoformat(),
        "status": status,
        "stages": stages,
    }


def apply_manual_date(minimum: date | None, chosen: date | None) -> dict:
    """Ручная дата сохраняется. Раньше минимума — предупреждение, без замены."""
    if chosen is None:
        return {"date": None, "warning": None}
    warning = None
    if minimum is not None and chosen < minimum:
        warning = (
            f"Дата {chosen.strftime('%d.%m.%Y')} раньше минимума "
            f"{minimum.strftime('%d.%m.%Y')}."
        )
    return {"date": chosen.isoformat(), "warning": warning}


def render_procedure_html(report: dict, manual: dict | None = None) -> str:
    manual = manual or {}
    rows = []
    bars = []
    publication = date.fromisoformat(report["publication"])
    for key, stage in report["stages"].items():
        minimum = stage.get("min") or "—"
        maximum = stage.get("max") or "—"
        chosen = (manual.get(key) or {}).get("date") or "—"
        warning = (manual.get(key) or {}).get("warning") or ""
        rows.append(
            "<tr>"
            f"<td>{html.escape(STAGE_NAMES[key])}</td>"
            f"<td>{html.escape(str(minimum))}</td>"
            f"<td>{html.escape(str(maximum))}</td>"
            f"<td>{html.escape(str(chosen))}</td>"
            f"<td>{html.escape(warning)}</td>"
            f"<td>{html.escape(stage.get('protocol') or '')}</td>"
            "</tr>"
        )
        bars.append(_bar(publication, stage, STAGE_NAMES[key]))
    return (
        "<section><h2>Календарь процедуры</h2>"
        f"<p>{html.escape(report['type'])}. Статус: {html.escape(report['status'])}.</p>"
        "<table><thead><tr><th>Этап</th><th>Минимум</th><th>Максимум</th>"
        "<th>Ручная дата</th><th>Предупреждение</th><th>Протокол</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<h3>Диаграмма</h3>{''.join(bars)}</section>"
    )


def _stage(row: dict[str, str], key: str, anchor: date | None, calendar: dict | None) -> tuple[dict, date | None]:
    unit = row[f"{key}_unit"] or "none"
    days_min = _number(row.get(f"{key}_min"))
    days_max = _number(row.get(f"{key}_max"))
    if unit == "none":
        return _empty(NOT_APPLICABLE, "Срок не назначается.", unit, days_min, days_max), None
    if anchor is None:
        return _empty(INSUFFICIENT, "Предыдущая дата не рассчитана.", unit, days_min, days_max), None
    if unit == "business_day" and calendar is None:
        return _empty(
            INSUFFICIENT,
            "недостаточно данных: производственный календарь не загружен. Дата не рассчитана.",
            unit,
            days_min,
            days_max,
        ), None
    minimum, counted_min = _add(anchor, days_min or 0, unit, calendar)
    maximum, counted_max = _add(anchor, days_max if days_max is not None else (days_min or 0), unit, calendar)
    prefix = "дата публикации" if key == "submission" else "дата предыдущего этапа"
    protocol = _protocol(prefix, days_min, days_max, unit, counted_max, days_min != days_max)
    return {
        "unit": unit,
        "days_min": days_min,
        "days_max": days_max,
        "min": minimum.isoformat(),
        "max": maximum.isoformat(),
        "counted": [item.isoformat() for item in counted_max],
        "protocol": protocol,
        "status": READY,
    }, minimum


def _add(start: date, count: int, unit: str, calendar: dict | None) -> tuple[date, list[date]]:
    if unit == "business_day":
        assert calendar is not None
        return add_business_days(start, count, calendar)
    counted = [start + timedelta(days=offset) for offset in range(1, count + 1)]
    return start + timedelta(days=count), counted


def _protocol(
    prefix: str,
    days_min: int | None,
    days_max: int | None,
    unit: str,
    counted_max: list[date],
    ranged: bool,
) -> str:
    label = UNIT_LABELS[unit]
    shown = ", ".join(item.strftime("%d.%m.%Y") for item in counted_max)
    if ranged:
        return (
            f"{prefix} + {days_min}–{days_max} {label}. "
            f"Минимум и максимум хранятся отдельно, одна дата не выбрана. "
            f"Сложены дни: {shown}."
        )
    return f"{prefix} + {days_min} {label}. Сложены дни: {shown}."


def _empty(status: str, protocol: str, unit: str, days_min: int | None, days_max: int | None) -> dict:
    return {
        "unit": unit,
        "days_min": days_min,
        "days_max": days_max,
        "min": None,
        "max": None,
        "counted": [],
        "protocol": protocol,
        "status": status,
    }


def _number(value: str | None) -> int | None:
    text = (value or "").strip()
    return int(text) if text else None


def _bar(publication: date, stage: dict, title: str) -> str:
    if not stage.get("min"):
        return f"<p>{html.escape(title)}: {html.escape(stage['status'])}</p>"
    start = date.fromisoformat(stage["min"])
    end = date.fromisoformat(stage["max"] or stage["min"])
    offset = max((start - publication).days, 0) * 8
    width = max((end - start).days, 1) * 8
    return (
        "<div style=\"margin:4px 0\">"
        f"<span>{html.escape(title)}</span>"
        f"<div style=\"margin-left:{offset}px;width:{width}px;height:14px;background:#3d5a40\"></div>"
        "</div>"
    )
