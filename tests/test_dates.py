from datetime import date

from kp_tz_check.dates import date_from_filename, parse_date_string


def test_numeric_and_russian_dates():
    assert parse_date_string("27.08.2026") == date(2026, 8, 27)
    assert parse_date_string("«27» августа 2026 г.") == date(2026, 8, 27)
    assert parse_date_string("2026-08-27") == date(2026, 8, 27)


def test_filename_registration_date():
    value, raw = date_from_filename("2737-08-2026-от-27.08.2026.pdf")
    assert value == date(2026, 8, 27)
    assert "27.08.2026" in raw


def test_filename_without_date_is_not_invented():
    value, raw = date_from_filename("КП без даты.docx")
    assert value is None
    assert raw is None
