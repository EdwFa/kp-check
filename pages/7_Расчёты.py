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

configure_page("Расчёты и НМЦК")
render_header(
    "Расчёты и НМЦК",
    "Арифметика КП, сопоставимая цена и коэффициент вариации рынка.",
)

if has_results():
    for block_id in ("4", "5"):
        block = lookup_block(block_id)
        if block is None:
            st.info("Сводка не построена. Запустите проверку ещё раз.")
            st.stop()
        render_block(block)
    totals = st.session_state.get("calculation_log") or []
    market = st.session_state.get("market") or {}
    nmck = st.session_state.get("nmck") or {"method": "—", "rows": []}

    st.subheader("Итоги по КП")
    summary_rows = [
        {
            "Поставщик": report["supplier"],
            "Файл": Path(report["source_file"]).name,
            "Расчётный итог": f"{report['total']:,.2f}",
            "Итог в КП": (
                f"{report['declared_total']:,.2f}"
                if report["declared_total"] is not None
                else "не найден"
            ),
            "Расхождение": (
                f"{report['difference']:,.2f}"
                if report["difference"] is not None
                else "—"
            ),
            "Арифметика": report["arithmetic_status"].upper(),
            "Статус строк": "PASS" if report["status"] == "ok" else "REVIEW",
        }
        for report in totals
    ]
    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    else:
        st.info("КП для расчёта не найдены.")

    for report in totals:
        with st.expander(f"{report['supplier']} · {Path(report['source_file']).name}"):
            st.caption(report["formula"])
            if report["arithmetic_reason"]:
                st.warning(report["arithmetic_reason"])
            else:
                st.success("Итоговая сумма КП совпадает с суммой строк.")
            rows = [
                {
                    "Позиция": line["position"],
                    "Количество": line.get("quantity", "—"),
                    "Единица": line.get("unit", "—"),
                    "Цена": line.get("unit_price", "—"),
                    "Сумма": line.get("line_total", "—"),
                    "НДС": line.get("vat", "—"),
                    "Формула": line.get("formula", line.get("reason", "—")),
                    "Статус": line["status"],
                }
                for line in report["lines"]
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Справедливость цены")
    fairness = st.session_state.get("price_fairness") or {}
    if fairness.get("rows"):
        st.write(fairness.get("verdict") or "—")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Поставщик": row["supplier"],
                        "Позиция": row["position"],
                        "Цена КП": row["price"],
                        "НМЦК": row["nmck"],
                        "Отклонение": row["deviation"],
                        "Порог −25%": "да" if any("демпинг" in note for note in row["notes"]) else "нет",
                        "Порог +20%": "да" if any("выше рыночной" in note for note in row["notes"]) else "нет",
                        "2σ": "да" if "Аномалия" in row["notes"] else "нет",
                        "Рыночная цена": row["market_status"] if row["market_price"] is None else row["market_price"],
                        "CV пройден": row["cv_passed"],
                    }
                    for row in fairness["rows"]
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Таблица справедливости цены появится после новой проверки.")

    st.subheader("Рыночная статистика")
    if market.get("groups"):
        market_rows = []
        for name, group in market["groups"].items():
            market_rows.append(
                {
                    "Позиция": name,
                    "Цены": ", ".join(f"{value:,.2f}" for value in group["values"]),
                    "Средняя": group.get("mean"),
                    "σ": group.get("standard_deviation"),
                    "CV, %": group.get("coefficient_of_variation"),
                    "Поставщики": (group.get("suppliers") or {}).get("supplier_count"),
                    "Статус": group.get("status"),
                    "Комментарий": group.get("reason") or "—",
                }
            )
        st.dataframe(pd.DataFrame(market_rows), use_container_width=True, hide_index=True)
        st.caption("V = σ / средняя цена × 100%; неоднородность при CV > 33%.")
    else:
        st.info(f"Рыночные цены не рассчитаны: {market.get('reason', 'недостаточно данных')}.")

    st.subheader("НМЦК")
    nmck_report = st.session_state.get("nmck_report") or {}
    if nmck_report.get("justification_note"):
        st.warning(nmck_report["justification_note"])
    elif nmck_report:
        st.success("Сверка с файлом обоснования выполнена.")
    else:
        st.info("Пересчёт НМЦК появится после новой проверки.")
    detail_rows = [
        {
            "Позиция": row.get("position"),
            "n": row.get("n"),
            "Среднее": row.get("mean"),
            "Второй расчёт": row.get("alternate_mean"),
            "σ": row.get("sigma"),
            "V, %": row.get("coefficient"),
            "Статус статистики": row.get("statistics_status"),
            "НМЦК за единицу": row.get("unit_nmck"),
            "Количество": row.get("quantity") if row.get("quantity") is not None else row.get("quantity_status"),
            "Статус": row.get("status"),
        }
        for row in nmck_report.get("rows") or []
    ]
    if detail_rows:
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
        st.caption("Два расчёта среднего и CV. Совпали — одна пара чисел в статусе agreed. Не совпали — требует ручной проверки.")
    st.caption(nmck.get("method") or "—")
    nmck_rows = [
        {
            "Позиция": row["position"],
            "НМЦК за единицу": row["unit_nmck"],
            "Количество ТЗ": row["quantity"] or "не найдено",
            "НМЦК позиции": row["total_nmck"] or "не рассчитана",
            "КП": row["offer_count"],
            "Поставщики": row["supplier_count"],
            "Статус": row["status"],
        }
        for row in nmck.get("rows") or []
    ]
    if nmck_rows:
        st.dataframe(pd.DataFrame(nmck_rows), use_container_width=True, hide_index=True)
        st.caption("Формула: НМЦК = средняя цена за единицу × количество.")
    else:
        st.info("НМЦК не рассчитана: нет сопоставимых цен.")

    diffs = nmck_report.get("justification_diffs") or []
    st.subheader("Расхождения с обоснованием")
    if not nmck_report:
        st.info("Сверка с обоснованием появится после новой проверки.")
    elif diffs:
        st.dataframe(
            pd.DataFrame([{"Замечание": item.get("text")} for item in diffs]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Строк «цена обоснования не найдена в КП» нет.")

    flags = [
        item.get("text")
        for row in nmck_report.get("rows") or []
        for item in row.get("antidumping") or []
    ]
    st.subheader("Антидемпинг")
    if flags:
        for text in flags:
            st.warning(text)
    else:
        st.caption("Флагов антидемпинга нет.")

    st.subheader("Арифметика заявки")
    application_math = st.session_state.get("application_math") or {}
    application_rows = []
    for report in application_math.get("reports") or []:
        for line in report.get("lines") or []:
            application_rows.append(
                {
                    "Позиция": line.get("position"),
                    "Статус": line.get("status"),
                    "Сумма": line.get("net"),
                    "НДС": line.get("vat_amount"),
                    "Комментарий": line.get("note"),
                }
            )
    if application_rows:
        st.dataframe(pd.DataFrame(application_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Заявка не загружена. Таблица КП выше остаётся отдельной секцией.")
