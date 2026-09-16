from datetime import date
from pathlib import Path

from kp_tz_check.checks import audit
from kp_tz_check.extract import ExtractedDoc
from kp_tz_check.models import (
    DateCheckMark,
    FinalStatus,
    Item,
    ProductCheckMark,
    RequestRecord,
    TzRecord,
)
from kp_tz_check.parse import parse_requests
from kp_tz_check.serde import from_jsonable, to_jsonable
from kp_tz_check.tools import TOOLS, invoke, list_tools

ROOT = Path(__file__).resolve().parents[1]


def _request() -> RequestRecord:
    return RequestRecord(
        source_file=Path("Запрос.docx"),
        outgoing_no="2738",
        sent_on=date(2026, 8, 27),
        sent_on_raw="27.08.2026",
        supplier="ООО Апиген",
        email="sales@apigene.ru",
    )


def _tz() -> TzRecord:
    return TzRecord(
        source_file=Path("ТЗ.doc"),
        title="ТЗ",
        items=[Item(no="1", name="Набор", specs="300 циклов", unit="шт.", qty="12")],
    )


def test_tool_registry_covers_extract_parse_match_checks():
    names = set(TOOLS)
    assert names == {
        "extract_document",
        "parse_requests",
        "parse_kp",
                "parse_tz",
                "load_incoming",
                "structure_incoming",
                "structure_requests",
                "structure_kp",
                "structure_tz",
                "pair_requests_and_kps",
                "match_items",
                "match_nomenclature",
                "audit",
                "critique_pack",
                "load_concepts",
                "calculate_market_statistics",
                "check_spec_constraint",
                "comply_pack",
                "audit_incoming",
    }
    specs = list_tools()
    assert len(specs) == len(TOOLS)
    for spec in specs:
        assert spec["type"] == "function"
        params = spec["function"]["parameters"]
        assert params["type"] == "object"
        assert "required" in params


def test_request_json_roundtrip_keeps_dates():
    original = _request()
    restored = from_jsonable(RequestRecord, to_jsonable(original))
    assert restored == original
    assert restored.sent_on == date(2026, 8, 27)


def test_audit_tool_matches_direct_audit_and_does_not_invent_dates():
    request, tz = _request(), _tz()
    direct = audit([request], [], [tz])
    via_tool = invoke(
        "audit",
        {
            "requests": to_jsonable([request]),
            "kps": [],
            "tzs": to_jsonable([tz]),
        },
    )
    assert via_tool["results"][0]["status"] == direct[0].status.value == FinalStatus.MISMATCH.value
    assert via_tool["results"][0]["date_mark"] == DateCheckMark.UNKNOWN.value
    assert via_tool["results"][0]["product_mark"] == ProductCheckMark.FAIL.value
    assert any("нет соответствующего КП" in item for item in via_tool["results"][0]["comments"])
    assert via_tool["results"][0]["request"]["sent_on"] == "2026-08-27"
    assert via_tool["results"][0]["kp"] is None


def test_parse_requests_tool_matches_direct_parser():
    extracted = ExtractedDoc(
        path=Path("Запрос.docx"),
        paragraphs=[
            "Исх №2738 от 27.08.2026",
            "ООО Апиген",
            "sales@apigene.ru",
            "Исх №2737 от 27.08.2026",
            "ООО «Сесана»",
            "aps@sesana.ru",
            "ЗАПРОС",
            "Просим предоставить коммерческое предложение",
        ],
        tables=[
            [
                ["№ п/п", "Наименование, Требуемые функции (параметры)", "Ед. изм", "Кол-во"],
                ["1", "Набор тип 1\n300 циклов", "набор", "12"],
            ]
        ],
    )
    direct = parse_requests(extracted)
    via_tool = invoke("parse_requests", {"extracted": to_jsonable(extracted)})
    assert len(via_tool["requests"]) == len(direct) == 2
    assert via_tool["requests"][0]["outgoing_no"] == "2738"
    assert via_tool["requests"][0]["sent_on"] == "2026-08-27"
    assert via_tool["requests"][1]["email"] == "aps@sesana.ru"


def test_pair_and_match_item_tools():
    from kp_tz_check.models import KpRecord

    request = _request()
    kp = KpRecord(
        source_file=Path("2738-09-2026-от-09.09.2026.pdf"),
        prepared_on=date(2026, 9, 9),
        prepared_on_raw="09.09.2026",
        registered_on=date(2026, 9, 9),
        registered_on_raw="09.09.2026",
        supplier="ООО Апиген",
        outgoing_no="2738",
        items=[Item(no="1", name="Набор", specs="300 циклов", unit="шт.", qty="12")],
    )
    paired = invoke(
        "pair_requests_and_kps",
        {"requests": to_jsonable([request]), "kps": to_jsonable([kp])},
    )
    assert len(paired["pairs"]) == 1
    assert paired["pairs"][0]["request"]["outgoing_no"] == "2738"
    assert paired["pairs"][0]["reason"] == "outgoing_no"
    assert paired["pairs"][0]["score"] == 1.0
    assert paired["unmatched_requests"] == []
    assert paired["unmatched_kps"] == []

    matched = invoke(
        "match_items",
        {
            "tz_items": to_jsonable(_tz().items),
            "kp_items": to_jsonable(kp.items),
        },
    )
    kinds = {item["kind"] for item in matched["mismatches"]}
    assert "missing" not in kinds
    assert "extra" not in kinds


def test_extract_and_parse_real_request_file():
    path = ROOT / "incoming" / "requests" / "Запрос.docx"
    extracted = invoke("extract_document", {"path": str(path)})
    parsed = invoke("parse_requests", {"extracted": extracted["document"]})
    numbers = [item["outgoing_no"] for item in parsed["requests"]]
    assert numbers == ["2738", "2737", "2739", "2740", "2741"]
    assert all(item["sent_on"] == "2026-08-27" for item in parsed["requests"])


def test_invoke_unknown_and_missing_fields():
    import pytest

    with pytest.raises(KeyError):
        invoke("not_a_tool", {})
    with pytest.raises(ValueError, match="path"):
        invoke("extract_document", {})
