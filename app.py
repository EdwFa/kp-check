from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def about() -> None:
    st.set_page_config(
        page_title="Проверка закупочного комплекта", page_icon="📋", layout="wide"
    )
    st.title("Проверка закупочного комплекта")
    st.caption("Запрос → коммерческое предложение → техническое задание")
    st.markdown(
        """
        Выберите раздел в боковой панели:

        - **Проверка** — загрузка документов и запуск анализа;
        - **Результаты** — сводка восьми блоков, пары документов и доказательства compliance;
        - **Решения** — подтверждение результатов оператором;
        - **Поставщики** — реквизиты из последней проверки;
        - **Расчёты** — блоки НМЦК и арифметики;
        - **ОКПД2** — блок кодов и справочника СМП;
        - **Календарь** — хронология дат комплекта;
        - **Обеспечение** — блок обеспечения заявки и договора.

        Статус проекта:

        - **README** — описание проекта и порядок проверки;
        - **Схема работы** — последовательность и реализованные функции.

        Служебные:

        - **Диагностика** — регрессионная проверка baseline и LangGraph;
        - **Настройки** — состояние конфигурации провайдеров.
        """
    )
    st.info("Начните со страницы «Проверка». Результаты сохраняются при переходе между страницами.")


def _page_order(path: Path) -> tuple[int, str]:
    number, _, rest = path.stem.partition("_")
    if number.isdigit():
        return (int(number), rest)
    return (10**9, path.stem)


_SERVICE_PAGES = {"4_Eval.py", "5_Настройки.py"}
_STATUS_PAGES = {
    "13_README.py": "README",
    "14_Схема.py": "Схема работы",
}


def main() -> None:
    work_pages = [st.Page(about, title="О системе", default=True)]
    service_pages = []
    status_pages = []
    for path in sorted((ROOT / "pages").glob("*.py"), key=_page_order):
        title = _STATUS_PAGES.get(path.name)
        if path.name == "4_Eval.py":
            title = "Диагностика"
        page = st.Page(path, title=title)
        if path.name in _SERVICE_PAGES:
            service_pages.append(page)
        elif path.name in _STATUS_PAGES:
            status_pages.append(page)
        else:
            work_pages.append(page)
    current = st.navigation(
        {"": work_pages, "Статус проекта": status_pages, "Служебные": service_pages}
    )
    current.run()


main()
