import json

from docx import Document

from kp_tz_check.contract_render import render_contract
from kp_tz_check.journal import load_hitl_decisions
from kp_tz_check.redaction import build_contours


FIO = "Иванов Иван Иванович"
TEMPLATE = "data/contracts/supply.example.docx"
FIELDS = {
    "name": "Набор",
    "qty": "2",
    "price": "100",
    "sum": "200",
    "specs": "стерильный",
    "shelf": "12 месяцев",
    "delivery": "10 дней",
}


def _source():
    return {
        "customer": "Заказчик Пример",
        "director": FIO,
        "operator": FIO,
        "winner": {"name": "ООО Ромашка", "inn": "7701234567", "director": FIO},
        "items": [{"name": "Набор", "price": "100"}],
    }


def test_analytics_hides_fio_and_contract_keeps_the_same_price():
    contours = build_contours(_source())
    analytics = json.dumps(contours["analytics"], ensure_ascii=False)
    contract = json.dumps(contours["contract"], ensure_ascii=False)
    assert FIO not in analytics
    assert "Заказчик Пример" not in analytics
    assert "7701234567" not in analytics
    assert FIO in contract
    assert "7701234567" in contract
    assert contours["analytics"]["items"] == contours["contract"]["items"]
    assert contours["journal_code"]
    assert FIO not in contours["journal_code"]


def test_contract_file_is_written_only_after_confirmation(tmp_path):
    journal = tmp_path / "hitl_decisions.jsonl"
    blocked = render_contract(
        TEMPLATE,
        tmp_path / "contracts",
        FIELDS,
        confirmed=False,
        operator="фио-test",
        reason="проверка",
        journal_path=journal,
        fingerprint="abc",
    )
    assert blocked["written"] is False
    assert list((tmp_path / "contracts").glob("*")) == [] if (tmp_path / "contracts").exists() else True
    empty = render_contract(
        TEMPLATE,
        tmp_path / "contracts",
        {**FIELDS, "price": ""},
        confirmed=True,
        operator="фио-test",
        reason="проверка",
        journal_path=journal,
        fingerprint="abc",
    )
    assert empty["written"] is False
    assert not journal.exists()
    contours = build_contours(_source())
    first = render_contract(
        TEMPLATE,
        tmp_path / "contracts",
        FIELDS,
        confirmed=True,
        operator=contours["journal_code"],
        reason="подтверждение оператора",
        journal_path=journal,
        fingerprint="abc",
        winner="ООО Ромашка",
    )
    second = render_contract(
        TEMPLATE,
        tmp_path / "contracts",
        FIELDS,
        confirmed=True,
        operator=contours["journal_code"],
        reason="повтор",
        journal_path=journal,
        fingerprint="abc",
        winner="ООО Ромашка",
    )
    assert first["written"] and second["written"]
    assert first["path"] != second["path"]
    assert first["path"].exists() and second["path"].exists()
    text = "\n".join(paragraph.text for paragraph in Document(str(first["path"])).paragraphs)
    assert "Набор" in text and "100" in text
    assert "{{price}}" not in text
    saved = journal.read_text(encoding="utf-8")
    assert FIO not in saved
    assert contours["journal_code"] in saved
    assert "подтверждение оператора" in saved
    assert first["path"].name in saved
    assert load_hitl_decisions(journal, fingerprint="abc") == []
