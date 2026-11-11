from kp_tz_check.contract_check import NO_SPEC
from kp_tz_check.risk_report import (
    UNCHECKED,
    build_risk_report,
    parse_param_lines,
    render_risk_html,
)


def _param(name, value, unit="шт", from_table=True):
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "required": True,
        "from_table": from_table,
    }


def test_full_match_has_percent_and_does_not_close_other_risks():
    requirements = [_param("срок", "12", "месяцев"), _param("объем", "10", "мл")]
    report = build_risk_report(requirements, list(requirements))
    assert report["percent"] == 100
    assert report["specification"]["confidence"] == "высокая"
    technical = report["risks"][0]
    assert technical["kind"] == "технический"
    assert technical["status"] == "не выявлено"
    assert technical["probability"] == "низкая"
    assert [item["status"] for item in report["risks"][1:]] == [UNCHECKED, UNCHECKED, UNCHECKED]
    assert report["sources"]["resources"] == []
    assert report["sources"]["internet_search"] is False


def test_missing_offer_does_not_search_or_count_percent():
    report = build_risk_report([_param("срок", "12")], None)
    assert report["percent"] is None
    assert report["specification"]["status"] == NO_SPEC
    assert report["risks"][0]["probability"] == UNCHECKED
    html = render_risk_html(report)
    assert "процент не считается" in html
    assert NO_SPEC in html
    assert "http" not in html
    empty = build_risk_report([], [])
    assert empty["percent"] is None
    assert empty["specification"]["status"] == "недостаточно данных"


def test_critical_deviation_raises_only_the_technical_risk():
    report = build_risk_report(
        [_param("объем", "10", "мл"), _param("срок", "12", "месяцев")],
        [_param("объем", "10", "мл")],
        legal="локальная проверка НПА не даёт статуса «действует»",
    )
    assert report["percent"] == 50
    assert report["risks"][0]["probability"] == "высокая"
    assert report["risks"][1]["status"] == "локальная проверка НПА не даёт статуса «действует»"
    assert report["risks"][1]["probability"] == UNCHECKED
    assert report["risks"][2]["status"] == UNCHECKED


def test_typed_lines_are_not_treated_as_a_table():
    rows = parse_param_lines("срок годности | 12 | месяцев\n\nобъем | 10 | мл")
    assert [row["name"] for row in rows] == ["срок годности", "объем"]
    assert all(row["from_table"] is False for row in rows)
    report = build_risk_report(rows, rows)
    assert report["specification"]["confidence"] == "низкая"
