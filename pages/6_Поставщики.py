from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.streamlit_pages import configure_page, has_results, render_header  # noqa: E402

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
