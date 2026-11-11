from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.eval import evaluate_incoming, evaluate_suite  # noqa: E402
from kp_tz_check.streamlit_pages import configure_page, render_header  # noqa: E402

configure_page("Диагностика")
render_header(
    "Диагностика",
    "Регрессионная проверка baseline и LangGraph на текущем комплекте.",
)

incoming = st.session_state.get("last_run_path", str(ROOT / "incoming"))
st.caption(f"Комплект для диагностики: `{incoming}`")
if st.button("Запустить диагностику", type="primary"):
    with st.spinner("Сравниваю direct audit и graph…"):
        result = evaluate_incoming(incoming)
    c1, c2, c3 = st.columns(3)
    c1.metric("Строк", result["rows"])
    c2.metric("Direct == Graph", "PASS" if result["status_exact_match"] else "FAIL")
    c3.metric("Compliance evidence", result["compliance_log_entries"])
    st.subheader("Инварианты")
    st.dataframe(
        [
            {"Инвариант": name, "Результат": "PASS" if passed else "FAIL"}
            for name, passed in result["invariants"].items()
        ],
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("Fingerprint строк"):
        st.json({"direct": result["direct"], "graph": result["graph"]})

st.divider()
st.subheader("Регрессионные сценарии")
st.caption("Проверка direct audit против сохранённых golden-ожиданий.")
cases_dir = ROOT / "tests" / "eval"
if st.button("Запустить все сценарии"):
    with st.spinner("Запускаю golden и negative-сценарии…"):
        suite = evaluate_suite(incoming, cases_dir)
    c1, c2, c3 = st.columns(3)
    c1.metric("Golden-сценариев", suite["golden_count"])
    c2.metric("Negative-сценариев", suite["negative_count"])
    c3.metric("Итог", "PASS" if suite["passed"] else "FAIL")

    rows = [
        {
            "Сценарий": item["case"],
            "Ожидаемых строк": item["expected_rows"],
            "Фактических строк": item["actual_rows"],
            "Golden": "PASS" if item["passed"] else "FAIL",
            "Graph + инварианты": "PASS" if item["graph_passed"] else "FAIL",
        }
        for item in suite["cases"]
    ]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    negative_rows = [
        {
            "Сценарий": item["case"],
            "Описание": item["description"],
            "Статусы": ", ".join(sorted(set(item["statuses"]))),
            "Ошибка обнаружена": "PASS" if item["passed"] else "FAIL",
        }
        for item in suite["negative_results"]
    ]
    if negative_rows:
        st.subheader("Negative-сценарии")
        st.dataframe(negative_rows, use_container_width=True, hide_index=True)
    if suite["negative_count"] == 0:
        st.info(
            "Negative-сценарии пока не добавлены в tests/eval."
        )
    for item in suite["cases"]:
        if item["mismatches"]:
            with st.expander(f"Расхождения: {item['case']}"):
                st.json(item["mismatches"])
