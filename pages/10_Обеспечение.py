from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.streamlit_pages import (  # noqa: E402
    configure_page,
    has_results,
    lookup_block,
    render_block,
    render_header,
)

configure_page("Обеспечение")
render_header(
    "Обеспечение заявки и договора",
    "Статус блока 8 из последней проверки.",
)

if has_results():
    block = lookup_block("8")
    if block is None:
        st.info("Сводка не построена. Запустите проверку ещё раз.")
    else:
        render_block(block)
        findings = block.get("findings") or []
        st.dataframe(
            [{"Проверка": item.get("text")} for item in findings],
            use_container_width=True,
            hide_index=True,
        )
