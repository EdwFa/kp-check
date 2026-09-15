from pathlib import Path

from kp_tz_check.match import item_score, match_items, pair_requests_and_kps
from kp_tz_check.models import Item, KpRecord, RequestRecord


def _item(**kwargs) -> Item:
    data = {
        "no": "1",
        "name": "Набор реагентов для секвенирования",
        "specs": "",
        "unit": "шт.",
        "qty": "12",
    }
    data.update(kwargs)
    return Item(**data)


def test_two_similar_kits_match_by_specs_not_name():
    tz_300 = _item(specs="Количество циклов картриджа – не менее 300; 84 Гб; не более 16 часов", qty="12")
    tz_150 = _item(no="2", specs="Количество циклов картриджа – не менее 150; 42 Гб; не более 10 часов", qty="6")
    kp_150 = _item(name="Набор реагентов для секвенирования тип 2", specs="150 циклов, 42 Гб, 10 часов", unit="набор", qty="6")
    kp_300 = _item(name="Набор реагентов для секвенирования тип 1", specs="300 циклов, 84 Гб, 16 часов", unit="набор", qty="12")
    assert item_score(tz_300, kp_300) > item_score(tz_300, kp_150)
    mismatches = match_items([tz_300, tz_150], [kp_150, kp_300])
    kinds = {item.kind for item in mismatches}
    assert "missing" not in kinds
    assert "extra" not in kinds
    assert any(item.kind == "unit" for item in mismatches)


def test_pair_by_supplier_name():
    request = RequestRecord(
        source_file=Path("Запрос.docx"),
        outgoing_no="2737",
        sent_on=None,
        sent_on_raw=None,
        supplier="ООО «Сесана»",
        email="aps@sesana.ru",
    )
    kp = KpRecord(
        source_file=Path("КП Сесана 29.08.2026.docx"),
        prepared_on=None,
        prepared_on_raw=None,
        registered_on=None,
        registered_on_raw=None,
        supplier="ООО Сесана",
    )
    pairs, unmatched_r, unmatched_k = pair_requests_and_kps([request], [kp])
    assert len(pairs) == 1
    assert not unmatched_r
    assert not unmatched_k
