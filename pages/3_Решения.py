from pathlib import Path
import hashlib
import os
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kp_tz_check.characteristic_search import (
    FixtureLookup,
    build_characteristic_lookup,
    build_live_lookup,
    http_transport,
    load_allowlist,
    load_fixture_pages,
    search_enabled,
)
from kp_tz_check.journal import append_characteristic_record, append_conclusion_ack
from kp_tz_check.streamlit_pages import configure_page, has_results, render_header  # noqa: E402
from kp_tz_check.ui import _hitl_controls  # noqa: E402
from kp_tz_check.contract_render import render_contract
from kp_tz_check.redaction import build_contours
from kp_tz_check.risk_report import build_risk_report, parse_param_lines, render_risk_html

configure_page("Решения оператора")
render_header(
    "Решения оператора",
    "Подтверждайте или отклоняйте только строки со статусом «Требует уточнения».",
)

if has_results():
    st.caption(
        f"Комплект: `{st.session_state.get('pack_fingerprint', 'не определён')}`"
    )
    conclusion = st.session_state.get("conclusion") or {}
    st.subheader("Подтверждение заключения")
    st.write(conclusion.get("verdict") or "Итог ещё не построен.")
    reviewer = st.text_input("Оператор, подтвердивший заключение")
    if st.button("Подтверждаю, что видел заключение"):
        verdict = str(conclusion.get("verdict") or "")
        fingerprint = st.session_state.get("pack_fingerprint") or ""
        record = {
            "kind": "conclusion",
            "verdict": verdict,
            "reviewer": reviewer,
            "accepted": True,
        }
        if fingerprint:
            append_conclusion_ack(
                ROOT / "reports" / "hitl_decisions.jsonl",
                fingerprint=fingerprint,
                verdict=verdict,
                reviewer=reviewer,
            )
        st.session_state.setdefault("hitl_log", []).append(record)
        st.success("Заключение записано в журнал. Статусы блоков и пар не изменены.")
    _hitl_controls(st.session_state["results"])
    history = st.session_state.get("hitl_log", [])
    if history:
        st.subheader("История решений текущего запуска")
        st.dataframe(history, use_container_width=True, hide_index=True)
    else:
        st.info("Сохранённых решений для текущего запуска нет.")


def _risk_form() -> None:
    st.subheader("Соответствие и риски")
    st.caption(
        "Строка: параметр | значение | единица. "
        "Пустая спецификация КП не запускает поиск в интернете."
    )
    tz_text = st.text_area("Параметры ТЗ", placeholder="срок годности | 12 | месяцев")
    offer_text = st.text_area("Спецификация КП")
    if not st.button("Собрать отчёт о соответствии"):
        return
    requirements = parse_param_lines(tz_text)
    offer = None if not offer_text.strip() else parse_param_lines(offer_text)
    report = build_risk_report(requirements, offer)
    percent = report["percent"]
    st.write(
        "Процент соответствия: процент не считается."
        if percent is None
        else f"Процент соответствия: {percent}%."
    )
    st.write(report["specification"]["status"])
    for row in report["specification"]["rows"]:
        text = f"{row['name']}: {row['class']}. {row['text']}"
        if row["class"] == "критическое":
            st.error(text)
        elif row["class"] == "значительное":
            st.warning(text)
        elif row["class"] == "незначительное":
            st.info(text)
        else:
            st.success(text)
    st.dataframe(report["risks"], use_container_width=True, hide_index=True)
    st.info(report["sources"]["status"])
    st.download_button(
        "Скачать отчёт о соответствии",
        data=render_risk_html(report).encode("utf-8"),
        file_name="sootvetstvie.html",
        mime="text/html",
    )


