from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from kp_tz_check.checks import summarize
from kp_tz_check.dates import format_date
from kp_tz_check.models import FinalStatus, PairResult


def write_html_report(
    results: list[PairResult],
    dest: Path,
    compliance_log: list[dict] | None = None,
    hitl_log: list[dict] | None = None,
    calculations_log: list[dict] | None = None,
    conclusion: dict | None = None,
    baseline: dict | None = None,
    nmck_report: dict | None = None,
    application_math: dict | None = None,
    competition: dict | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        render_html(
            results,
            compliance_log=compliance_log,
            hitl_log=hitl_log,
            calculations_log=calculations_log,
            conclusion=conclusion,
            baseline=baseline,
            nmck_report=nmck_report,
            application_math=application_math,
            competition=competition,
        ),
        encoding="utf-8",
    )
    return dest


def render_html(
    results: list[PairResult],
    *,
    compliance_log: list[dict] | None = None,
    hitl_log: list[dict] | None = None,
    calculations_log: list[dict] | None = None,
    conclusion: dict | None = None,
    baseline: dict | None = None,
    nmck_report: dict | None = None,
    application_math: dict | None = None,
    competition: dict | None = None,
) -> str:
    summary = summarize(results)
    rows = "\n".join(_row(index, item) for index, item in enumerate(results, start=1))
    diffs = "".join(f"<li>{html.escape(item)}</li>" for item in summary["differences"]) or "<li>Расхождений нет</li>"
    no_kp = "".join(f"<li>{html.escape(item)}</li>" for item in summary["requests_without_kp"])
    no_req = "".join(f"<li>{html.escape(item)}</li>" for item in summary["kps_without_request"])
    evidence = _compliance_html(compliance_log or [])
    decisions = _hitl_html(hitl_log or [])
    calculations = _calculations_html(calculations_log or [])
    conclusion_html = _conclusion_html(conclusion, confirmed=_conclusion_confirmed(hitl_log or []))
    baseline_html = _baseline_html(baseline)
    nmck_html = _nmck_html(nmck_report)
    application_html = _application_html(application_math)
    competition_html = _competition_html(competition)
    status_counts = {
        FinalStatus.MATCH: sum(item.status == FinalStatus.MATCH for item in results),
        FinalStatus.NEEDS_REVIEW: sum(item.status == FinalStatus.NEEDS_REVIEW for item in results),
        FinalStatus.MISMATCH: sum(item.status == FinalStatus.MISMATCH for item in results),
    }
    generated = datetime.now().strftime("%d.%m.%Y %H:%M")
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Проверка комплекта запрос → КП → ТЗ</title>
  <style>
    :root {{
      --bg: #f6f4ef;
      --ink: #1f1c16;
      --muted: #5c574c;
      --line: #d9d2c5;
      --ok: #215c3a;
      --bad: #8a1f1f;
      --warn: #8a5a12;
      --card: #fffcf7;
    }}
    body {{
      margin: 0;
      font: 15px/1.45 "Segoe UI", "PT Sans", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 32px 24px 64px; }}
    h1 {{ font-size: 24px; font-weight: 650; margin: 0 0 8px; }}
    .meta {{ color: var(--muted); margin-bottom: 24px; }}
    .stats {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 28px; }}
    .stat {{ background: var(--card); border: 1px solid var(--line); padding: 12px 16px; min-width: 160px; }}
    .stat b {{ display: block; font-size: 22px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 24px 0; }}
    .summary-card {{ background: var(--card); border: 1px solid var(--line); padding: 16px; }}
    .summary-card b {{ display: block; font-size: 24px; margin-bottom: 4px; }}
    .summary-card.ok {{ border-left: 5px solid var(--ok); }}
    .summary-card.warn {{ border-left: 5px solid var(--warn); }}
    .summary-card.bad {{ border-left: 5px solid var(--bad); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--card); }}
    th, td {{ border: 1px solid var(--line); padding: 10px 12px; vertical-align: top; text-align: left; }}
    th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }}
    .ok {{ color: var(--ok); font-weight: 600; }}
    .bad {{ color: var(--bad); font-weight: 600; }}
    .warn {{ color: var(--warn); font-weight: 600; }}
    .muted {{ color: var(--muted); font-weight: 600; }}
    ul {{ margin: 8px 0 0 18px; padding: 0; }}
    section {{ margin-top: 28px; }}
  </style>
