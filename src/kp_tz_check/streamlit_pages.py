"""Общие функции для multipage-интерфейса Streamlit."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import fitz
import pandas as pd
import streamlit as st

from kp_tz_check.application_math import check_applications
from kp_tz_check.base_reconcile import reconcile_pack
from kp_tz_check.blocks import build_blocks
from kp_tz_check.checks import audit
from kp_tz_check.compliance import apply_compliance
from kp_tz_check.calculations import calculate_nmck, calculate_offer_totals, collect_market_prices
from kp_tz_check.extract import extract_document
from kp_tz_check.hitl import apply_hitl_decisions
from kp_tz_check.journal import load_conclusion_acks, load_hitl_decisions, pack_fingerprint
from kp_tz_check.llm import LLMConfig, PrivateLLMClient
from kp_tz_check.models import PairResult, build_conclusion
from kp_tz_check.competition import build_competition_report
from kp_tz_check.nmck import build_nmck_report
from kp_tz_check.price_fairness import assess_prices, rows_from_offers
from kp_tz_check.registries import RegistryConfigError, build_registry
from kp_tz_check.parse import load_incoming, load_nmck, load_security_documents
from kp_tz_check.serde import from_jsonable, to_jsonable
from kp_tz_check.supplier_checks import check_suppliers

ROOT = Path(__file__).resolve().parents[2]
INCOMING = ROOT / "incoming"


def configure_page(title: str) -> None:
    st.set_page_config(page_title=title, page_icon="📋", layout="wide")


def save_uploads() -> Path:
    """Сохраняет загруженные файлы во временный комплект."""
    requests = st.file_uploader(
        "Запросы", type=["doc", "docx", "pdf"], accept_multiple_files=True
    )
    kps = st.file_uploader(
        "Коммерческие предложения",
        type=["doc", "docx", "pdf"],
        accept_multiple_files=True,
    )
    tzs = st.file_uploader(
        "Технические задания", type=["doc", "docx", "pdf"], accept_multiple_files=True
    )
    tmp = Path(tempfile.mkdtemp(prefix="kp-tz-check-"))
    for folder, files in {"requests": requests or [], "kp": kps or [], "tz": tzs or []}.items():
        destination = tmp / folder
        destination.mkdir(parents=True, exist_ok=True)
        for uploaded in files:
            (destination / uploaded.name).write_bytes(uploaded.getbuffer())
    return tmp


def source_controls() -> tuple[Path, str, str, bool]:
    """Отрисовывает общие элементы управления запуском проверки."""
    with st.sidebar:
        st.header("Источник файлов")
        source = st.radio(
            "Откуда брать документы",
            ("Папки incoming", "Загрузить файлы"),
            label_visibility="collapsed",
        )
        incoming = INCOMING if source == "Папки incoming" else save_uploads()
        if source == "Папки incoming":
            st.caption(f"Комплект: `{incoming}`")
        st.header("Модель")
        provider = st.selectbox(
            "Провайдер",
            ["Без LLM", "local-SLM(uStd)", "local-SLM(oLm)", "Sechenov.AI"],
        )
        endpoints = {
            "local-SLM(uStd)": "http://localhost:8888",
            "local-SLM(oLm)": "http://localhost:11434",
            "Sechenov.AI": "https://api.together.ai",
        }
        endpoint = st.text_input("Endpoint", value=endpoints.get(provider, ""))
        if provider != "Без LLM":
            st.caption("Ключ и модель берутся из .env и не отображаются в UI.")
        run = st.button("Проверить комплект", type="primary", use_container_width=True)
    return incoming, provider, endpoint, run


def execute_check(incoming: Path, provider: str, endpoint: str) -> None:
    """Запускает rule-engine или LangGraph и сохраняет результат в session state."""
    if provider != "Без LLM" and not endpoint:
        st.error("Для выбранного провайдера нужен endpoint.")
        return
    try:
        registry = build_registry()
    except RegistryConfigError as exc:
        st.error(str(exc))
        return

    with st.spinner("Читаю документы и сверяю комплект…"):
        requests, kps, tzs, applications = load_incoming(incoming)
        nmck_records = load_nmck(incoming)
        security_documents = load_security_documents(incoming)
        if provider == "Без LLM":
            results = audit(requests, kps, tzs)
            compliance = apply_compliance(to_jsonable(results), kps=to_jsonable(kps))
            serialized_results = compliance["results"]
        else:
            from kp_tz_check.graph import run_pack

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
                st.error(f"Не найден API key для {provider}. Добавьте его в .env.")
                return
            state = run_pack(incoming=incoming, llm_client=client)
            serialized_results = state.get("results") or []
            compliance = {
                "compliance_log": state.get("compliance_log") or [],
                "results": serialized_results,
            }

        request_data = to_jsonable(requests)
        kp_data = to_jsonable(kps)
        tz_data = to_jsonable(tzs)
        application_data = to_jsonable(applications)
        nmck_data = to_jsonable(nmck_records)
        security_data = to_jsonable(security_documents)
        calculation_log = calculate_offer_totals(kp_data)
        failed_files = {
            str(item["source_file"])
            for item in calculation_log
            if item.get("arithmetic_status") == "fail"
        }
        for result in serialized_results:
            kp = result.get("kp") or {}
            if str(kp.get("source_file")) not in failed_files:
                continue
            result["status"] = "Не соответствует"
            comment = "Арифметика: итоговая сумма КП не совпадает с суммой строк"
            if comment not in result.setdefault("comments", []):
                result["comments"].append(comment)

        fingerprint = pack_fingerprint(incoming)
        stored = load_hitl_decisions(
            ROOT / "reports" / "hitl_decisions.jsonl", fingerprint=fingerprint
        )
        acks = load_conclusion_acks(
            ROOT / "reports" / "hitl_decisions.jsonl", fingerprint=fingerprint
        )
        hitl = apply_hitl_decisions(serialized_results, stored)
        final_results = hitl["results"]
        if provider == "Без LLM":
            baseline = to_jsonable(reconcile_pack(tzs, applications, requests, kps))
        else:
            baseline = state.get("baseline") or to_jsonable(
                reconcile_pack(tzs, applications, requests, kps)
            )
        blocks = build_blocks(
            {
                "results": final_results,
                "requests": request_data,
                "kps": kp_data,
                "tzs": tz_data,
                "applications": application_data,
                "baseline": baseline,
                "nmck": nmck_data,
                "security_documents": security_data,
            }
        )
        conclusion = to_jsonable(build_conclusion(blocks))
        tz_items = tz_data[0]["items"] if tz_data else []
        nmck_report = build_nmck_report(
            kp_data,
            tz_items=tz_items,
            nmck_records=nmck_data,
            baseline=baseline,
            security_documents=security_data,
        )
        st.session_state["applications"] = application_data
        st.session_state["baseline"] = baseline
        st.session_state["nmck_report"] = nmck_report
        st.session_state["application_math"] = check_applications(application_data)
        st.session_state["competition"] = build_competition_report(kp_data, tz_data)
        st.session_state["results"] = [
            from_jsonable(PairResult, item) for item in final_results
        ]
        st.session_state["blocks"] = conclusion["blocks"]
        st.session_state["conclusion"] = conclusion
        nmck = calculate_nmck(
            kp_data,
            tz_data[0]["items"] if tz_data else [],
        )
        market_lookup = registry.lookup("market", "nmck")
        st.session_state["supplier_checks"] = check_suppliers(
            final_results,
            kps=kp_data,
            registry=registry,
        )
        st.session_state["price_fairness"] = assess_prices(
            rows_from_offers(kp_data, nmck.get("rows") or []),
            cv_passed=bool(nmck.get("rows"))
            and all(row.get("status") == "homogeneous" for row in nmck["rows"]),
            market_price=market_lookup.get("value") if market_lookup.get("status") != "not_checked" else None,
        )
        st.session_state["market"] = collect_market_prices(kp_data)
        st.session_state["nmck"] = nmck
        st.session_state["compliance_log"] = compliance["compliance_log"]
        st.session_state["calculation_log"] = calculation_log
        st.session_state["hitl_log"] = hitl["hitl_log"] + acks
        st.session_state["pack_fingerprint"] = fingerprint
        st.session_state["counts"] = {
            "requests": len(requests),
            "kps": len(kps),
            "tzs": len(tzs),
            "tz_items": sum(len(tz.items) for tz in tzs),
        }
        st.session_state["last_provider"] = provider
        st.session_state["last_run_path"] = str(incoming)


def has_results() -> bool:
    if not st.session_state.get("results"):
        st.info("Сначала выполните проверку на странице «Проверка».")
        return False
    return True


def lookup_block(block_id: str) -> dict | None:
    """Вернуть блок из последней проверки, без повторного чтения комплекта."""
    for block in st.session_state.get("blocks") or []:
        if str(block.get("block_id")) == block_id:
            return block
    return None


def render_block(block: dict) -> None:
    """Показать статус блока теми же формулировками, что и HTML-отчёт."""
    st.subheader(f"Блок {block['block_id']}. {block['title']}")
    st.metric("Статус", block.get("status") or "—")
    if block.get("reason"):
        st.write(block["reason"])
    findings = block.get("findings") or []
    if not findings:
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Критичность": item.get("severity") or "—",
                    "Замечание": item.get("text") or "—",
                    "Источник": item.get("source") or "—",
                }
                for item in findings
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )


@st.dialog("Просмотр коммерческого предложения", width="large")
def _show_kp_dialog(selected: Path) -> None:
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
    text = extracted.text or "\n".join(extracted.paragraphs)
    st.text_area(
        "Текст документа",
        value=text or "Текст не извлечён. Используйте скачивание файла.",
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


def render_header(title: str, description: str) -> None:
    st.title(title)
    st.caption(description)


def render_project_markdown(path: Path) -> None:
    """Показать файл документации. Ссылки на README и схему ведут на страницы приложения."""
    text = path.read_text(encoding="utf-8")
    for source, target in (
        ("](docs/system.md)", "](/Схема)"),
        ("](system.md)", "](/Схема)"),
        ("](../README.md)", "](/README)"),
        ("](README.md)", "](/README)"),
    ):
        text = text.replace(source, target)
    st.markdown(text)
