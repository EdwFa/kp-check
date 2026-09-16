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
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        render_html(
            results,
            compliance_log=compliance_log,
            hitl_log=hitl_log,
        ),
        encoding="utf-8",
    )
    return dest


def render_html(
    results: list[PairResult],
    *,
    compliance_log: list[dict] | None = None,
    hitl_log: list[dict] | None = None,
) -> str:
    summary = summarize(results)
    rows = "\n".join(_row(index, item) for index, item in enumerate(results, start=1))
    diffs = "".join(f"<li>{html.escape(item)}</li>" for item in summary["differences"]) or "<li>Расхождений нет</li>"
    no_kp = "".join(f"<li>{html.escape(item)}</li>" for item in summary["requests_without_kp"])
    no_req = "".join(f"<li>{html.escape(item)}</li>" for item in summary["kps_without_request"])
    evidence = _compliance_html(compliance_log or [])
    decisions = _hitl_html(hitl_log or [])
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
  {decisions}
</main>
</body>
</html>
"""


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
