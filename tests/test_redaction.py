import json

from kp_tz_check.redaction import build_contours


FIO = "Иванов Иван Иванович"


def test_both_contours_come_from_one_parse():
    source = {
        "customer": "Заказчик Пример",
        "director": FIO,
        "operator": FIO,
        "winner": {"name": "ООО Ромашка", "inn": "7701234567", "director": FIO},
        "items": [{"name": "Набор", "price": "100"}],
    }
    contours = build_contours(source)
    analytics = json.dumps(contours["analytics"], ensure_ascii=False)
    contract = json.dumps(contours["contract"], ensure_ascii=False)
    assert FIO not in analytics
    assert "Заказчик Пример" not in analytics
    assert "7701234567" not in analytics
    assert FIO in contract
    assert contours["contract"]["winner"]["inn"] == "7701234567"
    assert contours["analytics"]["items"] == contours["contract"]["items"]
    assert contours["journal_code"]
    assert FIO not in contours["journal_code"]