def _search_form() -> None:
    st.subheader("Поиск характеристик")
    if not search_enabled():
        st.info("Поиск характеристик не подключён.")
        return
    fixture = os.environ.get("KP_CHARACTERISTIC_FIXTURE", "").strip()
    allow_path = os.environ.get("KP_CHARACTERISTIC_ALLOWLIST", "").strip()
    fixture_path = Path(fixture) if fixture else None
    allowlist_path = Path(allow_path) if allow_path else None
    if allowlist_path is None or not allowlist_path.is_file():
        st.info("Включён поиск характеристик без клиента.")
        return
    use_fixture = fixture_path is not None and fixture_path.is_file()
    name = st.text_input("Наименование товара")
    manufacturer = st.text_input("Производитель")
    article = st.text_input("Артикул")
    registration = st.text_input("Регистрационное удостоверение")
    tz_text = st.text_area("Параметры ТЗ для поиска", key="char_tz")
    operator = st.text_input("Оператор поиска")
    if st.button("Найти характеристики"):
        if use_fixture:
            lookup = build_characteristic_lookup(FixtureLookup(load_fixture_pages(fixture_path)))
        else:
            lookup = build_live_lookup(allowlist_path, http_transport)
        requirements = parse_param_lines(tz_text)
        report = build_risk_report(
            requirements,
            None,
            lookup=lookup,
            query={
                "name": name,
                "manufacturer": manufacturer,
                "article": article,
                "registration": registration,
            },
            allowlist=load_allowlist(allowlist_path),
        )
        st.session_state["characteristic_hit"] = {
            "report": report,
            "requirements": requirements,
            "operator": operator,
        }
        st.session_state.pop("characteristic_final", None)
    hit = st.session_state.get("characteristic_hit")
    if not hit:
        return
    report = hit["report"]
    st.write(report["sources"]["status"])
    st.write(
        "Процент соответствия: процент не считается."
        if report["percent"] is None
        else f"Процент соответствия: {report['percent']}%."
    )
    st.dataframe(report["risks"], use_container_width=True, hide_index=True)
    selected = []
    for index, row in enumerate(report.get("candidates") or []):
        label = f"{row['name']} | {row['value']} | {row['unit']} — {row['note']}"
        if st.checkbox(label, key=f"char_accept_{index}"):
            selected.append(row)
    if report.get("candidates") and st.button("Принять выбранные строки"):
        if not selected:
            st.info("Строки не выбраны. Процент не считается.")
        else:
            final = build_risk_report(
                hit["requirements"],
                None,
                accepted=selected,
                resources=report["sources"]["resources"],
            )
            urls = [url for row in selected for url in row.get("urls") or []]
            digest = hashlib.sha256()
            for resource in report["sources"]["resources"]:
                if resource.get("url") in urls:
                    digest.update(str(resource.get("page_hash") or "").encode("utf-8"))
            append_characteristic_record(
                ROOT / "reports" / "hitl_decisions.jsonl",
                fingerprint=st.session_state.get("pack_fingerprint") or "",
                operator=hit["operator"],
                query=report.get("query") or {},
                urls=urls,
                page_hash=digest.hexdigest(),
            )
            st.session_state["characteristic_final"] = final
    final = st.session_state.get("characteristic_final")
    if final:
        _show_final(final)


def _show_final(final: dict) -> None:
    percent = final["percent"]
    st.write(
        "Процент соответствия: процент не считается."
        if percent is None
        else f"Процент соответствия: {percent}%."
    )
    st.write(final["specification"]["status"])
    st.dataframe(final["risks"], use_container_width=True, hide_index=True)


def _contract_form() -> None:
    st.subheader("Договор")
    st.caption("Поиск характеристик в интернете не выполняется. Пример шаблона не является договором университета.")
    template = os.environ.get("KP_CONTRACT_TEMPLATE", "").strip()
    template_path = Path(template) if template else None
    if template_path is None or not template_path.is_file():
        st.info("Шаблон договора не подключён. Кнопки генерации нет.")
        return
    winner = st.text_input("Победитель", help="Если протокол не загружен, укажите победителя вручную.")
    customer = st.text_input("Заказчик")
    director = st.text_input("ФИО для договора")
    operator = st.text_input("Оператор формирования договора")
    reason = st.text_input("Причина формирования")
    name = st.text_input("Наименование позиции")
    qty = st.text_input("Количество")
    price = st.text_input("Цена")
    total = st.text_input("Сумма")
    specs = st.text_input("Характеристики")
    shelf = st.text_input("Срок годности")
    delivery = st.text_input("Поставка")
    confirmed = st.checkbox("Подтверждаю формирование договора")
    if not confirmed:
        st.caption("Файл не создаётся, пока оператор не подтвердит формирование.")
        return
    if st.button("Сформировать договор"):
        contours = build_contours(
            {
                "customer": customer,
                "director": director,
                "operator": operator,
                "winner": {"name": winner, "inn": "", "director": director},
                "items": [{"name": name, "qty": qty, "price": price, "sum": total}],
            }
        )
        st.write("Аналитический контур")
        st.json(contours["analytics"])
        result = render_contract(
            template_path,
            ROOT / "reports" / "contracts",
            {
                "name": name,
                "qty": qty,
                "price": price,
                "sum": total,
                "specs": specs,
                "shelf": shelf,
                "delivery": delivery,
            },
            confirmed=True,
            operator=contours["journal_code"],
            reason=reason,
            journal_path=ROOT / "reports" / "hitl_decisions.jsonl",
            fingerprint=st.session_state.get("pack_fingerprint") or "",
            winner=winner,
        )
        if result["written"]:
            st.success(f"Создан новый файл {result['path'].name}. Предыдущие файлы не перезаписаны.")
        else:
            st.error(result["reason"])


_risk_form()
_search_form()
_contract_form()
