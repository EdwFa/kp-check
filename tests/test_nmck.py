from pathlib import Path

from docx import Document

from kp_tz_check.blocks import NMCK_JUSTIFICATION, build_blocks
from kp_tz_check.calculations import calculate_market_statistics, check_antidumping, money_format_issue, parse_money
from kp_tz_check.calculations_alt import calculate_market_statistics_alt, reconcile_statistics
from kp_tz_check.extract import ExtractedDoc
from kp_tz_check.models import BlockStatus
from kp_tz_check.nmck import HETEROGENEOUS, build_nmck_report
from kp_tz_check.parse import load_nmck, parse_nmck


def _offer(supplier: str, price: str, *, name: str = "Реагент", filename: str | None = None) -> dict:
    return {
        "supplier": supplier,
        "source_file": filename or f"{supplier}.docx",
        "body": "",
        "items": [
            {
                "no": "1",
                "name": name,
                "qty": "1",
                "unit": "шт",
                "extra": {"price": price, "price_kind": "price_unit", "vat": "20%"},
            }
        ],
    }


def test_nmck_match_is_by_supplier_and_position_not_row_order():
    record = {
        "source_file": "обоснование.docx",
        "items": [
            {"no": "1", "name": "Реагент", "extra": {"supplier": "Гамма", "price": "999,00"}},
            {"no": "1", "name": "Реагент", "extra": {"supplier": "Альфа", "price": "100,00"}},
            {"no": "1", "name": "Реагент", "extra": {"supplier": "Бета", "price": "100,00"}},
        ],
    }
    offers = [
        _offer("Альфа", "100,00"),
        _offer("Гамма", "100,00"),
        _offer("Бета", "100,00"),
    ]
    report = build_nmck_report(offers, nmck_records=[record])
    assert report["justification_checked"] is True
    assert len(report["justification_diffs"]) == 1
    assert report["justification_diffs"][0]["supplier"] == "Гамма"
    assert "цена обоснования не найдена в КП" in report["justification_diffs"][0]["text"]


def test_cv_threshold_is_strictly_greater_than_33():
    low = calculate_market_statistics([100, 100, 101])
    high = calculate_market_statistics([50, 100, 150])
    assert low["status"] == "homogeneous"
    assert high["status"] == "heterogeneous"
    exact = calculate_market_statistics([10, 20, 30], threshold=calculate_market_statistics([10, 20, 30])["coefficient_of_variation"])
    assert exact["status"] == "homogeneous"
    assert calculate_market_statistics_alt([100, 100, 101])["status"] == "homogeneous"
    assert calculate_market_statistics_alt([50, 100, 150])["status"] == "heterogeneous"


def test_two_statistics_agree_and_reconciler_catches_desync():
    values = [10, 20, 30]
    primary = calculate_market_statistics(values)
    alternate = calculate_market_statistics_alt(values)
    agreed = reconcile_statistics(primary, alternate)
    assert agreed["status"] == "agreed"
    assert "Формула" in agreed["text"]
    assert f"n = {agreed['n']}" in agreed["text"]
    assert "Среднее" in agreed["text"] and "σ" in agreed["text"] and "V " in agreed["text"]
    shifted = dict(alternate)
    shifted["mean"] = alternate["mean"] + 1
    shifted["coefficient_of_variation"] = alternate["coefficient_of_variation"] + 1
    conflict = reconcile_statistics(primary, shifted)
    assert conflict["status"] == "manual_review"
    assert "требует ручной проверки" in conflict["text"].lower()
    assert conflict["primary"]["mean"] != conflict["alternate"]["mean"]


def test_heterogeneous_finding_contains_formula_and_exact_phrase():
    offers = [_offer("Альфа", "10"), _offer("Бета", "10"), _offer("Гамма", "100")]
    block = build_blocks({"kps": offers})[3]
    assert block.status == BlockStatus.REMARKS
    cv = next(item for item in block.findings if item.code == "nmck-cv")
    assert HETEROGENEOUS in cv.text
    for token in ("Формула", "n =", "Среднее", "σ", "V "):
        assert token in cv.text
    assert any(NMCK_JUSTIFICATION in item.text for item in block.findings)


def test_antidumping_threshold_and_missing_nmck():
    assert check_antidumping(70, 100) is not None
    assert "1.9.23" in check_antidumping(70, 100)["text"]
    assert check_antidumping(75, 100) is not None
    assert check_antidumping(80, 100) is None
    assert check_antidumping(70, None) is None
    report = build_nmck_report([_offer("Альфа", "70")])
    assert all(not row["antidumping"] for row in report["rows"])


def test_money_format_remark_keeps_parsed_number():
    assert money_format_issue("12450.00")
    assert money_format_issue("12 450,00") is None
    assert parse_money("12450.00") == 12450
    report = build_nmck_report([_offer("Альфа", "12450.00"), _offer("Бета", "12 450,00"), _offer("Гамма", "12 450,00")])
    assert any("12450.00" in item["text"] for item in report["format_notes"])
    assert any("12 450" in item["text"] or "12450" in item["text"] for item in report["format_notes"])


def test_missing_security_document_asks_for_clarification():
    offers = [_offer(name, "70") for name in ("Альфа", "Бета", "Гамма")]
    offers.append(_offer("Дельта", "100"))
    report = build_nmck_report(offers[:3])
    # Три одинаковые низкие цены не ниже своей же средней.
    high = build_nmck_report(
        [_offer("Альфа", "100"), _offer("Бета", "100"), _offer("Гамма", "100"), _offer("Дельта", "60")]
    )
    texts = " ".join(flag["text"] for row in high["rows"] for flag in row["antidumping"])
    assert "Дельта" in texts
    assert "требует уточнения" in texts
    assert "нарушение" not in texts.lower()


def test_without_justification_file_recalculation_stays_visible():
    offers = [_offer("Альфа", "100"), _offer("Бета", "100"), _offer("Гамма", "100")]
    report = build_nmck_report(offers)
    assert report["justification_note"] == NMCK_JUSTIFICATION
    assert report["rows"]
    assert report["rows"][0]["unit_nmck"] == 100
    block = build_blocks({"kps": offers})[3]
    assert block.status == BlockStatus.REMARKS
    assert block.reason == NMCK_JUSTIFICATION


def test_parse_nmck_keeps_supplier_price_without_quantity():
    extracted = ExtractedDoc(
        path=Path("обоснование.docx"),
        paragraphs=["НМЦК = средняя цена. Итого 300,00"],
        tables=[
            [
                ["Позиция", "Поставщик", "Цена"],
                ["Реагент", "Альфа", "100,00"],
                ["Реагент", "Бета", "200,00"],
            ]
        ],
    )
    record = parse_nmck(extracted)
    assert [item.extra["supplier"] for item in record.items] == ["Альфа", "Бета"]
    assert record.items[0].extra["price"] == "100,00"
    assert "НМЦК" in record.formula
    assert record.declared_total == "300,00"


def test_load_nmck_reads_folder(tmp_path: Path):
    folder = tmp_path / "nmck"
    folder.mkdir()
    document = Document()
    document.add_paragraph("Формула НМЦК")
    table = document.add_table(rows=2, cols=3)
    for index, value in enumerate(["Наименование", "Поставщик", "Цена"]):
        table.rows[0].cells[index].text = value
    for index, value in enumerate(["Реагент", "Альфа", "100,00"]):
        table.rows[1].cells[index].text = value
    document.save(folder / "обоснование.docx")
    loaded = load_nmck(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].items[0].extra["supplier"] == "Альфа"
    assert load_nmck(tmp_path / "missing") == []
