from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from kp_tz_check.checks import MIN_MARKET_KPS, audit, summarize
from kp_tz_check.compliance import apply_compliance
from kp_tz_check.hitl import apply_hitl_decisions
from kp_tz_check.journal import append_hitl_decisions, load_hitl_decisions, pack_fingerprint
from kp_tz_check.llm import LLMConfig, PrivateLLMClient
from kp_tz_check.models import FinalStatus, PairResult
from kp_tz_check.parse import load_incoming
from kp_tz_check.report import render_html, table_rows
from kp_tz_check.serde import from_jsonable, to_jsonable

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
        st.header("Модель")
        provider = st.selectbox(
            "Провайдер",
            ["Без LLM", "local-SLM(uStd)", "local-SLM(oLm)", "Sechenov.AI"],
        )
        defaults = {
            "local-SLM(uStd)": "http://localhost:8888",
            "local-SLM(oLm)": "http://localhost:11434",
            "Sechenov.AI": "https://api.together.ai",
        }
        default_url = defaults.get(provider, "")
        endpoint = st.text_input("Endpoint", value=default_url)
        if provider != "Без LLM":
            st.caption("API key и имя модели берутся из .env и в UI не отображаются.")
        run = st.button("Проверить комплект", type="primary", use_container_width=True)

    if run:
        with st.spinner("Читаю документы и сверяю комплект…"):
            if provider == "Без LLM":
                requests, kps, tzs, _applications = load_incoming(incoming)
                results = audit(requests, kps, tzs)
                compliance = apply_compliance(to_jsonable(results), kps=to_jsonable(kps))
                serialized_results = compliance["results"]
            else:
                if not endpoint:
                    st.error("Для выбранного провайдера нужен endpoint.")
                    return
                try:
                    from kp_tz_check.graph import run_pack
                except ModuleNotFoundError as exc:
                    if exc.name == "langgraph":
                        st.error(
                            "Для режима с LLM нужен пакет langgraph. "
                            "Запустите Streamlit из .venv или выполните: "
                            ".venv/bin/python -m pip install -r requirements.txt"
                        )
                        return
                    raise
                provider_key = {
                    "local-SLM(uStd)": "unsloth",
                    "local-SLM(oLm)": "ollama",
                    "Sechenov.AI": "together",
                }[provider]
                config = LLMConfig.from_env(provider_key)
                if not config.model:
                    st.error(f"Не найдено имя модели для {provider} в .env.")
                    return
                client = PrivateLLMClient(
                    LLMConfig(
                        enabled=True,
                        base_url=endpoint.rstrip("/"),
                        api_key=config.api_key,
                        model=config.model,
                        timeout=config.timeout,
                    )
                )
                if provider != "local-SLM(oLm)" and not client.config.api_key:
                    st.error(
                        f"Не найден API key для {provider}. "
                        f"Добавьте его в .env и перезапустите Streamlit."
                    )
                    return
                requests, kps, tzs, _applications = load_incoming(incoming)
                state = run_pack(incoming=incoming, llm_client=client)
                serialized_results = state.get("results") or []
                compliance = {
                    "compliance_log": state.get("compliance_log") or [],
                    "results": serialized_results,
                }
            fingerprint = pack_fingerprint(incoming)
            stored_decisions = load_hitl_decisions(
                ROOT / "reports" / "hitl_decisions.jsonl",
                fingerprint=fingerprint,
            )
            hitl = apply_hitl_decisions(serialized_results, stored_decisions)
            results = [from_jsonable(PairResult, item) for item in hitl["results"]]
        st.session_state["results"] = results
        st.session_state["compliance_log"] = compliance["compliance_log"]
        st.session_state["hitl_log"] = hitl["hitl_log"]
        st.session_state["pack_fingerprint"] = fingerprint
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
    _hitl_controls(results)
    _resume(summary, counts)
    _compliance_details(st.session_state.get("compliance_log", []))
    st.download_button(
        "Скачать HTML-отчёт",
        data=render_html(
            results,
            compliance_log=st.session_state.get("compliance_log", []),
            hitl_log=st.session_state.get("hitl_log", []),
        ).encode("utf-8"),
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


def _results_table(results: list[PairResult], kp_viewer=None) -> None:
    st.subheader("Таблица по парам «запрос — КП»")
    rows = table_rows(results)
    if kp_viewer is None:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
            height=min(480, 72 + 48 * max(len(rows), 1)),
        )
        return

    header = st.columns([0.08, 0.34, 0.34, 0.24])
    for column, title in zip(header, ("№", "Запрос", "Файл КП", "Статус")):
        column.markdown(f"**{title}**")
    for index, (item, row) in enumerate(zip(results, rows), start=1):
        columns = st.columns([0.08, 0.34, 0.34, 0.24])
        columns[0].write(index)
        columns[1].write(row.get("Запрос (дата отправки)", "—"))
        if item.kp:
            if columns[2].button(
                row.get("Файл КП", item.kp.source_file.name),
                key=f"open-kp-{index}-{item.kp.source_file}",
                use_container_width=True,
            ):
                kp_viewer(item.kp.source_file)
        else:
            columns[2].write("—")
        columns[3].write(item.status.value)


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
    results = st.session_state.get("results", [])
    status_counts = {
        "Соответствует": sum(item.status == FinalStatus.MATCH for item in results),
        "Требует уточнения": sum(item.status == FinalStatus.NEEDS_REVIEW for item in results),
        "Не соответствует": sum(item.status == FinalStatus.MISMATCH for item in results),
    }
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Соответствует", status_counts["Соответствует"])
    c2.metric("Требует уточнения", status_counts["Требует уточнения"])
    c3.metric("Не соответствует", status_counts["Не соответствует"])
    c4.metric("Всего строк", summary["total_rows"])

    if status_counts["Не соответствует"]:
        st.error(
            f"Найдено жёстких расхождений: {status_counts['Не соответствует']}. "
            "Пакет нельзя передавать без исправления."
        )
    elif status_counts["Требует уточнения"]:
        st.warning(
            f"Требуют решения оператора: {status_counts['Требует уточнения']} "
            "строк."
        )
    else:
        st.success("Критических расхождений не обнаружено.")

    left, right = st.columns(2)
    with left:
        if summary["requests_without_kp"]:
            with st.expander(
                f"Запросы без КП · {len(summary['requests_without_kp'])}",
                expanded=True,
            ):
                for item in summary["requests_without_kp"]:
                    st.markdown(f"- {item}")
        else:
            st.success("Для каждого запроса найдено КП.")
    with right:
        if summary["kps_without_request"]:
            with st.expander(
                f"КП без запроса · {len(summary['kps_without_request'])}",
                expanded=True,
            ):
                for item in summary["kps_without_request"]:
                    st.markdown(f"- `{item}`")
        else:
            st.success("Лишних КП не найдено.")

    diffs = [
        item
        for item in summary["differences"]
        if "Положение о закупке" not in item and item != "Хронология дат соблюдена"
    ]
    if diffs:
        with st.expander(f"Расхождения · {len(diffs)}", expanded=True):
            for item in diffs[:40]:
                st.markdown(f"- {item}")


