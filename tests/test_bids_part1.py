from pathlib import Path

from kp_tz_check.bids import (
    PART_CRITICAL,
    PART_OK,
    PART_REVIEW,
    PART_STATUSES,
    PDF_NEEDS_TEXT,
    SCHEMA_MISSING,
    load_bid_packages,
    parse_statement_xml,
)
from kp_tz_check.parse import load_bids
from kp_tz_check.supplier_checks import REQUISITE_PATTERNS

SCHEMA = Path("data/egrul/tags.example.json")
XML = """<?xml version="1.0" encoding="UTF-8"?>
<Выписка>
  <НаимЮЛ>ООО Ромашка</НаимЮЛ>
  <ИНН>7701234567</ИНН>
  <КПП>770101001</КПП>
  <ОГРН>1027700132195</ОГРН>
  <ФИОРуководителя>Иванов Иван Иванович</ФИОРуководителя>
  <Статус>действующее</Статус>
</Выписка>
"""


def _write(folder: Path, name: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def test_xml_without_schema_returns_no_partial_fields(tmp_path, monkeypatch):
    monkeypatch.delenv("KP_EGRUL_SCHEMA", raising=False)
    part = tmp_path / "bids" / "Ромашка" / "part1"
    _write(part, "Выписка.xml", XML)
    package = load_bid_packages(tmp_path)[0]
    statement = package.part1.statement
    assert statement is not None
    assert statement.note == SCHEMA_MISSING
    assert statement.inn is None
    assert statement.name is None
    assert statement.director is None
    assert package.part1.status == PART_REVIEW
    assert package.part1.status in PART_STATUSES


def test_pdf_is_not_parsed_as_an_extract(tmp_path, monkeypatch):
    monkeypatch.delenv("KP_EGRUL_SCHEMA", raising=False)
    part = tmp_path / "bids" / "Ромашка" / "part1"
    part.mkdir(parents=True)
    (part / "Выписка.pdf").write_bytes(b"%PDF-1.4\nINN 7701234567")
    package = load_bids(tmp_path)[0]
    assert package.part1.files == ["Выписка.pdf"]
    assert package.part1.statement is None
    assert PDF_NEEDS_TEXT in package.part1.findings
    assert package.part1.status == PART_REVIEW


def test_configured_schema_reads_the_same_requisite_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("KP_EGRUL_SCHEMA", str(SCHEMA))
    part = tmp_path / "bids" / "Ромашка" / "part1"
    _write(part, "Выписка.xml", XML)
    _write(
        part,
        "заявка.txt",
        "Наименование: ООО Ромашка\nПодписант: Иванов Иван Иванович\nДата подачи: 02.11.2026\n",
    )
    statement = load_bid_packages(tmp_path)[0].part1.statement
    assert statement.inn == "7701234567"
    assert statement.kpp == "770101001"
    assert statement.ogrn == "1027700132195"
    assert set(REQUISITE_PATTERNS) <= {"inn", "kpp", "ogrn"}
    package = load_bid_packages(tmp_path)[0]
    assert package.part1.status == PART_OK


def test_excluded_and_bankruptcy_are_critical(tmp_path):
    schema = {"status": "Статус", "name": "НаимЮЛ"}
    for legal in ("исключено из ЕГРЮЛ", "банкротство"):
        participant = tmp_path / "bids" / legal / "part1"
        _write(participant, "Выписка.xml", XML.replace("действующее", legal))
        _write(participant, "заявка.txt", "Наименование: ООО Ромашка\n")
    packages = {item.participant: item for item in load_bid_packages(tmp_path, schema=schema, load_schema=False)}
    assert packages["исключено из ЕГРЮЛ"].part1.status == PART_CRITICAL
    assert packages["банкротство"].part1.status == PART_CRITICAL
    schema = {"name": "НаимЮЛ", "status": "Статус", "director": "ФИОРуководителя"}
    part = tmp_path / "bids" / "Ромашка" / "part1"
    _write(part, "Выписка.xml", XML.replace("действующее", "в процессе ликвидации"))
    _write(part, "заявка.txt", "Наименование: ООО Другое\nПодписант: Иванов Иван Иванович\n")
    package = next(item for item in load_bid_packages(tmp_path, schema=schema, load_schema=False) if item.participant == "Ромашка")
    assert package.part1.status == PART_CRITICAL
    assert any("ликвидации" in item for item in package.part1.findings)
    assert any("Требует ручной проверки" in item for item in package.part1.findings)


def test_matching_director_is_correct_and_expired_power_is_critical(tmp_path):
    schema = {
        "name": "НаимЮЛ",
        "director": "ФИОРуководителя",
        "status": "Статус",
        "inn": "ИНН",
        "kpp": "КПП",
        "ogrn": "ОГРН",
    }
    matched = tmp_path / "bids" / "Ромашка" / "part1"
    _write(matched, "Выписка.xml", XML)
    _write(matched, "заявка.txt", "Наименование: ООО Ромашка\nПодписант: Иванов Иван Иванович\n")
    assert load_bid_packages(tmp_path, schema=schema, load_schema=False)[0].part1.status == PART_OK

    other = tmp_path / "bids" / "Другой" / "part1"
    _write(other, "Выписка.xml", XML)
    _write(
        other,
        "заявка.txt",
        "Наименование: ООО Ромашка\nПодписант: Петров Петр Петрович\n"
        "Дата подачи: 02.11.2026\nДоверенность до: 01.01.2026\n",
    )
    expired = next(item for item in load_bid_packages(tmp_path, schema=schema, load_schema=False) if item.participant == "Другой")
    assert expired.part1.status == PART_CRITICAL
    assert any("просрочена" in item for item in expired.part1.findings)

    bare = tmp_path / "bids" / "Бездоверенности" / "part1"
    _write(bare, "Выписка.xml", XML)
    _write(bare, "заявка.txt", "Наименование: ООО Ромашка\nПодписант: Петров Петр Петрович\n")
    unclear = next(
        item for item in load_bid_packages(tmp_path, schema=schema, load_schema=False) if item.participant == "Бездоверенности"
    )
    assert unclear.part1.status == PART_REVIEW
    assert any("без доверенности" in item for item in unclear.part1.findings)
    assert parse_statement_xml("<ИНН>1</ИНН>", None).inn is None
