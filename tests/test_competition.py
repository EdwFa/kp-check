from kp_tz_check.blocks import build_blocks
from kp_tz_check.competition import REGIME_CRITICAL, REGIME_NOT_LOADED, build_competition_report
from kp_tz_check.models import BlockStatus, FindingSeverity


def _kp(supplier: str, manufacturer: str | None, country: str | None, *, code: str = "32.50.13.190") -> dict:
    extra = {"okpd2": code, "price": "100", "price_kind": "price_unit", "vat": "20%"}
    if manufacturer is not None:
        extra["manufacturer"] = manufacturer
    if country is not None:
        extra["country"] = country
    return {
        "supplier": supplier,
        "source_file": f"{supplier}.docx",
        "body": "",
        "items": [{"no": "1", "name": "Набор", "qty": "1", "unit": "шт", "specs": "", "extra": extra}],
    }


CATALOG = [{"okpd2_prefix": "32.50", "measure": "ban", "source": "пример", "requires": ""}]


def test_two_manufacturers_have_no_diversity_remark():
    report = build_competition_report(
        [_kp("А", "Завод 1", "Россия"), _kp("Б", "Завод 2", "Россия"), _kp("В", "Завод 1", "Россия")],
        catalog=CATALOG,
        load_catalog=False,
    )
    assert report["rows"][0]["manufacturer_count"] == 2
    assert "Завод 1" in report["rows"][0]["manufacturers"]
    assert "Завод 2" in report["rows"][0]["manufacturers"]
    assert not any("уникальных производителей" in item["text"] for item in report["findings"])


def test_one_manufacturer_is_a_remark_with_verbatim_name():
    report = build_competition_report(
        [_kp("А", "Завод 1", "Россия"), _kp("Б", "Завод 1", "Россия"), _kp("В", "Завод 1", "Россия")],
        catalog=CATALOG,
        load_catalog=False,
    )
    assert report["rows"][0]["manufacturer_count"] == 1
    text = " ".join(item["text"] for item in report["findings"])
    assert "уникальных производителей 1" in text
    assert "Завод 1" in text
    assert "А" not in report["rows"][0]["manufacturers"]


def test_empty_manufacturer_is_insufficient_and_supplier_is_not_used():
    report = build_competition_report(
        [_kp("ООО Ромашка", None, "Россия")],
        catalog=CATALOG,
        load_catalog=False,
    )
    text = " ".join(item["text"] for item in report["findings"])
    assert "недостаточно данных" in text
    assert "ООО Ромашка" not in text


def test_regime_critical_only_for_measure_and_non_eaeu_country():
    china = build_competition_report([_kp("А", "Завод", "Китай"), _kp("Б", "Другой", "Китай")], catalog=CATALOG, load_catalog=False)
    russia = build_competition_report([_kp("А", "Завод", "Россия"), _kp("Б", "Другой", "Россия")], catalog=CATALOG, load_catalog=False)
    empty = build_competition_report([_kp("А", "Завод", None), _kp("Б", "Другой", None)], catalog=CATALOG, load_catalog=False)
    assert any(REGIME_CRITICAL in item["text"] for item in china["findings"])
    assert not any(REGIME_CRITICAL in item["text"] for item in russia["findings"])
    assert not any(REGIME_CRITICAL in item["text"] for item in empty["findings"])
    assert not any("иностранн" in item["text"].lower() for item in empty["findings"])
    assert any("недостаточно данных" in item["text"] for item in empty["findings"])


def test_missing_catalog_is_written_and_block_is_not_clean(monkeypatch):
    monkeypatch.delenv("KP_NATIONAL_REGIME_CATALOG", raising=False)
    block = build_blocks({"kps": [_kp("А", "Завод", "Китай")], "tzs": [{"source_file": "ТЗ.doc", "items": [{"no": "1", "name": "Набор"}]}]})[2]
    assert block.status == BlockStatus.REMARKS
    assert block.status != BlockStatus.CLEAN
    assert any(REGIME_NOT_LOADED in item.text for item in block.findings)
    assert not any(item.severity == FindingSeverity.CRITICAL for item in block.findings)


def test_critical_regime_raises_block_and_conclusion():
    block = build_blocks(
        {
            "kps": [_kp("А", "Завод", "Китай"), _kp("Б", "Другой", "Китай")],
            "national_regime": CATALOG,
        }
    )[2]
    assert block.status == BlockStatus.CRITICAL
    assert any(REGIME_CRITICAL in item.text for item in block.findings)


def test_address_is_not_country_of_origin():
    from kp_tz_check.extract import ExtractedDoc
    from kp_tz_check.parse import parse_kp

    extracted = ExtractedDoc(
        path=__import__("pathlib").Path("кп.docx"),
        paragraphs=["Адрес поставщика: г. Москва", "Производитель: Завод"],
        tables=[[
            ["№", "Наименование", "Кол-во", "Цена"],
            ["1", "Набор", "1", "100"],
        ]],
    )
    record = parse_kp(extracted)
    assert record.items
    assert "country" not in record.items[0].extra
    assert record.items[0].extra.get("manufacturer") == "Завод"


def test_country_column_is_read():
    from pathlib import Path

    from kp_tz_check.extract import ExtractedDoc
    from kp_tz_check.parse import parse_kp

    extracted = ExtractedDoc(
        path=Path("кп.docx"),
        paragraphs=[],
        tables=[[
            ["№", "Наименование", "Кол-во", "Страна происхождения", "Цена"],
            ["1", "Набор", "1", "Китай", "100"],
        ]],
    )
    record = parse_kp(extracted)
    assert record.items[0].extra["country"] == "Китай"