</head>
<body>
<main>
  <h1>Проверка комплекта документов</h1>
  <p class="meta">Запрос → коммерческое предложение → техническое задание · сформировано {html.escape(generated)}</p>
  <div class="stats">
    <div class="stat"><b>{summary["matched_pairs"]}</b>полностью соответствуют</div>
    <div class="stat"><b>{summary["total_rows"]}</b>строк в таблице</div>
    <div class="stat"><b>{len(summary["requests_without_kp"])}</b>запросов без КП</div>
    <div class="stat"><b>{len(summary["kps_without_request"])}</b>КП без запроса</div>
  </div>
  {conclusion_html}
  {baseline_html}
  {competition_html}
  <table>
    <thead>
      <tr>
        <th>№</th>
        <th>Запрос (дата отправки)</th>
        <th>КП (дата подготовки)</th>
        <th>КП (дата регистрации, из файла)</th>
        <th>Проверка дат</th>
        <th>Соответствие товара ТЗ</th>
        <th>Итоговый статус</th>
        <th>Комментарий</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  <section>
    <h2>Резюме</h2>
    <div class="summary-grid">
      <div class="summary-card ok"><b>{status_counts[FinalStatus.MATCH]}</b>Соответствует</div>
      <div class="summary-card warn"><b>{status_counts[FinalStatus.NEEDS_REVIEW]}</b>Требует уточнения</div>
      <div class="summary-card bad"><b>{status_counts[FinalStatus.MISMATCH]}</b>Не соответствует</div>
    </div>
    <p><b>Итог:</b> {summary["matched_pairs"]} из {summary["total_rows"]} строк полностью соответствуют.</p>
    <h3>Расхождения</h3>
    <ul>{diffs}</ul>
    {"<h3>Запросы без КП</h3><ul>" + no_kp + "</ul>" if no_kp else ""}
    {"<h3>КП без запроса</h3><ul>" + no_req + "</ul>" if no_req else ""}
  </section>
  {evidence}
  {nmck_html}
  {application_html}
  {calculations}
  {decisions}
