from datetime import date
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.procedure_calendar import (  # noqa: E402
    apply_manual_date,
    calculate_procedure,
    load_deadlines,
    render_procedure_html,
)
from kp_tz_check.streamlit_pages import configure_page, render_header  # noqa: E402

configure_page("Процедура")
render_header(
    "Календарь процедуры",
    "Минимальные сроки по типу закупки. Хронология комплекта остаётся на странице «Календарь».",
)

rows = load_deadlines()
procedure_type = st.selectbox("Тип процедуры", [row["type"] for row in rows])
decision = st.date_input("Дата решения", value=date(2026, 11, 2))
publication = st.date_input("Дата публикации", value=date(2026, 11, 2))
report = calculate_procedure(procedure_type, decision, publication)
st.session_state["procedure_report"] = report

table = []
manual = {}
for key, title in (
    ("submission", "Подача заявок"),
    ("review", "Рассмотрение"),
    ("contract", "Заключение договора"),
):
    stage = report["stages"][key]
    use_manual = st.checkbox(f"Ручная дата: {title}", key=f"manual-{key}")
    chosen = st.date_input(title, value=date(2026, 11, 2), key=f"date-{key}") if use_manual else None
    minimum = date.fromisoformat(stage["min"]) if stage.get("min") else None
    checked = apply_manual_date(minimum, chosen)
    manual[key] = checked
    if checked["warning"]:
        st.warning(checked["warning"])
    table.append(
        {
            "Этап": title,
            "Минимум": stage.get("min") or "—",
            "Максимум": stage.get("max") or "—",
            "Статус": stage["status"],
            "Протокол": stage["protocol"],
            "Ручная дата": checked["date"] or "—",
        }
    )

st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
document = render_procedure_html(report, manual)
st.markdown(document, unsafe_allow_html=True)
st.download_button(
    "Скачать протокол сроков",
    data=document.encode("utf-8"),
    file_name="procedure.html",
    mime="text/html",
)
