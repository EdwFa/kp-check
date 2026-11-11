from kp_tz_check.application_math import check_application, check_line
from kp_tz_check.blocks import build_blocks
from kp_tz_check.models import BlockStatus, FindingSeverity


def _line(*, qty: str = "2", price: str = "10", line_sum: str = "20,00", vat: str = "20%", **extra: str) -> dict:
    payload = {"price": price, "price_kind": "price_unit", "line_sum": line_sum, "vat": vat}
    payload.update(extra)
    return {"no": "1", "name": "Набор", "qty": qty, "unit": "шт", "extra": payload}


def test_line_vat_is_included_in_total():
    result = check_line(_line())
    assert result["status"] == "ок"
    assert float(result["net"]) == 20
    assert result["vat_amount"] == 3.33


def test_line_sum_mismatch_is_substantive_and_kopeck_is_technical():
    wrong = check_line(_line(line_sum="21,00"))
    assert wrong["status"] == "содержательная ошибка"
    kopeck = check_line(_line(line_sum="20,01"))
    assert kopeck["status"] == "техническое расхождение"


def test_discount_needs_both_percent_and_sum():
    incomplete = check_line(_line(discount="10%"))
    assert incomplete["status"] == "недостаточно данных"
    assert "Скидка" in incomplete["note"]
    complete = check_line(_line(line_sum="18,00", discount_percent="10%", discount_sum="2,00"))
    assert complete["status"] == "ок"
    assert float(complete["net"]) == 18


def test_forward_and_backward_totals_match():
    report = check_application(
        {
            "source_file": "заявка.docx",
            "body": "Итого 40,00\nпрописью: 40,00",
            "items": [
                _line(),
                _line(price="10", line_sum="20,00"),
            ],
        }
    )
    assert report["forward_total"] == report["backward_total"] == 40
    assert report["written_status"] == "ок"
    assert report["status"] == "ок"


def test_vat_rate_is_not_taken_from_okpd2():
    result = check_line(_line(vat="", okpd2="32.50.13"))
    assert result["vat_amount"] is None
    assert "Ставка НДС" in result["note"]


def test_block_five_mentions_application_and_keeps_kp_section():
    application = {
        "source_file": "заявка.docx",
        "body": "Итого 20,00",
        "items": [_line()],
    }
    offer = {
        "supplier": "Альфа",
        "source_file": "кп.docx",
        "body": "Итого 10,00",
        "items": [
            {
                "no": "1",
                "name": "Набор",
                "qty": "2",
                "unit": "шт",
                "extra": {"price": "10", "price_kind": "price_unit", "vat": "20%"},
            }
        ],
    }
    block = build_blocks({"kps": [offer], "applications": [application]})[4]
    assert "заявк" in (block.reason or "").lower()
    assert "отдельная секция" in (block.reason or "")
    assert any(item.code == "kp-total" and item.severity == FindingSeverity.CRITICAL for item in block.findings)
    assert block.status == BlockStatus.CRITICAL
