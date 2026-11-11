from datetime import date
from pathlib import Path

from kp_tz_check.blocks import BlockId, build_blocks
from kp_tz_check.checks import audit
from kp_tz_check.extract import extract_document
from kp_tz_check.models import KpRecord
from kp_tz_check.parse import load_incoming, parse_requests
from kp_tz_check.request_builder import build_request


TEMPLATE = "data/requests/kp-request.example.docx"
ITEMS = [
    {"name": "Набор", "specs": "стерильный", "unit": "шт", "qty": "2"},
    {"name": "Реагент", "specs": "жидкий", "unit": "мл", "qty": "1"},
]


def _build(folder: Path, sent_on: str):
    return build_request(
        TEMPLATE,
        folder,
        outgoing="150",
        supplier="ООО Ромашка",
        email="buyer@example.com",
        items=ITEMS,
        sent_on=sent_on,
    )


def test_two_positions_keep_the_send_date_empty(tmp_path):
    result = _build(tmp_path, "")
    assert result["mailed"] is False
    assert result["sent_on"] == ""
    text = extract_document(result["path"]).text
    assert "Дата отправки:" in text
    assert "02.11.2026" not in text
    assert "Примерный заказчик" in text
    assert "10 календарных дней" in text
    assert "в течение 30 дней" in text
    assert "12 месяцев" in text
    incoming = tmp_path / "pack"
    target = incoming / "requests"
    target.mkdir(parents=True)
    (target / "request.docx").write_bytes(result["path"].read_bytes())
    requests, kps, tzs, applications = load_incoming(incoming)
    assert kps == [] and tzs == [] and applications == []
    assert requests[0].sent_on is None
    assert [item.name for item in requests[0].items] == ["Набор", "Реагент"]
    assert [item.specs for item in requests[0].items] == ["стерильный", "жидкий"]
    assert [item.unit for item in requests[0].items] == ["шт", "мл"]
    assert [item.qty for item in requests[0].items] == ["2", "1"]


def test_typed_send_date_is_checked_by_block_1(tmp_path):
    result = _build(tmp_path, "02.11.2026")
    request = parse_requests(extract_document(result["path"]))[0]
    assert request.sent_on == date(2026, 11, 2)
    assert request.outgoing_no == "150"
    kp = KpRecord(
        source_file=Path("150_kp.pdf"),
        prepared_on=date(2026, 11, 1),
        prepared_on_raw="01.11.2026",
        registered_on=date(2026, 11, 3),
        registered_on_raw="03.11.2026",
        supplier="ООО Ромашка",
        outgoing_no="150",
    )
    results = audit([request], [kp], [])
    blocks = build_blocks(
        {
            "results": results,
            "requests": [request],
            "kps": [kp],
            "tzs": [],
            "applications": [],
            "national_regime": [],
            "okpd2_catalog": [],
            "nmck": [],
            "security_documents": [],
        }
    )
    assert blocks[0].block_id == BlockId.PACKAGE
    assert any("раньше отправки запроса" in item.text for item in blocks[0].findings)
