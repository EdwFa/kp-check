from pathlib import Path
import sys

import fitz
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.streamlit_pages import (  # noqa: E402
    configure_page,
    execute_check,
    render_header,
    source_controls,
)
from kp_tz_check.extract import extract_document  # noqa: E402
from kp_tz_check.ui import _metrics, _results_table, _resume  # noqa: E402
from kp_tz_check.checks import summarize  # noqa: E402


@st.dialog("Просмотр коммерческого предложения", width="large")
def show_kp_dialog(selected: Path) -> None:
    st.caption(selected.name)
    st.download_button(
        "Скачать исходный файл",
        data=selected.read_bytes(),
        file_name=selected.name,
        mime=_mime_type(selected),
        key=f"dialog-download-kp-{selected.name}",
    )
    if selected.suffix.lower() == ".pdf":
        document = fitz.open(stream=selected.read_bytes(), filetype="pdf")
        for page_number, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            st.image(
                pixmap.tobytes("png"),
                caption=f"Страница {page_number}",
                use_container_width=True,
            )
        return
    extracted = extract_document(selected)
    st.text_area(
        "Текст документа",
        value=extracted.text or "\n".join(extracted.paragraphs)
        or "Текст не извлечён. Используйте скачивание файла.",
        height=520,
        disabled=True,
    )


def _mime_type(path: Path) -> str:
    return {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docm": "application/vnd.ms-word.document.macroEnabled.12",
    }.get(path.suffix.lower(), "application/octet-stream")


configure_page("Проверка комплекта")
render_header(
    "Проверка комплекта",
    "Загрузите запросы, КП и ТЗ, затем запустите сквозную проверку.",
)

incoming, provider, endpoint, run = source_controls()
if run:
    execute_check(incoming, provider, endpoint)

results = st.session_state.get("results")
if results:
    counts = st.session_state.get("counts", {})
    summary = summarize(results)
    _metrics(summary, counts)
    _results_table(results, kp_viewer=show_kp_dialog)
    _resume(summary, counts)
else:
    st.info("Выберите источник документов и нажмите «Проверить комплект».")
