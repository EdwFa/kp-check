from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kp_tz_check.theme import apply_theme  # noqa: E402


def _card(title: str, text: str, page: str, label: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(text)
        st.page_link(page, label=label)


def about() -> None:
    st.set_page_config(
        page_title="Проверка закупочного комплекта",
        page_icon="📋",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme()
    st.title("Проверка закупочного комплекта")
    st.caption("Запрос → коммерческое предложение → техническое задание")
    st.info("Начните с «Проверки». Результат сохраняется и открывается на остальных страницах.")

    st.subheader("С чего начать")
    first, second, third = st.columns(3)
    with first:
        _card(
            "1. Проверка",
            "Загрузка документов и запуск анализа.",
            "pages/1_Проверка.py",
            "Открыть проверку",
        )
    with second:
        _card(
            "2. Результаты",
            "Восемь блоков, пары документов и итог.",
            "pages/2_Результаты.py",
            "Открыть результаты",
        )
    with third:
        _card(
            "3. Решения",
            "Подтверждение строк, которые требуют уточнения.",
            "pages/3_Решения.py",
            "Открыть решения",
        )

    st.subheader("Разбор комплекта")
    row = st.columns(4)
    details = [
        ("Поставщики", "Реквизиты из последней проверки.", "pages/6_Поставщики.py", "Поставщики"),
        ("Расчёты", "НМЦК, арифметика и отклонение цены.", "pages/7_Расчёты.py", "Расчёты"),
        ("ОКПД2", "Коды и справочник СМП.", "pages/8_ОКПД2.py", "ОКПД2"),
        ("Календарь", "Хронология дат комплекта.", "pages/9_Календарь.py", "Календарь"),
    ]
    for column, item in zip(row, details):
        with column:
            _card(*item)
    row = st.columns(3)
    more = [
        ("Обеспечение", "Заявка и исполнение договора.", "pages/10_Обеспечение.py", "Обеспечение"),
        ("Процедура", "Минимальные сроки закупки.", "pages/11_Процедура.py", "Процедура"),
        ("Запрос", "Черновик письма. Почта не отправляется.", "pages/12_Запрос.py", "Запрос"),
    ]
    for column, item in zip(row, more):
        with column:
            _card(*item)

    st.subheader("Статус проекта")
    left, right = st.columns(2)
    with left:
        _card("README", "Описание проекта и порядок проверки.", "pages/13_README.py", "README")
    with right:
        _card(
            "Схема работы",
            "Последовательность и реализованные функции.",
            "pages/14_Схема.py",
            "Схема работы",
        )

    st.subheader("Служебные")
    left, right = st.columns(2)
    with left:
        _card(
            "Диагностика",
            "Регрессия baseline и LangGraph. Это не функция ТЗ.",
            "pages/4_Eval.py",
            "Диагностика",
        )
    with right:
        _card(
            "Настройки",
            "Флаги реестров и провайдеры. Ключи скрыты.",
            "pages/5_Настройки.py",
            "Настройки",
        )


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
