from datetime import date

from kp_tz_check.business_days import add_business_days, is_workday, load_business_calendar
from kp_tz_check.procedure_calendar import apply_manual_date, calculate_procedure, render_procedure_html
from kp_tz_check.timeline import build_timeline


def test_open_tender_submission_is_fifteen_calendar_days():
    report = calculate_procedure("Открытый конкурс", date(2026, 11, 1), date(2026, 11, 2), load_calendar=False)
    submission = report["stages"]["submission"]
    contract = report["stages"]["contract"]
    assert submission["min"] == "2026-11-17"
    assert "календарных дней" in submission["protocol"]
    assert "дата публикации + 15" in submission["protocol"]
    assert contract["min"] != contract["max"]
    assert contract["days_min"] == 10
    assert contract["days_max"] == 20
    assert "одна дата не выбрана" in contract["protocol"]


def test_quote_request_without_calendar_has_no_date(monkeypatch):
    monkeypatch.delenv("KP_BUSINESS_CALENDAR", raising=False)
    report = calculate_procedure("Запрос котировок (общий)", date(2026, 11, 2), date(2026, 11, 2))
    assert report["stages"]["submission"]["min"] is None
    assert report["status"] == "недостаточно данных"
    assert "не загружен" in report["stages"]["submission"]["protocol"]


def test_single_supplier_has_no_invented_dates():
    report = calculate_procedure("Закупка у единственного поставщика", date(2026, 11, 2), date(2026, 11, 2), load_calendar=False)
    assert report["status"] == "не применяется"
    assert all(stage["min"] is None for stage in report["stages"].values())


def test_saturday_is_not_a_workday_by_default(tmp_path):
    calendar_file = tmp_path / "calendar.json"
    calendar_file.write_text('{"holidays": [], "extra_workdays": []}', encoding="utf-8")
    calendar = load_business_calendar(calendar_file)
    friday = date(2026, 11, 6)
    assert is_workday(date(2026, 11, 7), calendar) is False
    assert add_business_days(friday, 1, calendar)[0] == date(2026, 11, 9)


def test_listed_weekend_and_transferred_workday():
    friday = date(2026, 11, 6)
    calendar = {
        "holidays": {date(2026, 11, 7), date(2026, 11, 8)},
        "extra_workdays": set(),
    }
    assert add_business_days(friday, 1, calendar)[0] == date(2026, 11, 9)
    transferred = {
        "holidays": {date(2026, 11, 7), date(2026, 11, 8)},
        "extra_workdays": {date(2026, 11, 7)},
    }
    assert add_business_days(friday, 1, transferred)[0] == date(2026, 11, 7)


def test_manual_date_before_minimum_is_kept():
    checked = apply_manual_date(date(2026, 11, 17), date(2026, 11, 16))
    assert checked["date"] == "2026-11-16"
    assert "раньше минимума" in checked["warning"]


def test_procedure_html_mentions_protocol_and_timeline_events_stay():
    report = calculate_procedure("Открытый конкурс", date(2026, 11, 2), date(2026, 11, 2), load_calendar=False)
    document = render_procedure_html(report)
    assert "Сложены дни" in document
    assert "Диаграмма" in document
    assert build_timeline([]) == []
    source = open("pages/9_Календарь.py", encoding="utf-8").read()
    assert "отправка запроса, подготовка и регистрация" in source
    procedure = open("pages/11_Процедура.py", encoding="utf-8").read()
    assert "session_state[\"results\"]" not in procedure
