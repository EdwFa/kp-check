from dataclasses import dataclass
from datetime import date
from pathlib import Path

from kp_tz_check.extract import ExtractedDoc, extract_document
from kp_tz_check.parse import load_incoming, parse_kp, parse_requests
from kp_tz_check.structure import (
    reset_proposer,
    set_proposer,
    structure_incoming,
    structure_kp,
    structure_requests,
)
from kp_tz_check.tools import invoke

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeProposer:
    requests: list[dict] | None = None
    kp: dict | None = None
    tz: dict | None = None

    def propose_requests(self, **kwargs):
        return list(self.requests or [])

    def propose_kp(self, **kwargs):
        return dict(self.kp or {})

    def propose_tz(self, **kwargs):
        return dict(self.tz or {})


def test_real_request_file_still_has_five_outgoing_letters():
    extracted = extract_document(ROOT / "incoming" / "requests" / "Запрос.docx")
    records = structure_requests(extracted)
    assert [item.outgoing_no for item in records] == ["2738", "2737", "2739", "2740", "2741"]
    assert all(item.sent_on == date(2026, 8, 27) for item in records)


def test_evil_proposer_cannot_add_invented_letter_or_date():
    extracted = extract_document(ROOT / "incoming" / "requests" / "Запрос.docx")
    token = set_proposer(
        FakeProposer(
            requests=[
                {
                    "outgoing_no": "9999",
                    "sent_on": "2000-01-01",
                    "supplier": "ООО Выдумка",
                    "email": "nobody@example.com",
                }
            ]
        )
    )
    try:
        records = structure_requests(extracted)
        assert [item.outgoing_no for item in records] == ["2738", "2737", "2739", "2740", "2741"]
        assert all(item.sent_on == date(2026, 8, 27) for item in records)
    finally:
        reset_proposer(token)


def test_proposer_recovers_letters_when_parser_misses_ish_header():
    extracted = ExtractedDoc(
        path=Path("Запрос.docx"),
        paragraphs=[
            "Исходящий 2738 от 27.08.2026",
            "ООО Апиген",
            "sales@apigene.ru",
            "ЗАПРОС",
            "Просим предоставить коммерческое предложение",
        ],
    )
    baseline = parse_requests(extracted)
    assert baseline[0].outgoing_no is None
    token = set_proposer(
        FakeProposer(
            requests=[
                {
                    "outgoing_no": "2738",
                    "sent_on_raw": "27.08.2026",
                    "supplier": "ООО Апиген",
                    "email": "sales@apigene.ru",
                }
            ]
        )
    )
    try:
        records = structure_requests(extracted)
        assert len(records) == 1
        assert records[0].outgoing_no == "2738"
        assert records[0].sent_on == date(2026, 8, 27)
        assert records[0].email == "sales@apigene.ru"
        assert records[0].supplier == "ООО Апиген"
    finally:
        reset_proposer(token)


def test_invented_sent_date_is_not_filled():
    extracted = ExtractedDoc(
        path=Path("Запрос.docx"),
        paragraphs=["Исходящий 2738 без даты", "ООО Апиген", "sales@apigene.ru", "ЗАПРОС"],
    )
    token = set_proposer(
        FakeProposer(
            requests=[{"outgoing_no": "2738", "sent_on_raw": "01.01.2020", "email": "sales@apigene.ru"}]
        )
    )
    try:
        records = structure_requests(extracted)
        assert records[0].outgoing_no == "2738"
        assert records[0].sent_on is None
        assert any("не найдена в документе" in item or "не прочитана" in item for item in records[0].notes)
    finally:
        reset_proposer(token)


def test_delivery_date_is_not_used_as_sent_date():
    extracted = ExtractedDoc(
        path=Path("Запрос.docx"),
        paragraphs=[
            "Исходящий 2738 от 27.08.2026",
            "ООО Апиген",
            "sales@apigene.ru",
            "ЗАПРОС",
            "Поставка по 30.11.2026",
        ],
    )
    token = set_proposer(
        FakeProposer(requests=[{"outgoing_no": "2738", "sent_on_raw": "30.11.2026"}])
    )
    try:
        records = structure_requests(extracted)
        assert records[0].outgoing_no == "2738"
        assert records[0].sent_on == date(2026, 8, 27)
        assert any("не рядом с исх" in item or "не подставлена" in item for item in records[0].notes)
    finally:
        reset_proposer(token)


def test_kp_registration_stays_from_filename():
    extracted = ExtractedDoc(
        path=Path("2738-09-2026-от-09.09.2026.pdf"),
        paragraphs=["Текст без даты подготовки"],
    )
    parsed = parse_kp(extracted)
    assert parsed.registered_on == date(2026, 9, 9)
    assert parsed.prepared_on is None
    token = set_proposer(
        FakeProposer(kp={"registered_on": "01.01.2020", "prepared_on_raw": "15.03.2021"})
    )
    try:
        record = structure_kp(extracted)
        assert record.registered_on == date(2026, 9, 9)
        assert record.prepared_on is None
        blob = " ".join(record.notes)
        assert "имени файла" in blob or "не найдена в документе" in blob
    finally:
        reset_proposer(token)


def test_structure_incoming_matches_parser_without_proposer():
    incoming = ROOT / "incoming"
    left = load_incoming(incoming)
    right = structure_incoming(incoming)
    assert [item.outgoing_no for item in left[0]] == [item.outgoing_no for item in right[0]]
    assert [item.sent_on for item in left[0]] == [item.sent_on for item in right[0]]
    assert [item.registered_on for item in left[1]] == [item.registered_on for item in right[1]]
    via_tool = invoke("structure_incoming", {"incoming": str(incoming)})
    assert [item["outgoing_no"] for item in via_tool["requests"]] == ["2738", "2737", "2739", "2740", "2741"]
    assert {item["registered_on"] for item in via_tool["kps"]} == {
        "2026-08-27",
        "2026-09-09",
        "2026-09-10",
    }
