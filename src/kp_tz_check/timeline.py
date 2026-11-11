"""Временная шкала и контроль календарных событий комплекта."""

from __future__ import annotations

import re
from datetime import date, timedelta

from kp_tz_check.models import PairResult

VALIDITY_RE = re.compile(
    r"срок действия[^\n]{0,80}?(\d+)\s*"
    r"(день|дня|дней|месяц|месяца|месяцев)",
    re.IGNORECASE,
)


def extract_validity_days(text: str) -> int | None:
    """Извлечь срок действия из текста КП в днях."""
    values: list[int] = []
    for number, unit in VALIDITY_RE.findall(text or ""):
        value = int(number)
        values.append(value * 30 if unit.lower().startswith("месяц") else value)
    return max(values) if values else None


def build_timeline(results: list[PairResult]) -> list[dict]:
    """Сформировать события и итоговый календарный статус по каждой паре."""
    timeline: list[dict] = []
    for index, item in enumerate(results, start=1):
        request = item.request
        kp = item.kp
        events: list[dict] = []
        if request and request.sent_on:
            events.append(
                {
                    "event": "Отправка запроса",
                    "date": request.sent_on,
                    "source": request.source_file.name,
                }
            )
        if kp and kp.prepared_on:
            events.append(
                {
                    "event": "Подготовка КП",
                    "date": kp.prepared_on,
                    "source": kp.source_file.name,
                }
            )
        if kp and kp.registered_on:
            events.append(
                {
                    "event": "Регистрация КП",
                    "date": kp.registered_on,
                    "source": kp.source_file.name,
                }
            )

        validity_days = extract_validity_days(kp.body if kp else "")
        expiry = (
            kp.prepared_on + timedelta(days=validity_days)
            if kp and kp.prepared_on and validity_days
            else None
        )
        if expiry:
            events.append(
                {
                    "event": "Окончание срока действия КП",
                    "date": expiry,
                    "source": kp.source_file.name,
                }
            )

        dates = [event["date"] for event in events[:3]]
        chronology_ok = dates == sorted(dates) if dates else False
        if not request or not kp or not dates:
            status = "REVIEW"
            reason = "Недостаточно дат или пары документов."
        elif not chronology_ok:
            status = "FAIL"
            reason = "Нарушена хронология событий."
        elif validity_days is None:
            status = "REVIEW"
            reason = "Срок действия КП не найден."
        else:
            status = "PASS"
            reason = "Хронология и срок действия проверены."
        timeline.append(
            {
                "pair": index,
                "label": item.request_label,
                "status": status,
                "reason": reason,
                "validity_days": validity_days,
                "events": events,
            }
        )
    return timeline
