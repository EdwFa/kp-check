from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from kp_tz_check.checks import summarize
from kp_tz_check.dates import format_date
from kp_tz_check.models import FinalStatus, PairResult


def write_html_report(results: list[PairResult], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_html(results), encoding="utf-8")
    return dest


def render_html(results: list[PairResult]) -> str:
    summary = summarize(results)
    rows = "\n".join(_row(index, item) for index, item in enumerate(results, start=1))
    diffs = "".join(f"<li>{html.escape(item)}</li>" for item in summary["differences"]) or "<li>Расхождений нет</li>"
    no_kp = "".join(f"<li>{html.escape(item)}</li>" for item in summary["requests_without_kp"])
    no_req = "".join(f"<li>{html.escape(item)}</li>" for item in summary["kps_without_request"])
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
    <p>Полностью соответствующих пар: <b>{summary["matched_pairs"]}</b></p>
    <h3>Расхождения</h3>
    <ul>{diffs}</ul>
    {"<h3>Запросы без КП</h3><ul>" + no_kp + "</ul>" if no_kp else ""}
    {"<h3>КП без запроса</h3><ul>" + no_req + "</ul>" if no_req else ""}
  </section>
</main>
</body>
</html>
"""


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
