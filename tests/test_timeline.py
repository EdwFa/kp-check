from datetime import date
from pathlib import Path

from kp_tz_check.models import (
    DateCheckMark,
    FinalStatus,
    KpRecord,
    PairResult,
    ProductCheckMark,
    RequestRecord,
)
from kp_tz_check.timeline import build_timeline, extract_validity_days


def test_extract_validity_days():
    assert extract_validity_days("Срок действия предложения — 3 месяца") == 90


def test_timeline_checks_chronology_and_expiry():
    request = RequestRecord(
        source_file=Path("request.docx"),
        outgoing_no="1",
        sent_on=date(2026, 8, 1),
        sent_on_raw=None,
        supplier="ООО Поставщик",
        email=None,
    )
    kp = KpRecord(
        source_file=Path("offer.pdf"),
        prepared_on=date(2026, 8, 2),
        prepared_on_raw=None,
        registered_on=date(2026, 8, 2),
        registered_on_raw=None,
        supplier="ООО Поставщик",
        body="Срок действия предложения — 3 месяца",
    )
    result = PairResult(
        request=request,
        kp=kp,
        tz=None,
        date_mark=DateCheckMark.OK,
        product_mark=ProductCheckMark.UNKNOWN,
        status=FinalStatus.NEEDS_REVIEW,
        comments=[],
    )
    timeline = build_timeline([result])[0]
    assert timeline["status"] == "PASS"
    assert timeline["validity_days"] == 90
    assert timeline["events"][-1]["date"] == date(2026, 10, 31)