def _compliance_details(log: list[dict]) -> None:
    if not log:
        return
    st.subheader("Доказательства compliance")
    for entry in log:
        with st.expander(str(entry.get("concept_id", "Compliance"))):
            evidence = entry.get("evidence") or {}
            status = entry.get("status", evidence.get("status", "—"))
            if status in {"homogeneous", "pass", "ok"}:
                st.success(f"Результат: {status}")
            elif status in {"insufficient_data", "fail", "heterogeneous"}:
                st.warning(f"Результат: {status}")
            else:
                st.info(f"Результат: {status}")
            if entry.get("source"):
                st.caption(f"Источник: {entry['source']}")
            if entry.get("span"):
                st.markdown(f"**Цитата:** «{entry['span']}»")
            groups = evidence.get("groups")
            if groups:
                rows = []
                for name, group in groups.items():
                    rows.append(
                        {
                            "Позиция": name,
                            "Цены": ", ".join(f"{value:,.2f}" for value in group.get("values", [])),
                            "Средняя цена": group.get("mean"),
                            "CV, %": group.get("coefficient_of_variation"),
                            "Порог, %": group.get("threshold"),
                            "Поставщики": (group.get("suppliers") or {}).get("supplier_count"),
                            "Результат": group.get("status"),
                            "Комментарий": group.get("reason") or "—",
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)
                st.caption("Формула: V = σ / средняя цена × 100%; неоднородность при CV > 33%.")
            elif evidence.get("check"):
                check = evidence["check"]
                c1, c2, c3 = st.columns(3)
                c1.metric("Оператор", check.get("operator", "—"))
                c2.metric("Порог ТЗ", check.get("threshold", "—"))
                c3.metric("Значение КП", check.get("actual", "не найдено"))
                if evidence.get("request_item") or evidence.get("kp_item"):
                    st.caption(
                        f"ТЗ: {(evidence.get('request_item') or {}).get('specs', '—')}  \n"
                        f"КП: {(evidence.get('kp_item') or {}).get('specs', '—')}"
                    )


def _hitl_controls(results: list[PairResult]) -> None:
    review_rows = [
        (index, item)
        for index, item in enumerate(results)
        if item.status == FinalStatus.NEEDS_REVIEW
    ]
    if not review_rows:
        return
    st.subheader("Решения оператора")
    st.caption("Решение применяется только после указания оператора и причины.")
    labels = {
        index: f"{index + 1}. {item.request_label if item.request else 'КП без запроса'}"
        for index, item in review_rows
    }
    selected = st.selectbox(
        "Строка для решения",
        [index for index, _ in review_rows],
        format_func=lambda index: labels[index],
    )
    action = st.selectbox(
        "Решение",
        ["keep", "confirm", "reject"],
        format_func={
            "keep": "Оставить требует уточнения",
            "confirm": "Подтвердить соответствие",
            "reject": "Отклонить",
        }.get,
    )
    reviewer = st.text_input("Оператор")
    reason = st.text_area("Причина решения")
    if st.button("Сохранить решение", type="primary"):
        decision = {
            "result_index": selected,
            "action": action,
            "reviewer": reviewer,
            "reason": reason,
        }
        outcome = apply_hitl_decisions(
            to_jsonable(results),
            [decision],
        )
        accepted = [item for item in outcome["hitl_log"] if item.get("accepted")]
        if accepted:
            append_hitl_decisions(
                ROOT / "reports" / "hitl_decisions.jsonl",
                fingerprint=st.session_state["pack_fingerprint"],
                decisions=[decision],
            )
        st.session_state["results"] = [
            from_jsonable(PairResult, item)
            for item in outcome["results"]
        ]
        st.session_state.setdefault("hitl_log", []).extend(outcome["hitl_log"])
        st.rerun()
