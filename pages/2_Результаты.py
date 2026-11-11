from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.report import render_html  # noqa: E402
from kp_tz_check.streamlit_pages import (  # noqa: E402
    configure_page,
    has_results,
    render_header,
)
from kp_tz_check.ui import _compliance_details, _pair_details, _results_table  # noqa: E402


def _missing_document_notes(baseline: dict | None) -> list[str]:
    notes: list[str] = []
    for row in (baseline or {}).get("rows") or []:
        note = str(row.get("note") or "").strip()
        if note and not row.get("sources"):
            notes.append(note)
    return notes


def _baseline_cell(row: dict, document: str) -> str:
    for source in row.get("sources") or []:
        if source.get("document") != document:
            continue
        return " | ".join(
            str(source.get(key) or "") for key in ("name", "specs", "unit", "qty")
        )
    return "—"


def _baseline_frames(baseline: dict | None) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    if not isinstance(baseline, dict):
        return None, None
    step_one = pd.DataFrame(
        [
            {
                "Статус": row.get("status") or "—",
                "ТЗ": _baseline_cell(row, "ТЗ"),
                "Заявка": _baseline_cell(row, "Заявка"),
                "Запрос": _baseline_cell(row, "Запрос"),
                "Замечание": row.get("note") or "—",
            }
            for row in baseline.get("rows") or []
        ]
    )
    step_two = pd.DataFrame(
        [
            {
                "№": row.get("position_no") or "—",
                "Позиция": row.get("position_name") or "—",
                "Поставщик": row.get("supplier") or "—",
                "Источник требования": row.get("requirement_source") or "—",
                "Статус": row.get("status") or "—",
                "Требование": row.get("requirement_text") or "—",
                "КП": row.get("offer_text") or "—",
            }
            for row in baseline.get("offer_rows") or []
        ]
    )
    return step_one, step_two


def _baseline_expanders(baseline: dict | None) -> None:
    step_one, step_two = _baseline_frames(baseline)
    with st.expander("Шаг 2.1. ТЗ, заявка и запрос", expanded=True):
        if step_one is None:
            st.info("Сверка не построена. Запустите проверку ещё раз.")
        else:
            for note in _missing_document_notes(baseline):
                st.warning(note)
            st.dataframe(step_one, use_container_width=True, hide_index=True)
    with st.expander("Шаг 2.2. КП и источник требования", expanded=True):
        if step_two is None:
            st.info("Сверка не построена. Запустите проверку ещё раз.")
        else:
            st.dataframe(step_two, use_container_width=True, hide_index=True)


def _competition_expander(report: dict | None) -> None:
    with st.expander("Блок 3. Производители и нацрежим", expanded=True):
        if not report:
            st.info("Таблица блока 3 появится после новой проверки.")
            return
        if not report.get("catalog_loaded"):
            st.warning("перечень № 1875 не загружен. Проверка запрета не выполняется.")
        rows = report.get("rows") or []
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("Позиций КП для таблицы производителей нет.")


configure_page("Результаты проверки")
render_header(
    "Результаты проверки",
    "Сводка восьми блоков, затем пары документов и доказательства compliance.",
)

if has_results():
    results = st.session_state["results"]
    conclusion = st.session_state.get("conclusion")
    blocks = (conclusion or {}).get("blocks") or []
    if blocks:
        st.subheader("Сводное заключение")
        verdict = conclusion.get("verdict") or "—"
        reason = conclusion.get("verdict_reason") or ""
        banner, action = st.columns([3, 1])
        with banner:
            if "комиссии" in verdict:
                st.error(verdict)
            elif "доработка" in verdict:
                st.warning(verdict)
            elif "без изменений" in verdict:
                st.success(verdict)
            else:
                st.info(verdict)
            if reason:
                st.caption(reason)
        with action:
            st.download_button(
                "Скачать отчёт",
                data=render_html(
                    results,
                    compliance_log=st.session_state.get("compliance_log", []),
                    hitl_log=st.session_state.get("hitl_log", []),
                    calculations_log=st.session_state.get("calculation_log", []),
                    conclusion=conclusion,
                    baseline=st.session_state.get("baseline"),
                    nmck_report=st.session_state.get("nmck_report"),
                    application_math=st.session_state.get("application_math"),
                    competition=st.session_state.get("competition"),
                ).encode("utf-8"),
                file_name="proverka-komplekta.html",
                mime="text/html",
                use_container_width=True,
            )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Блок": block["block_id"],
                        "Проверка": block["title"],
                        "Статус": block["status"],
                        "Комментарий": block.get("reason") or "—",
                    }
                    for block in blocks
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        linked = conclusion.get("linked_risks") or []
        st.subheader("Связанные риски")
        if linked:
            st.dataframe(pd.DataFrame(linked), use_container_width=True, hide_index=True)
        else:
            st.caption("Связанных рисков нет.")
        if any(item.get("kind") == "conclusion" for item in st.session_state.get("hitl_log") or []):
            st.success("Заключение подтверждено оператором. Замечания блоков сохранены.")
        else:
            st.warning("Заключение не подтверждено оператором.")
    else:
        st.info("Сводка не построена. Запустите проверку ещё раз.")
    _baseline_expanders(st.session_state.get("baseline"))
    _competition_expander(st.session_state.get("competition"))
    _results_table(results)
    _pair_details(results)
    _compliance_details(st.session_state.get("compliance_log", []))
