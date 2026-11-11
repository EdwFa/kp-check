from datetime import date
from pathlib import Path

from docx import Document

from kp_tz_check.checks import audit
from kp_tz_check.extract import ExtractedDoc
from kp_tz_check.models import (
    ROW_INSUFFICIENT,
    ApplicationRecord,
    DateCheckMark,
    FinalStatus,
    ProductCheckMark,
)
from kp_tz_check.parse import load_incoming, parse_requests
from kp_tz_check.structure import structure_incoming


def test_parse_five_outgoing_letters():
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
    records = parse_requests(extracted)
    assert len(records) == 2
    assert records[0].outgoing_no == "2738"
    assert records[0].supplier == "ООО Апиген"
    assert records[0].sent_on == date(2026, 8, 27)
    assert records[1].email == "aps@sesana.ru"
    assert len(records[0].items) == 1


def test_missing_kp_is_mismatch_and_does_not_invent_dates():
    from kp_tz_check.models import Item, RequestRecord, TzRecord

    request = RequestRecord(
        source_file=Path("Запрос.docx"),
        outgoing_no="2738",
        sent_on=date(2026, 8, 27),
        sent_on_raw="27.08.2026",
        supplier="ООО Апиген",
        email="sales@apigene.ru",
    )
    tz = TzRecord(
        source_file=Path("ТЗ.doc"),
        title="ТЗ",
        items=[Item(no="1", name="Набор", specs="300 циклов", unit="шт.", qty="12")],
    )
    results = audit([request], [], [tz])
    assert len(results) == 1
    assert results[0].status == FinalStatus.MISMATCH
    assert results[0].date_mark == DateCheckMark.UNKNOWN
    assert results[0].product_mark == ProductCheckMark.FAIL
    assert any("нет соответствующего КП" in item for item in results[0].comments)


def _write_application(path: Path) -> None:
    document = Document()
    document.add_paragraph("Заявка на закупку наборов")
    table = document.add_table(rows=3, cols=10)
    headers = [
        "№ п/п",
        "Наименование",
        "Характеристика",
        "Ед. изм",
        "Кол-во",
        "Цена",
        "Скидка",
        "НДС",
        "Сумма",
        "ОКПД2",
    ]
    rows = [
        headers,
        ["1", "Набор тип 1", "300 циклов", "набор", "12", "1000,00", "0", "20%", "12000,00", "32.50.13.190"],
        ["2", "Набор тип 2", "150 циклов", "набор", "6", "500,00", "10%", "20%", "2700,00", ""],
    ]
    for row_index, values in enumerate(rows):
        for col_index, value in enumerate(values):
            table.rows[row_index].cells[col_index].text = value
    document.save(path)


def test_application_docx_keeps_price_fields_and_marks_missing_okpd2(tmp_path):
    folder = tmp_path / "applications"
    folder.mkdir()
    _write_application(folder / "Заявка.docx")
    requests, _kps, tzs, applications = load_incoming(tmp_path)
    assert requests == []
    assert tzs == []
    assert len(applications) == 1
    record = applications[0]
    assert isinstance(record, ApplicationRecord)
    assert "Заявка на закупку наборов" in record.body
    assert len(record.items) == 2
    complete, incomplete = record.items
    assert complete.extra["price"] == "1000,00"
    assert complete.extra["discount"] == "0"
    assert complete.extra["vat"] == "20%"
    assert complete.extra["line_sum"] == "12000,00"
    assert complete.extra["okpd2"] == "32.50.13.190"
    assert "row_status" not in complete.extra
    assert incomplete.extra["price"] == "500,00"
    assert incomplete.extra["okpd2"] == ""
    assert incomplete.extra["row_status"] == ROW_INSUFFICIENT


def test_missing_applications_folder_is_empty_list(tmp_path):
    requests, kps, tzs, applications = load_incoming(tmp_path)
    assert (requests, kps, tzs, applications) == ([], [], [], [])


def test_application_is_not_used_to_restore_tz(tmp_path):
    (tmp_path / "applications").mkdir()
    (tmp_path / "requests").mkdir()
    (tmp_path / "tz").mkdir()
    _write_application(tmp_path / "applications" / "Заявка.docx")
    document = Document()
    document.add_paragraph("Техническое задание без таблицы")
    document.save(tmp_path / "tz" / "ТЗ.docx")

    requests, _kps, tzs, applications = structure_incoming(tmp_path)
    assert requests == []
    assert tzs[0].items == []
    assert any("Таблица позиций ТЗ не прочитана" in note for note in tzs[0].notes)
    assert len(applications) == 1
    assert applications[0].items
    assert applications[0].source_file.name == "Заявка.docx"


def test_ne_menee_stays_an_uncertain_wording():
    from kp_tz_check.instruction import abbreviation_issues, enumeration_issue, vague_wording_issue
    from kp_tz_check.models import Item

    tz = Item(no="1", name="Набор", specs="объём данных, Гб 84; время секвенирования, ч 16", unit="шт", qty="1")
    kp = Item(no="1", name="Набор", specs="не менее 10", unit="шт", qty="1")
    issue = vague_wording_issue(tz, kp)
    assert issue is not None
    assert "неопределённая формулировка" in issue.detail
    assert abbreviation_issues("ПЦР", "ПЦР") == ["ПЦР"]
    assert abbreviation_issues("ПЦР", "ПЦР (полимеразная цепная реакция)") == []
    assert enumeration_issue(tz.specs, "10 и 20 мг")

