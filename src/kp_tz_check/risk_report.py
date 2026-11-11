"""Отчёт о соответствии и рисках. Сеть вызывается только переданным клиентом поиска."""

from __future__ import annotations

import html

from kp_tz_check.characteristic_search import (
    EXTRACTED_NONE,
    PENDING,
    QUERY_EMPTY,
    REGISTRY,
    REGISTRY_NOTE,
    SEARCH_INCOMPLETE,
    build_characteristic_query,
    describe_pages,
)
from kp_tz_check.contract_check import (
    CRITICAL,
    INSUFFICIENT,
    MAJOR,
    MATCH,
    MINOR,
    NO_SPEC,
    check_specification,
)


UNCHECKED = "не проверен"
NOT_FOUND = "не выявлено"


def parse_param_lines(text: str) -> list[dict]:
    rows = []
    for raw in (text or "").splitlines():
        parts = [part.strip() for part in raw.split("|")]
        if not parts or not parts[0]:
            continue
        rows.append(
            {
                "name": parts[0],
                "value": parts[1] if len(parts) > 1 else "",
                "unit": parts[2] if len(parts) > 2 else "",
                "required": True,
                "from_table": False,
            }
        )
    return rows


LOCAL_SPEC = "локальная спецификация, интернет не использовался"
ACCEPTED = "принято оператором"


def build_risk_report(
    requirements: list[dict] | None,
    offer: list[dict] | None,
    *,
    legal: str | None = None,
    financial: str | None = None,
    reputation: str | None = None,
    lookup=None,
    query: dict | None = None,
    allowlist: list[dict] | None = None,
    accepted: list[dict] | None = None,
    resources: list[dict] | None = None,
) -> dict:
    risks = (legal, financial, reputation)
    if offer is not None:
        return _pack(
            check_specification(requirements, offer),
            _sources(LOCAL_SPEC, [], False),
            risks,
        )
    if accepted:
        rows = [_accepted_row(item) for item in accepted]
        return _pack(
            check_specification(requirements, rows),
            _sources(ACCEPTED, list(resources or []), True),
            risks,
        )
    if lookup is None:
        return _pack(
            check_specification(requirements, None),
            _sources(NO_SPEC, [], False),
            risks,
        )
    built = build_characteristic_query(query)
    if not built["ready"]:
        report = _unchecked(QUERY_EMPTY, risks, internet_search=False)
        report["query"] = built["query"]
        return report
    found = lookup.lookup(built["query"])
    if not found.get("internet_search"):
        report = _pack(
            check_specification(requirements, None),
            _sources(NO_SPEC, [], False),
            risks,
        )
        report["query"] = built["query"]
        return report
    described = describe_pages(found.get("pages") or [], allowlist)
    status = described["status"]
    if found.get("status") == SEARCH_INCOMPLETE:
        status = SEARCH_INCOMPLETE
    report = _unchecked(status, risks, internet_search=True)
    report["sources"]["resources"] = described["resources"]
    report["candidates"] = described["candidates"]
    report["query"] = built["query"]
    return report


def render_risk_html(report: dict) -> str:
    specification = report["specification"]
    percent = report["percent"]
    percent_text = "процент не считается" if percent is None else f"{percent}%"
    rows = []
    for row in specification["rows"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['name']))}</td>"
            f"<td>{html.escape(str(row['class']))}</td>"
            f"<td>{html.escape(str(row['text']))}</td>"
            f"<td>{html.escape(str(row['confidence']))}</td>"
            "</tr>"
        )
    risks = []
    for risk in report["risks"]:
        risks.append(
            "<li>"
            f"{html.escape(risk['kind'])}: {html.escape(risk['status'])}, "
            f"вероятность {html.escape(risk['probability'])}"
            "</li>"
        )
    body = "".join(rows) or "<tr><td colspan='4'>Строк сравнения нет.</td></tr>"
    candidates = []
    for candidate in report.get("candidates") or []:
        candidates.append(
            "<li>"
            f"{html.escape(str(candidate.get('name') or ''))}: "
            f"{html.escape(str(candidate.get('note') or ''))}"
            "</li>"
        )
    resource_lines = []
    registry = False
    for resource in report["sources"].get("resources") or []:
        if resource.get("source_class") == REGISTRY:
            registry = True
        resource_lines.append(
            "<li>"
            f"{html.escape(str(resource.get('url') or ''))} — "
            f"{html.escape(str(resource.get('source_class') or ''))} — "
            f"{html.escape(str(resource.get('checked_at') or ''))}"
            "</li>"
        )
    if resource_lines:
        sources = f"<ul>{''.join(resource_lines)}</ul>"
        if registry:
            sources += f"<p>{html.escape(REGISTRY_NOTE)}</p>"
    else:
        sources = "<p>Проверенных интернет-ресурсов нет.</p>"
    return (
        "<section><h2>Соответствие и риски</h2>"
        f"<p>Соответствие: {html.escape(percent_text)}. "
        f"Статус: {html.escape(str(specification['status']))}. "
        f"Уверенность: {html.escape(str(specification.get('confidence') or UNCHECKED))}.</p>"
        "<table><tr><th>Параметр</th><th>Класс</th><th>Текст</th><th>Уверенность</th></tr>"
        f"{body}</table><ul>{''.join(risks)}</ul>"
        f"<p>{html.escape(report['sources']['status'])}.</p>"
        f"{sources}<ul>{''.join(candidates)}</ul>"
        "</section>"
    )


def _technical(specification: dict) -> dict:
    status = specification["status"]
    if status in {NO_SPEC, INSUFFICIENT}:
        probability = UNCHECKED
    elif status == CRITICAL:
        probability = "высокая"
    elif status == MAJOR:
        probability = "средняя"
    elif status == MINOR:
        probability = "низкая"
    elif status == MATCH:
        probability = "низкая"
        status = NOT_FOUND
    else:
        probability = UNCHECKED
    return {"kind": "технический", "status": status, "probability": probability}


def _open_risk(kind: str, status: str | None) -> dict:
    if not status:
        return {"kind": kind, "status": UNCHECKED, "probability": UNCHECKED}
    return {"kind": kind, "status": status, "probability": UNCHECKED}


def _pack(specification: dict, sources: dict, risks: tuple) -> dict:
    legal, financial, reputation = risks
    share = specification["share"]
    return {
        "specification": specification,
        "percent": None if share is None else int(round(share * 100)),
        "risks": [
            _technical(specification),
            _open_risk("правовой", legal),
            _open_risk("финансовый", financial),
            _open_risk("репутационный", reputation),
        ],
        "sources": sources,
        "candidates": [],
        "query": {},
    }


def _unchecked(status: str, risks: tuple, *, internet_search: bool) -> dict:
    specification = {
        "status": UNCHECKED,
        "share": None,
        "confidence": None,
        "rows": [],
        "internet_search": internet_search,
    }
    report = _pack(specification, _sources(status, [], internet_search), risks)
    if status in {PENDING, EXTRACTED_NONE, QUERY_EMPTY, SEARCH_INCOMPLETE}:
        report["risks"][0] = {"kind": "технический", "status": UNCHECKED, "probability": UNCHECKED}
    return report


def _sources(status: str, resources: list[dict], internet_search: bool) -> dict:
    return {
        "status": status,
        "resources": resources,
        "checked_at": "",
        "internet_search": internet_search,
    }


def _accepted_row(item: dict) -> dict:
    return {
        "name": item.get("name") or "",
        "value": item.get("value") or "",
        "unit": item.get("unit") or "",
        "required": True,
        "from_table": False,
    }
