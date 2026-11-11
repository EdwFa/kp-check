from kp_tz_check.supplier_checks import check_suppliers, extract_requisites


def test_extract_requisites():
    values = extract_requisites("ИНН: 7701234567 КПП 770101001 ОГРН: 1027700132195")
    assert values == {
        "inn": "7701234567",
        "kpp": "770101001",
        "ogrn": "1027700132195",
    }


def test_supplier_conflict_is_fail():
    result = check_suppliers(
        [
            {
                "request": {"supplier": "ООО Заказчик"},
                "kp": {
                    "supplier": "ООО Другой поставщик",
                    "source_file": "offer.pdf",
                },
            }
        ],
        kps=[{"source_file": "offer.pdf", "body": "ИНН 7701234567"}],
    )
    assert result[0]["status"] == "FAIL"
    assert result[0]["supplier_conflict"]


def test_missing_requisites_require_review():
    result = check_suppliers(
        [
            {
                "request": {"supplier": "ООО Поставщик"},
                "kp": {
                    "supplier": "ООО Поставщик",
                    "source_file": "offer.pdf",
                },
            }
        ],
        kps=[{"source_file": "offer.pdf", "body": "ИНН 7701234567"}],
    )
    assert result[0]["status"] == "REVIEW"
    assert "KPP" in result[0]["missing"]
