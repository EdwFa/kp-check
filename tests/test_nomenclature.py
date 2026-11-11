from dataclasses import dataclass
from pathlib import Path

from kp_tz_check.match import item_score, match_items
from kp_tz_check.models import Item
from kp_tz_check.nomenclature import (
    match_nomenclature,
    reset_nomenclature_proposer,
    set_nomenclature_proposer,
)
from kp_tz_check.parse import load_incoming
from kp_tz_check.tools import invoke
from kp_tz_check.serde import to_jsonable

ROOT = Path(__file__).resolve().parents[1]


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


@dataclass
class FakeNomenclatureProposer:
    links: list[dict]

    def propose_item_links(self, **kwargs):
        return list(self.links)


def test_nomenclature_without_proposer_matches_rule_engine():
    tz_300 = _item(specs="Количество циклов картриджа – не менее 300; 84 Гб; не более 16 часов", qty="12")
    tz_150 = _item(no="2", specs="Количество циклов картриджа – не менее 150; 42 Гб; не более 10 часов", qty="6")
    kp_150 = _item(name="Набор реагентов для секвенирования тип 2", specs="150 циклов, 42 Гб, 10 часов", unit="набор", qty="6")
    kp_300 = _item(name="Набор реагентов для секвенирования тип 1", specs="300 циклов, 84 Гб, 16 часов", unit="набор", qty="12")
    rule = match_items([tz_300, tz_150], [kp_150, kp_300])
    via_agent, links = match_nomenclature([tz_300, tz_150], [kp_150, kp_300])
    assert [item.kind for item in via_agent] == [item.kind for item in rule]
    assert "missing" not in {item.kind for item in via_agent}
    assert {item["reason"] for item in links} == {"rule"}


def test_evil_proposer_cannot_glue_300_and_150_cycles():
    tz_300 = _item(specs="300 циклов, 84 Гб", qty="12")
    kp_150 = _item(specs="150 циклов, 42 Гб", qty="12")
    token = set_nomenclature_proposer(FakeNomenclatureProposer([{"tz_index": 0, "kp_index": 0, "article": "FCH"}]))
    try:
        mismatches, links = match_nomenclature([tz_300], [kp_150])
        kinds = {item.kind for item in mismatches}
        assert "missing" in kinds
        assert "extra" in kinds
        assert links == []
        assert item_score(tz_300, kp_150) == 0.0
    finally:
        reset_nomenclature_proposer(token)


def test_proposer_can_link_divergent_names_when_article_is_in_both():
    tz_item = _item(name="Позиция заказчика альфа", specs="артикул XYZ-42", qty="12")
    kp_item = _item(name="Vendor mega kit omega series", specs="pack XYZ-42", qty="11")
    rule_kinds = {item.kind for item in match_items([tz_item], [kp_item])}
    assert "missing" in rule_kinds
    token = set_nomenclature_proposer(
        FakeNomenclatureProposer([{"tz_index": 0, "kp_index": 0, "article": "XYZ-42"}])
    )
    try:
        mismatches, links = match_nomenclature([tz_item], [kp_item])
        kinds = {item.kind for item in mismatches}
        assert "missing" not in kinds
        assert "extra" not in kinds
        assert links[0]["reason"] == "article"
        assert any(item.kind == "qty" for item in mismatches)
    finally:
        reset_nomenclature_proposer(token)


def test_incoming_pairs_by_outgoing_number():
    incoming = ROOT / "incoming"
    requests, kps, _tzs, _applications = load_incoming(incoming)
    paired = invoke(
        "pair_requests_and_kps",
        {"requests": to_jsonable(requests), "kps": to_jsonable(kps)},
    )
    assert len(paired["pairs"]) == 3
    assert {item["reason"] for item in paired["pairs"]} == {"outgoing_no"}
    assert {item["request"]["outgoing_no"] for item in paired["pairs"]} == {"2737", "2738", "2739"}
    assert {item["outgoing_no"] for item in paired["unmatched_requests"]} == {"2740", "2741"}