</main>
</body>
</html>
"""


def _conclusion_confirmed(log: list[dict]) -> bool:
    return any(item.get("kind") == "conclusion" for item in log)


def _conclusion_html(conclusion: dict | None, *, confirmed: bool = False) -> str:
    blocks = (conclusion or {}).get("blocks") or []
    if not blocks:
        return "<section><h2>Сводное заключение</h2><p>Сводка не построена.</p></section>"
    rows = []
    for block in blocks:
        block_id = str(block.get("block_id") or "")
        status = str(block.get("status") or "—")
        rows.append(
            "<tr data-block=\""
            + html.escape(block_id, quote=True)
            + "\">"
            f"<td>{html.escape(block_id)}</td>"
            f"<td>{html.escape(str(block.get('title') or '—'))}</td>"
            f"<td class=\"{_block_status_class(status)}\">{html.escape(status)}</td>"
            f"<td>{html.escape(str(block.get('reason') or '—'))}</td>"
            "</tr>"
        )
    verdict = html.escape(str((conclusion or {}).get("verdict") or "—"))
    reason = html.escape(str((conclusion or {}).get("verdict_reason") or "—"))
    risks = _text_items((conclusion or {}).get("critical_risks") or [], "Критических рисков в сводке нет.")
    clarifications = _text_items(
        [
            (
                f"{item.get('text')} — {item.get('owner')}"
                if isinstance(item, dict) and item.get("owner")
                else (item.get("text") if isinstance(item, dict) else item)
            )
            for item in (conclusion or {}).get("clarifications") or []
        ],
        "Пунктов, требующих уточнения, нет.",
    )
    linked = _text_items(
        [
            item.get("text") if isinstance(item, dict) else item
            for item in (conclusion or {}).get("linked_risks") or []
        ],
        "Связанных рисков нет.",
    )
    confirmation = (
        "Заключение подтверждено оператором."
        if confirmed
        else "Заключение не подтверждено оператором."
    )
    return (
        "<section><h2>Сводное заключение</h2>"
        f"<p><b>Итог:</b> {verdict}</p>"
        f"<p>{reason}</p>"
        f"<p>{html.escape(confirmation)}</p>"
        "<table><thead><tr><th>Блок</th><th>Проверка</th><th>Статус</th><th>Комментарий</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "<h3>Связанные риски</h3>"
        f"<ul>{linked}</ul>"
        "<h3>Критические риски</h3>"
        f"<ul>{risks}</ul>"
        "<h3>Требует уточнения</h3>"
        f"<ul>{clarifications}</ul></section>"
    )


def _baseline_html(baseline: dict | None) -> str:
    if baseline is None:
        return ""
    return (
        "<section><h2>Сверка базовых документов</h2>"
        "<h3>Шаг 2.1. ТЗ, заявка и запрос</h3>"
        + _baseline_step_table(baseline.get("rows") or [])
        + "<h3>Шаг 2.2. КП и источник требования</h3>"
        + _offer_step_table(baseline.get("offer_rows") or [])
        + "</section>"
    )


def _baseline_step_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        sources = {
            str(source.get("document")): _source_verbatim(source)
            for source in row.get("sources") or []
            if isinstance(source, dict)
        }
        status = str(row.get("status") or "—")
        body.append(
            "<tr>"
            f"<td class=\"{_baseline_status_class(status)}\">{html.escape(status)}</td>"
            f"<td>{html.escape(sources.get('ТЗ', '—'))}</td>"
            f"<td>{html.escape(sources.get('Заявка', '—'))}</td>"
            f"<td>{html.escape(sources.get('Запрос', '—'))}</td>"
            f"<td>{html.escape(str(row.get('note') or '—'))}</td>"
            "</tr>"
        )
    if not body:
        body.append("<tr><td colspan=\"5\">Строк сверки нет.</td></tr>")
    return (
        "<table><thead><tr><th>Статус</th><th>ТЗ</th><th>Заявка</th><th>Запрос</th><th>Замечание</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _offer_step_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        status = str(row.get("status") or "—")
        body.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('position_no') or '—'))}</td>"
            f"<td>{html.escape(str(row.get('position_name') or '—'))}</td>"
            f"<td>{html.escape(str(row.get('supplier') or '—'))}</td>"
            f"<td>{html.escape(str(row.get('requirement_source') or '—'))}</td>"
            f"<td class=\"{_baseline_status_class(status)}\">{html.escape(status)}</td>"
            f"<td>{html.escape(str(row.get('requirement_text') or '—'))}</td>"
            f"<td>{html.escape(str(row.get('offer_text') or '—'))}</td>"
            "</tr>"
        )
    if not body:
        body.append("<tr><td colspan=\"7\">Строк сравнения с КП нет.</td></tr>")
    return (
        "<table><thead><tr><th>№</th><th>Позиция</th><th>Поставщик</th><th>Источник требования</th>"
        "<th>Статус</th><th>Требование</th><th>КП</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _source_verbatim(source: dict) -> str:
    return " | ".join(
        str(source.get(key) or "") for key in ("name", "specs", "unit", "qty")
    )


def _baseline_status_class(status: str) -> str:
    if status in {"Полностью согласовано", "Соответствует"}:
        return "ok"
    if status in {"Не соответствует", "Нет базового требования"}:
        return "bad"
    if status in {"Расхождение между базовыми документами", "Отсутствует в одном из документов"}:
        return "warn"
    return "muted"


def _text_items(items: list, empty: str) -> str:
    texts = [str(item).strip() for item in items if item is not None and str(item).strip()]
    if not texts:
        return f"<li>{html.escape(empty)}</li>"
    return "".join(f"<li>{html.escape(text)}</li>" for text in texts)


def _block_status_class(status: str) -> str:
    if status == "Проверен, замечаний нет":
        return "ok"
    if status == "Проверен, критичные ошибки":
        return "bad"
    if status == "Проверен, есть замечания":
        return "warn"
    return "muted"


def _competition_html(report: dict | None) -> str:
    if not report:
        return ""
    rows = []
    for row in report.get("rows") or []:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('position') or '—'))}</td>"
            f"<td>{html.escape(str(row.get('manufacturer_count') if row.get('manufacturer_count') is not None else '—'))}</td>"
            f"<td>{html.escape(str(row.get('manufacturers') or '—'))}</td>"
            f"<td>{html.escape(str(row.get('countries') or '—'))}</td>"
            f"<td>{html.escape(str(row.get('measure') or '—'))}</td>"
            f"<td>{html.escape(str(row.get('status') or '—'))}</td>"
            "</tr>"
        )
    body = "".join(rows) or "<tr><td colspan=\"6\">Позиций КП нет.</td></tr>"
    notes = "".join(f"<li>{html.escape(item.get('text') or '')}</li>" for item in report.get("findings") or [])
    return (
        "<section><h2>Блок 3. Производители и нацрежим</h2>"
        "<table><thead><tr><th>Позиция</th><th>Производителей</th><th>Названия</th>"
        "<th>Страны</th><th>Мера</th><th>Статус</th></tr></thead>"
        f"<tbody>{body}</tbody></table><ul>{notes}</ul></section>"
    )


def _nmck_html(report: dict | None) -> str:
    if not report:
        return ""
    note = report.get("justification_note") or "Сверка с файлом обоснования выполнена."
    rows = []
    for row in report.get("rows") or []:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('position') or '—'))}</td>"
            f"<td>{html.escape(_num(row.get('mean')))}</td>"
            f"<td>{html.escape(_num(row.get('alternate_mean')))}</td>"
            f"<td>{html.escape(_num(row.get('coefficient')))}</td>"
            f"<td>{html.escape(str(row.get('status') or '—'))}</td>"
            f"<td>{html.escape(_num(row.get('unit_nmck')))}</td>"
            f"<td>{html.escape(str(row.get('quantity') if row.get('quantity') is not None else row.get('quantity_status') or '—'))}</td>"
            "</tr>"
        )
    body = "".join(rows) or "<tr><td colspan=\"7\">Пересчёт по КП не дал строк.</td></tr>"
    diffs = "".join(f"<li>{html.escape(item.get('text') or '')}</li>" for item in report.get("justification_diffs") or [])
    flags = "".join(
        f"<li>{html.escape(item.get('text') or '')}</li>"
        for row in report.get("rows") or []
        for item in row.get("antidumping") or []
    )
    return (
        "<section><h2>Расчёт НМЦК</h2>"
        f"<p>{html.escape(str(note))}</p>"
        "<table><thead><tr><th>Позиция</th><th>Среднее</th><th>Второй расчёт</th>"
        "<th>V</th><th>Статус</th><th>НМЦК за единицу</th><th>Количество</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
        "<h3>Расхождения с обоснованием</h3>"
        f"<ul>{diffs or '<li>Нет</li>'}</ul>"
        "<h3>Антидемпинг</h3>"
        f"<ul>{flags or '<li>Нет</li>'}</ul></section>"
    )


def _application_html(report: dict | None) -> str:
    reports = (report or {}).get("reports") or []
    if report is None:
        return ""
    if not reports:
        return "<section><h2>Арифметика заявки</h2><p>Заявка не загружена. Арифметика КП — отдельная секция.</p></section>"
    rows = []
    for item in reports:
        for line in item.get("lines") or []:
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(line.get('position') or '—'))}</td>"
                f"<td>{html.escape(str(line.get('status') or '—'))}</td>"
                f"<td>{html.escape(_num(line.get('net')))}</td>"
                f"<td>{html.escape(_num(line.get('vat_amount')))}</td>"
                f"<td>{html.escape(str(line.get('note') or '—'))}</td>"
                "</tr>"
            )
    body = "".join(rows) or "<tr><td colspan=\"5\">Строк заявки нет.</td></tr>"
    return (
        "<section><h2>Арифметика заявки</h2>"
        "<table><thead><tr><th>Позиция</th><th>Статус</th><th>Сумма</th><th>НДС</th><th>Комментарий</th></tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _num(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}"
    return "—" if value is None else str(value)


def _calculations_html(log: list[dict]) -> str:
    if not log:
        return ""
    rows = []
    for item in log:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('supplier', '—')))}</td>"
            f"<td>{html.escape(Path(str(item.get('source_file', '—'))).name)}</td>"
            f"<td>{html.escape(str(item.get('total', '—')))}</td>"
            f"<td>{html.escape(str(item.get('declared_total', 'не найден')))}</td>"
            f"<td>{html.escape(str(item.get('difference', '—')))}</td>"
            f"<td>{html.escape(str(item.get('arithmetic_status', '—')).upper())}</td>"
            f"<td>{html.escape(str(item.get('arithmetic_reason') or '—'))}</td>"
            "</tr>"
        )
    return (
        "<section><h2>Арифметика КП</h2>"
        "<table><thead><tr><th>Поставщик</th><th>Файл</th>"
        "<th>Расчётный итог</th><th>Итог в КП</th><th>Расхождение</th>"
        "<th>Статус</th><th>Комментарий</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        "<p class='meta'>Итог КП = Σ (количество × цена за единицу).</p></section>"
    )


def _compliance_html(log: list[dict]) -> str:
    if not log:
        return ""
    rows = []
    for entry in log:
        evidence = entry.get("evidence") or {}
        source = entry.get("source") or entry.get("source", "—")
        detail = _evidence_html(evidence, entry)
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(entry.get('concept_id', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('status', evidence.get('status', '—'))))}</td>"
            f"<td>{html.escape(str(source))}</td>"
            f"<td>{detail}</td>"
            "</tr>"
        )
    return (
        "<section><h2>Доказательства compliance</h2>"
        "<table><thead><tr><th>Концепция</th><th>Результат</th>"
        "<th>Источник</th><th>Расчёт и evidence</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></section>"
    )


def _evidence_html(evidence: dict, entry: dict) -> str:
    parts: list[str] = []
    if entry.get("span"):
        parts.append(f"<p><b>Цитата:</b> «{html.escape(str(entry['span']))}»</p>")
    groups = evidence.get("groups")
    if groups:
        rows = []
        for name, group in groups.items():
            suppliers = (group.get("suppliers") or {}).get("supplier_count", "—")
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(name))}</td>"
                f"<td>{html.escape(', '.join(f'{value:,.2f}' for value in group.get('values', [])))}</td>"
                f"<td>{html.escape(str(group.get('mean', '—')))}</td>"
                f"<td>{html.escape(str(group.get('coefficient_of_variation', '—')))}</td>"
                f"<td>{html.escape(str(suppliers))}</td>"
                f"<td>{html.escape(str(group.get('status', '—')))}</td>"
                f"<td>{html.escape(str(group.get('reason') or '—'))}</td>"
                "</tr>"
            )
        parts.append(
            "<table><thead><tr><th>Позиция</th><th>Цены</th><th>Средняя</th>"
            "<th>CV, %</th><th>Поставщики</th><th>Результат</th><th>Комментарий</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )
        parts.append("<p class='meta'>Формула: V = σ / средняя цена × 100%; неоднородность при CV &gt; 33%.</p>")
    elif evidence.get("check"):
        check = evidence["check"]
        parts.append(
            "<dl>"
            f"<dt>Оператор</dt><dd>{html.escape(str(check.get('operator', '—')))}</dd>"
            f"<dt>Порог ТЗ</dt><dd>{html.escape(str(check.get('threshold', '—')))}</dd>"
            f"<dt>Значение КП</dt><dd>{html.escape(str(check.get('actual', 'не найдено')))}</dd>"
            "</dl>"
        )
    return "".join(parts) or "—"


def _hitl_html(log: list[dict]) -> str:
    if not log:
        return ""
    rows = []
    for entry in log:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(entry.get('result_index', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('action', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('reviewer', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('reason', entry.get('error', '—'))))}</td>"
            f"<td>{'принято' if entry.get('accepted') else 'отклонено'}</td>"
            "</tr>"
        )
    return (
        "<section><h2>Журнал решений оператора</h2>"
        "<table><thead><tr><th>Строка</th><th>Действие</th><th>Оператор</th>"
        "<th>Причина</th><th>Результат</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></section>"
    )


def _row(index: int, item: PairResult) -> str:
    status_class = {
        FinalStatus.MATCH: "ok",
        FinalStatus.NEEDS_REVIEW: "warn",
        FinalStatus.MISMATCH: "bad",
    }[item.status]
    comments = "<br>".join(html.escape(comment) for comment in item.comments) or "—"
    prep = format_date(item.kp.prepared_on, item.kp.prepared_on_raw) if item.kp else "—"
    reg = format_date(item.kp.registered_on, item.kp.registered_on_raw) if item.kp else "—"
    sent = item.request_label if item.request else "—"
    kp_file = f"<div class='meta'>{html.escape(item.kp.source_file.name)}</div>" if item.kp else ""
    return f"""
      <tr>
        <td>{index}</td>
        <td>{html.escape(sent)}</td>
        <td>{html.escape(prep)}{kp_file}</td>
        <td>{html.escape(reg)}</td>
        <td>{html.escape(item.date_mark.value)}</td>
        <td>{html.escape(item.product_mark.value)}</td>
        <td class="{status_class}">{html.escape(item.status.value)}</td>
        <td>{comments}</td>
      </tr>
    """


def table_rows(results: list[PairResult]) -> list[dict[str, str]]:
    rows = []
    for index, item in enumerate(results, start=1):
        prep = format_date(item.kp.prepared_on, item.kp.prepared_on_raw) if item.kp else "—"
        reg = format_date(item.kp.registered_on, item.kp.registered_on_raw) if item.kp else "—"
        rows.append(
            {
                "№": str(index),
                "Запрос (дата отправки)": item.request_label if item.request else "—",
                "КП (дата подготовки)": prep,
                "Файл КП": item.kp.source_file.name if item.kp else "—",
                "КП (дата регистрации)": reg,
                "Проверка дат": item.date_mark.value,
                "Соответствие товара ТЗ": item.product_mark.value,
                "Итоговый статус": item.status.value,
                "Комментарий": " ".join(f"• {comment}" for comment in item.comments) or "—",
            }
        )
    return rows


def render_text(results: list[PairResult]) -> str:
    summary = summarize(results)
    lines = [
        "Проверка комплекта запрос → КП → ТЗ",
        f"Соответствует: {summary['matched_pairs']} из {summary['total_rows']}",
        "",
        f"{'№':<4}{'Запрос':<42}{'Подготовка КП':<16}{'Регистрация КП':<18}{'Даты':<24}{'ТЗ↔КП':<24}{'Статус'}",
    ]
    for index, item in enumerate(results, start=1):
        sent = item.request_label if item.request else "—"
        prep = format_date(item.kp.prepared_on, item.kp.prepared_on_raw) if item.kp else "—"
        reg = format_date(item.kp.registered_on, item.kp.registered_on_raw) if item.kp else "—"
        lines.append(
            f"{index:<4}{sent[:40]:<42}{prep:<16}{reg:<18}{item.date_mark.value:<24}{item.product_mark.value:<24}{item.status.value}"
        )
        for comment in item.comments:
            lines.append(f"     - {comment}")
    if summary["requests_without_kp"]:
        lines.append("\nЗапросы без КП:")
        lines.extend(f"  - {item}" for item in summary["requests_without_kp"])
    if summary["kps_without_request"]:
        lines.append("\nКП без запроса:")
        lines.extend(f"  - {item}" for item in summary["kps_without_request"])
    return "\n".join(lines)
