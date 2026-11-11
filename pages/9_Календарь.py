from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.streamlit_pages import configure_page, has_results, render_header  # noqa: E402
from kp_tz_check.timeline import build_timeline  # noqa: E402

configure_page("Календарь")
render_header(
    "Календарь закупки",
    "Хронология комплекта: отправка запроса, подготовка и регистрация КП.",
)

if has_results():
    timeline = build_timeline(st.session_state["results"])
    counts = {
        status: sum(item["status"] == status for item in timeline)
        for status in ("PASS", "REVIEW", "FAIL")
    }
    c1, c2, c3 = st.columns(3)
    c1.metric("PASS", counts["PASS"])
    c2.metric("REVIEW", counts["REVIEW"])
    c3.metric("FAIL", counts["FAIL"])

    rows = []
    for item in timeline:
        for event in item["events"]:
            rows.append(
                {
                    "Пара": item["pair"],
                    "Событие": event["event"],
                    "Дата": event["date"].strftime("%d.%m.%Y"),
                    "Источник": event["source"],
                    "Статус пары": item["status"],
                }
            )
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Даты для календаря не найдены.")

    st.subheader("Контрольные карточки")
    for item in timeline:
        with st.expander(f"{item['pair']}. {item['status']} · {item['label']}"):
            st.write(item["reason"])
            st.write(
                f"Срок действия КП: "
                f"{item['validity_days']} дн." if item["validity_days"] else
                "Срок действия КП: не найден"
            )
            st.json(
                [
                    {
                        "event": event["event"],
                        "date": event["date"].isoformat(),
                        "source": event["source"],
                    }
                    for event in item["events"]
                ]
            )
