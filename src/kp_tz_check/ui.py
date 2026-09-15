from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from kp_tz_check.checks import MIN_MARKET_KPS, audit, summarize
from kp_tz_check.models import FinalStatus, PairResult
from kp_tz_check.parse import load_incoming
from kp_tz_check.report import render_html, table_rows

ROOT = Path(__file__).resolve().parents[2]
INCOMING = ROOT / "incoming"


def run_app() -> None:
    st.set_page_config(page_title="Проверка запрос → КП → ТЗ", layout="wide")
    st.title("Проверка комплекта документов")
    st.caption("Запрос → коммерческое предложение → техническое задание перед согласованием")

    with st.sidebar:
        st.header("Источник файлов")
        source = st.radio(
            "Откуда брать документы",
            ("Папки incoming", "Загрузить файлы"),
            label_visibility="collapsed",
        )
        incoming = INCOMING
        if source == "Папки incoming":
            st.markdown(
                f"`{incoming}`\n\n"
                "- `requests` — запросы\n"
                "- `kp` — коммерческие предложения\n"
                "- `tz` — техническое задание"
            )
            _folder_inventory(incoming)
        else:
            incoming = _save_uploads()
        run = st.button("Проверить комплект", type="primary", use_container_width=True)

    if run:
        with st.spinner("Читаю документы и сверяю комплект…"):
            requests, kps, tzs = load_incoming(incoming)
            results = audit(requests, kps, tzs)
        st.session_state["results"] = results
        st.session_state["counts"] = {
            "requests": len(requests),
            "kps": len(kps),
            "tzs": len(tzs),
            "tz_items": sum(len(tz.items) for tz in tzs),
        }

    results: list[PairResult] | None = st.session_state.get("results")
    if not results:
        st.info("Нажмите «Проверить комплект», чтобы построить таблицу по парам запрос — КП.")
        return

    counts = st.session_state.get("counts", {})
    summary = summarize(results)
    _metrics(summary, counts)
    _results_table(results)
    _pair_details(results)
    _resume(summary, counts)
    st.download_button(
        "Скачать HTML-отчёт",
        data=render_html(results).encode("utf-8"),
        file_name="proverka-komplekta.html",
        mime="text/html",
    )


def _folder_inventory(incoming: Path) -> None:
    for name, label in (("requests", "Запросы"), ("kp", "КП"), ("tz", "ТЗ")):
        folder = incoming / name
        files = _list_docs(folder)
        st.caption(f"{label}: {len(files)}")
        for path in files:
            st.write(f"· {path.name}")


def _list_docs(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return [
        path
        for path in sorted(folder.iterdir())
        if path.is_file()
        and path.suffix.lower() in {".doc", ".docx", ".docm", ".pdf"}
        and not path.name.startswith("~$")
    ]


def _save_uploads() -> Path:
    requests = st.file_uploader("Запросы", type=["doc", "docx", "pdf"], accept_multiple_files=True)
    kps = st.file_uploader("Коммерческие предложения", type=["doc", "docx", "pdf"], accept_multiple_files=True)
    tzs = st.file_uploader("Технические задания", type=["doc", "docx", "pdf"], accept_multiple_files=True)
    tmp = Path(tempfile.mkdtemp(prefix="kp-tz-check-"))
    mapping = {
        "requests": requests or [],
        "kp": kps or [],
        "tz": tzs or [],
    }
    for folder, files in mapping.items():
        dest = tmp / folder
        dest.mkdir(parents=True, exist_ok=True)
        for uploaded in files:
            (dest / uploaded.name).write_bytes(uploaded.getbuffer())
    return tmp


def _metrics(summary: dict, counts: dict) -> None:
    matched = summary["matched_pairs"]
    total = summary["total_rows"]
    review = sum(1 for item in st.session_state["results"] if item.status == FinalStatus.NEEDS_REVIEW)
    mismatch = sum(1 for item in st.session_state["results"] if item.status == FinalStatus.MISMATCH)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Соответствует", matched)
    c2.metric("Требует уточнения", review)
    c3.metric("Не соответствует", mismatch)
    c4.metric("Запросов / КП / ТЗ", f"{counts.get('requests', 0)} / {counts.get('kps', 0)} / {counts.get('tzs', 0)}")
    c5.metric("Строк в таблице", total)
    if counts.get("kps", 0) < MIN_MARKET_KPS:
        st.warning(
            f"По положению о закупке для анализа рынка нужно не менее {MIN_MARKET_KPS} КП. "
            f"Сейчас: {counts.get('kps', 0)}."
        )
    elif counts.get("kps", 0) >= MIN_MARKET_KPS:
        st.caption(f"Для анализа рынка получено {counts.get('kps', 0)} КП (минимум {MIN_MARKET_KPS}).")


def _results_table(results: list[PairResult]) -> None:
    st.subheader("Таблица по парам «запрос — КП»")
    rows = table_rows(results)
    frame = pd.DataFrame(rows)
    st.dataframe(frame, use_container_width=True, hide_index=True, height=min(480, 72 + 48 * max(len(rows), 1)))


def _pair_details(results: list[PairResult]) -> None:
    st.subheader("Карточки пар")
    for index, item in enumerate(results, start=1):
        title = f"{index}. {item.status.value} · {item.request_label if item.request else 'КП без запроса'}"
        with st.expander(title, expanded=item.status == FinalStatus.MISMATCH):
            left, right = st.columns(2)
            with left:
                st.markdown("**Запрос**")
                if item.request:
                    st.write(f"Исх. № {item.request.outgoing_no or '—'}")
                    st.write(f"Поставщик: {item.request.supplier or '—'}")
                    st.write(f"Дата отправки: {item.request.sent_on.strftime('%d.%m.%Y') if item.request.sent_on else 'не прочитана'}")
                    st.caption(item.request.source_file.name)
                else:
                    st.write("Нет исходного запроса")
            with right:
                st.markdown("**КП**")
                if item.kp:
                    st.write(f"Поставщик: {item.kp.supplier or '—'}")
                    st.write(
                        "Подготовка: "
                        f"{item.kp.prepared_on.strftime('%d.%m.%Y') if item.kp.prepared_on else 'не прочитана'}"
                    )
                    st.write(
                        "Регистрация: "
                        f"{item.kp.registered_on.strftime('%d.%m.%Y') if item.kp.registered_on else 'не прочитана'}"
                    )
                    st.caption(item.kp.source_file.name)
                else:
                    st.write("Нет соответствующего КП")
            st.markdown(f"**Даты:** {item.date_mark.value} · **ТЗ↔КП:** {item.product_mark.value}")
            if item.tz:
                st.caption(f"Эталон ТЗ: {item.tz.source_file.name}, позиций: {len(item.tz.items)}")
            for comment in item.comments:
                st.write(f"• {comment}")


def _resume(summary: dict, counts: dict) -> None:
    st.subheader("Резюме")
    st.write(f"Полностью соответствующих пар: **{summary['matched_pairs']}** из {summary['total_rows']}.")
    if summary["requests_without_kp"]:
        st.markdown("**Запросы без КП**")
        for item in summary["requests_without_kp"]:
            st.write(f"• {item}")
    if summary["kps_without_request"]:
        st.markdown("**КП без запроса**")
        for item in summary["kps_without_request"]:
            st.write(f"• {item}")
    diffs = [
        item
        for item in summary["differences"]
        if "Положение о закупке" not in item and item != "Хронология дат соблюдена"
    ]
    if diffs:
        st.markdown("**Расхождения**")
        for item in diffs[:40]:
            st.write(f"• {item}")
