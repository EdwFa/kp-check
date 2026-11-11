from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.egrul_form import (  # noqa: E402
    egrul_enabled,
    fetch_card,
    fetch_extract,
    http_transport,
)
from kp_tz_check.streamlit_pages import configure_page, has_results, render_header  # noqa: E402


def _show_egrul(card: dict | None) -> None:
    if not card:
        return
    st.write(f"Форма ЕГРЮЛ: {card.get('status')}")
    row = card.get("row") or {}
    if row:
        st.write(row.get("name") or "—")
        st.write(
            "ИНН {inn}, КПП {kpp}, ОГРН {ogrn}".format(
                inn=row.get("inn") or "—",
                kpp=row.get("kpp") or "—",
                ogrn=row.get("ogrn") or "—",
            )
        )
        if row.get("director"):
            st.write(row["director"])
        if row.get("terminated"):
            st.write(f"Дата прекращения: {row['terminated']}")
    if card.get("source_url"):
        st.caption(card["source_url"])


def _egrul_request() -> None:
    st.subheader("Сведения ЕГРЮЛ")
    if not egrul_enabled():
        st.info("Получение сведений ЕГРЮЛ не подключено.")
        return
    query = st.text_input("ИНН или ОГРН", key="egrul_query")
    if st.button("Запросить сведения"):
        st.session_state["egrul_card"] = fetch_card(query, http_transport)
        st.session_state.pop("egrul_pdf", None)
    card = st.session_state.get("egrul_card")
    _show_egrul(card if isinstance(card, dict) else None)
    token = ((card or {}).get("row") or {}).get("extract_token") if isinstance(card, dict) else ""
    if token and st.button("Запросить выписку"):
        statement = fetch_extract(token, http_transport)
        st.session_state["egrul_pdf"] = statement
    statement = st.session_state.get("egrul_pdf")
    if isinstance(statement, dict) and statement.get("pdf"):
        st.download_button("Скачать выписку", data=statement["pdf"], file_name="egrul.pdf")
    elif isinstance(statement, dict):
        st.info(statement.get("status") or "")


configure_page("Поставщики и реквизиты")
render_header(
    "Поставщики и реквизиты",
    "Реквизиты из последней проверки. Повторного чтения комплекта нет.",
)

if has_results():
    checks = st.session_state.get("supplier_checks")
    if checks is None:
        st.info("Сводка не построена. Запустите проверку ещё раз.")
    elif not checks:
        st.info("В текущем комплекте нет КП для проверки.")
    else:
        counts = {
            status: sum(item["status"] == status for item in checks)
            for status in ("PASS", "REVIEW", "FAIL")
        }
        c1, c2, c3 = st.columns(3)
        c1.metric("PASS", counts["PASS"])
        c2.metric("REVIEW", counts["REVIEW"])
        c3.metric("FAIL", counts["FAIL"])
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Статус": item["status"],
                        "Поставщик КП": item["supplier"],
                        "Поставщик в запросе": item["request_supplier"],
                        "ИНН": item["requisites"]["inn"] or "—",
                        "КПП": item["requisites"]["kpp"] or "—",
                        "ОГРН": item["requisites"]["ogrn"] or "—",
                        "Карточка": item.get("card") or "—",
                        "Комментарий": item["reason"],
                        "Источник": Path(item["source_file"]).name,
                    }
                    for item in checks
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        for index, item in enumerate(checks, start=1):
            with st.expander(f"{index}. {item['status']} · {item['supplier']}"):
                st.write(item.get("card") or item["reason"])
                st.write(item["reason"])
                criteria = item.get("criteria") or []
                if criteria:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Критерий": row["criterion"],
                                    "Статус": row["status"],
                                    "Значение": row.get("value") if row.get("value") is not None else "—",
                                    "Источник": row.get("source") or "",
                                }
                                for row in criteria
                            ]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("Карточка реестров появится после новой проверки.")
                st.caption(f"Источник файла: {item['source_file']}")
                st.json(item["requisites"])
                _show_egrul(item.get("egrul"))

_egrul_request()
