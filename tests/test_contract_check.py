from kp_tz_check.contract_check import (
    CRITICAL,
    INSUFFICIENT,
    MAJOR,
    MATCH,
    MINOR,
    NO_SPEC,
    check_specification,
)


def _param(name, value, unit="шт", required=True, from_table=True):
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "required": required,
        "from_table": from_table,
    }


def test_matching_parameters_and_a_missing_required_one():
    requirements = [_param("срок годности", "12", "месяцев"), _param("объем", "10", "мл")]
    offer = [
        _param("срок годности", "12", "месяцев"),
        _param("объем", "10", "мл"),
    ]
    matched = check_specification(requirements, offer)
    assert matched["status"] == MATCH
    assert matched["share"] == 1
    assert matched["confidence"] == "высокая"
    assert matched["internet_search"] is False
    missing = check_specification(requirements, [offer[0]])
    assert missing["status"] == CRITICAL
    assert missing["share"] == 0.5
    assert any(row["name"] == "объем" and row["class"] == CRITICAL for row in missing["rows"])


def test_empty_parameters_have_no_percent_and_no_internet_search():
    empty = check_specification([], [])
    assert empty["status"] == INSUFFICIENT
    assert empty["share"] is None
    assert empty["internet_search"] is False
    absent = check_specification([_param("срок", "12")], None)
    assert absent["status"] == NO_SPEC
    assert absent["share"] is None
    assert absent["internet_search"] is False


def test_unit_number_and_format_have_separate_classes():
    base = _param("объем", "12", "мл")
    unit = check_specification([base], [_param("объем", "12", "л")])
    assert unit["rows"][0]["class"] == MAJOR
    number = check_specification([base], [_param("объем", "6", "мл")])
    assert number["rows"][0]["class"] == MAJOR
    formatted = check_specification([base], [_param("объем", "12,0", "мл")])
    assert formatted["rows"][0]["class"] == MINOR
    low = check_specification(
        [_param("объем", "12", "мл", from_table=False)],
        [_param("объем", "12", "мл", from_table=False)],
    )
    assert low["confidence"] == "низкая"
