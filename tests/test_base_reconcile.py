import json
from dataclasses import asdict

from kp_tz_check.base_reconcile import (
    BaselineOffer,
    BaselineReconciliation,
    BaselineStatus,
    OfferMatchStatus,
    reconcile_baseline,
    render_baseline,
    render_offer_comparison,
)
from kp_tz_check.match import match_items
from kp_tz_check.models import FindingSeverity, Item


def _item(no: str, name: str, specs: str, unit: str, qty: str) -> Item:
    return Item(no=no, name=name, specs=specs, unit=unit, qty=qty)


def _same(no: str = "1", qty: str = "12") -> Item:
    return _item(no, "Набор тип 1", "300 циклов", "набор", qty)


def test_full_match_is_agreed():
    result = reconcile_baseline([_same()], [_same()], [_same()])
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.status == BaselineStatus.AGREED
    assert [source.document for source in row.sources] == ["ТЗ", "Заявка", "Запрос"]
    assert "winner" not in json.dumps(asdict(result))


def test_different_quantity_keeps_all_source_texts():
    result = reconcile_baseline([_same(qty="12")], [_same(qty="10")], [_same(qty="12")])
    row = result.rows[0]
    assert row.status == BaselineStatus.DIVERGED
    assert row.differing_fields == ["количество"]
    report = render_baseline(result)
    assert "ТЗ: Набор тип 1 | 300 циклов | набор | 12" in report
    assert "Заявка: Набор тип 1 | 300 циклов | набор | 10" in report
    assert "Запрос: Набор тип 1 | 300 циклов | набор | 12" in report
    assert "winner" not in json.dumps(asdict(result))


def test_position_only_in_tz_is_absent_and_not_copied():
    only_tz = _item("1", "Только в ТЗ", "параметр А", "шт.", "3")
    shared = _item("2", "Общая позиция", "параметр Б", "шт.", "1")
    result = reconcile_baseline([only_tz, shared], [shared], [shared])
    row = next(item for item in result.rows if any(source.name == "Только в ТЗ" for source in item.sources))
    assert row.status == BaselineStatus.ABSENT
    assert [source.document for source in row.sources] == ["ТЗ"]
    assert row.note == "нет в документе: Заявка, Запрос"
    report = render_baseline(result)
    assert report.count("Только в ТЗ") == 1
    assert "winner" not in json.dumps(asdict(result))


def test_missing_application_is_a_separate_row():
    result = reconcile_baseline([_same()], None, [_same()])
    agreed = result.rows[0]
    assert agreed.status == BaselineStatus.AGREED
    assert [source.document for source in agreed.sources] == ["ТЗ", "Запрос"]
    missing = result.rows[1]
    assert missing.status == BaselineStatus.ABSENT
    assert missing.note == "Заявка не предоставлена"
    assert missing.sources == []
    assert "Набор тип 1" not in render_baseline(BaselineReconciliation(rows=[missing]))


def test_items_without_number_match_by_name():
    named = _item("", "Набор тип 1", "300 циклов", "набор", "12")
    other = _item("", "Другой товар", "иные параметры", "шт.", "1")
    result = reconcile_baseline([named, other], [named], [named])
    agreed = [row for row in result.rows if row.status == BaselineStatus.AGREED]
    assert len(agreed) == 1
    assert [source.document for source in agreed[0].sources] == ["ТЗ", "Заявка", "Запрос"]


def _offer(items: list[Item], supplier: str = "ООО Апиген") -> BaselineOffer:
    return BaselineOffer(supplier=supplier, source_file="kp.docx", items=items)


def test_offer_matches_tz_and_diverges_from_application():
    result = reconcile_baseline(
        [_same(qty="12")],
        [_same(qty="10")],
        None,
        offers=[_offer([_same(qty="12")])],
    )
    assert len(result.offer_rows) == 2
    by_source = {row.requirement_source: row.status for row in result.offer_rows}
    assert by_source == {"ТЗ": OfferMatchStatus.MATCH, "Заявка": OfferMatchStatus.MISMATCH}
    assert [row.supplier for row in result.offer_rows] == ["ООО Апиген", "ООО Апиген"]
    assert len(result.critical_findings) == 1
    finding = result.critical_findings[0]
    assert finding.severity == FindingSeverity.CRITICAL
    assert finding.code == "2"
    assert "в заявке 10" in finding.text
    assert "в КП 12" in finding.text
    assert "ООО Апиген" not in render_baseline(result)
    assert "Полностью согласовано" not in render_offer_comparison(result)
    assert "ООО Апиген" in render_offer_comparison(result)


def test_agreed_position_is_compared_once():
    result = reconcile_baseline(
        [_same()],
        [_same()],
        [_same()],
        offers=[_offer([_same()])],
    )
    assert len(result.rows) == 1
    assert len(result.offer_rows) == 1
    row = result.offer_rows[0]
    assert row.requirement_source == "Согласованное требование"
    assert row.status == OfferMatchStatus.MATCH
    assert result.critical_findings == []


def test_extra_kp_line_stays_in_block_one_and_step_two():
    extra = _item("9", "Лишняя позиция", "другой параметр", "шт.", "1")
    result = reconcile_baseline(
        [_same()],
        [_same()],
        [_same()],
        offers=[_offer([_same(), extra])],
    )
    extra_row = next(row for row in result.offer_rows if row.position_name == "Лишняя позиция")
    assert extra_row.status == OfferMatchStatus.NO_REQUIREMENT
    assert extra_row.requirement_text == ""
    assert any("без базового требования" in item.text for item in result.critical_findings)
    block_one = match_items([_same()], [_same(), extra])
    assert any(item.kind == "extra" for item in block_one)


def test_two_present_documents_keep_both_texts():
    result = reconcile_baseline([_same(qty="12")], None, [_same(qty="8")])
    row = result.rows[0]
    assert row.status == BaselineStatus.DIVERGED
    report = render_baseline(BaselineReconciliation(rows=[row]))
    assert "ТЗ: Набор тип 1 | 300 циклов | набор | 12" in report
    assert "Запрос: Набор тип 1 | 300 циклов | набор | 8" in report
    assert "Заявка:" not in report
