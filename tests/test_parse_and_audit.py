from datetime import date
from pathlib import Path

from kp_tz_check.checks import audit
from kp_tz_check.extract import ExtractedDoc
from kp_tz_check.models import DateCheckMark, FinalStatus, ProductCheckMark
from kp_tz_check.parse import parse_requests


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
