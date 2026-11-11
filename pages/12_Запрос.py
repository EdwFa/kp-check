from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.request_builder import build_request
from kp_tz_check.streamlit_pages import configure_page, render_header  # noqa: E402

TEMPLATE = ROOT / "data" / "requests" / "kp-request.example.docx"

configure_page("Запрос КП")
render_header(
    "Конструктор запроса",
    "Черновик собирается из примера. Это не официальный бланк университета. Почта не отправляется.",
)

if not TEMPLATE.is_file():
    st.info("Пример шаблона запроса не найден. Кнопки сборки нет.")
else:
    st.caption(f"Пример: `{TEMPLATE.name}`. Дата отправки пустая, пока её не ввести.")
    outgoing = st.text_input("Исх. №", value="150")
    supplier = st.text_input("Поставщик")
    email = st.text_input("Email поставщика")
    sent_on = st.text_input("Дата отправки", value="", help="Оставьте пустым, если запрос ещё не отправлен.")
    st.markdown("Позиции")
    items = []
    for index in (1, 2):
        name = st.text_input(f"Наименование {index}", key=f"item_name_{index}")
        specs = st.text_input(f"Параметры {index}", key=f"item_specs_{index}")
        unit = st.text_input(f"Единица {index}", key=f"item_unit_{index}")
        qty = st.text_input(f"Количество {index}", key=f"item_qty_{index}")
        if name.strip() or qty.strip():
            items.append({"name": name, "specs": specs, "unit": unit, "qty": qty})
    if st.button("Собрать черновик"):
        result = build_request(
            TEMPLATE,
            ROOT / "reports" / "requests",
            outgoing=outgoing,
            supplier=supplier,
            email=email,
            items=items,
            sent_on=sent_on,
        )
        if result["sent_on"]:
            st.success(f"Черновик {result['path'].name}. Дата отправки: {result['sent_on']}. Письмо не отправлено.")
        else:
            st.success(f"Черновик {result['path'].name}. Дата отправки не заполнена. Письмо не отправлено.")
