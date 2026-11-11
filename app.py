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
        - **Eval** — регрессионная диагностика baseline и LangGraph;
        - **Настройки** — состояние конфигурации провайдеров;
        - **Поставщики** — реквизиты из последней проверки;
        - **Расчёты** — блоки НМЦК и арифметики;
        - **ОКПД2** — блок кодов и справочника СМП;
        - **Календарь** — хронология дат комплекта;
        - **Обеспечение** — блок обеспечения заявки и договора.
        """
    )
    st.info("Начните со страницы «Проверка». Результаты сохраняются при переходе между страницами.")


def _page_order(path: Path) -> tuple[int, str]:
    number, _, rest = path.stem.partition("_")
    if number.isdigit():
        return (int(number), rest)
    return (10**9, path.stem)


def main() -> None:
    section_pages = [
        st.Page(path)
        for path in sorted((ROOT / "pages").glob("*.py"), key=_page_order)
    ]
    current = st.navigation(
        [st.Page(about, title="О системе", default=True), *section_pages]
    )
    current.run()


main()
