from kp_tz_check.bids import load_bid_packages
from kp_tz_check.bids_part3 import (
    ADMITTED,
    ARITHMETIC,
    DEAL_EXPIRED,
    DEAL_LIMIT,
    DIRECTOR_MISMATCH,
    NEEDS_REVIEW,
    NMCK_REJECT,
    NO_RATE_RULE,
    OCR_NEEDED,
    REJECTED,
    VAT_REVIEW,
    check_part3,
)


STATEMENT = {
    "name": "ООО Ромашка",
    "inn": "7701234567",
    "kpp": "770101001",
    "ogrn": "1027700132195",
    "director": "Иванов Иван Иванович",
}
RATES = [{"okpd2_prefix": "32.50", "rates": "10"}]
LINE = "№ 1 | количество: 1 | цена: {price} | сумма: {price} | НДС: 10%"


class _Checked:
    def lookup(self, kind: str, key: str) -> dict:
        return {
            "status": "checked",
            "value": None,
            "source_url": "local",
            "checked_at": "2026-11-11",
        }


def _statuses(report: dict) -> set[str]:
    return {row["status"] for row in report["protocol"]}


def _clean() -> str:
    return """
Анкета
Наименование: ООО Ромашка
ИНН: 7701234567
КПП: 770101001
ОГРН: 1027700132195
ФИО директора: Иванов Иван Иванович
БИК: 044525225
Расчётный счёт: 40702810900000000001
Корреспондентский счёт: 30101810400000000225

Декларация
Наименование: ООО Ромашка
ИНН: 7701234567
КПП: 770101001
ОГРН: 1027700132195
ФИО директора: Иванов Иван Иванович
отсутствие ликвидации
нет банкротства
нет недоимки
нет судимости
нет конфликта интересов
нет статуса иностранного агента
отсутствие в РНП

Приказ
Наименование: ООО Ромашка
ИНН: 7701234567
КПП: 770101001
ОГРН: 1027700132195
ФИО директора: Иванов Иван Иванович

Крупная сделка
Дата решения: 01.01.2026
Срок: 18.02.2028
Лимит: 350000000
ФИО: Иванов Иван Иванович
Сумма заявки: 60000
Дата заявки: 02.11.2026
""" + LINE.format(price="60000") + """
Итого: 60000
прописью: 60000
"""


def test_total_above_nmck_rejects_the_bid():
    report = check_part3("Итого: 100", nmck=90, statement=STATEMENT)
    assert NMCK_REJECT in report["findings"]
    assert report["verdict"] == REJECTED
    assert report["admitted"] is False


def test_wrong_vat_rate_needs_review_and_is_not_replaced():
    line = "№ 1 | ОКПД2: 32.50.13.190 | НДС: 20%"
    report = check_part3(line, vat_table=RATES, statement=STATEMENT)
    row = next(item for item in report["protocol"] if item["status"] == VAT_REVIEW)
    assert "20%" in row["text"]
    assert "не заменена" in row["text"]
    assert report["verdict"] != ADMITTED
    assert "20%" in line


def test_unknown_okpd2_prefix_has_no_rate_rule():
    report = check_part3(
        "№ 1 | ОКПД2: 99.99.99 | НДС: 20%",
        vat_table=RATES,
        statement=STATEMENT,
    )
    assert NO_RATE_RULE in _statuses(report)
    assert VAT_REVIEW not in _statuses(report)


def test_written_total_is_compared_only_when_extracted():
    body = LINE.format(price="100") + "\nИтого: 100\nпрописью: 90,00"
    compared = check_part3(body, statement=STATEMENT)
    assert compared["math"]["written_total"]
    assert ARITHMETIC in _statuses(compared)
    assert any("прописью" in item for item in compared["findings"])
    missing = check_part3(LINE.format(price="100") + "\nИтого: 100", statement=STATEMENT)
    assert missing["math"]["written_status"] == "не извлечено"
    assert ARITHMETIC not in _statuses(missing)


def test_large_deal_limit_and_term():
    ok = check_part3(
        """
Крупная сделка
Лимит: 350000000
Сумма заявки: 60000
Срок: 18.02.2028
Дата заявки: 02.11.2026
""",
        statement=STATEMENT,
    )
    assert "Корректно" in _statuses(ok)
    assert DEAL_LIMIT not in _statuses(ok)
    assert DEAL_EXPIRED not in _statuses(ok)
    expired = check_part3(
        """
Крупная сделка
Лимит: 350000000
Сумма заявки: 60000
Срок: 01.01.2026
Дата заявки: 02.11.2026
""",
        statement=STATEMENT,
    )
    assert DEAL_EXPIRED in _statuses(expired)
    assert expired["verdict"] == REJECTED


def test_empty_scan_needs_ocr_and_keeps_fields_empty():
    report = check_part3("", pdf_empty=True, statement=STATEMENT)
    assert OCR_NEEDED in report["findings"]
    assert report["verdict"] == NEEDS_REVIEW
    assert report["extracted"] == {"decision_date": "", "until": "", "limit": "", "decision_fio": ""}
    blank = check_part3("Крупная сделка\nРешение без атрибутов.", statement=STATEMENT)
    assert blank["extracted"] == {"decision_date": "", "until": "", "limit": "", "decision_fio": ""}
    assert DEAL_EXPIRED not in _statuses(blank)


def test_decision_fio_is_compared_with_part1_director():
    report = check_part3(
        """
Крупная сделка
ФИО: Петров Петр Петрович
Лимит: 350000000
Сумма заявки: 60000
""",
        statement=STATEMENT,
    )
    assert DIRECTOR_MISMATCH in _statuses(report)
    assert any("Петров" in item and "Иванов" in item for item in report["findings"])


def test_bik_length_and_inn_mismatch():
    bank = check_part3(
        """
Анкета
БИК: 04452522
Расчётный счёт: 40702810900000000001
Корреспондентский счёт: 30101810400000000225
""",
        statement=STATEMENT,
    )
    assert any("БИК" in item and "8" in item for item in bank["findings"])
    assert any(row["status"] == "Корректно" and "20" in row["text"] for row in bank["protocol"])
    inn = check_part3(
        "Анкета\nИНН: 7700000000\n",
        statement=STATEMENT,
    )
    assert any("ИНН" in item and "7700000000" in item for item in inn["findings"])


def test_registry_off_blocks_admission_until_a_critical_error():
    quiet = check_part3(_clean(), statement=STATEMENT)
    assert quiet["verdict"] == NEEDS_REVIEW
    assert quiet["admitted"] is False
    assert any("не подтверждает факт" in row["text"] for row in quiet["protocol"])
    assert all(row["status"] == "not_checked" for row in quiet["registry"])
    opened = check_part3(_clean(), statement=STATEMENT, registry=_Checked())
    assert opened["verdict"] == ADMITTED
    assert opened["admitted"] is True
    rejected = check_part3("Итого: 100", nmck=90, statement=STATEMENT)
    assert rejected["verdict"] == REJECTED
    assert ADMITTED not in _statuses(rejected)


def test_protocol_keeps_the_named_statuses_separate():
    seen = set()
    seen.update(_statuses(check_part3(_clean(), statement=STATEMENT, registry=_Checked())))
    seen.update(_statuses(check_part3(LINE.format(price="100") + "\nИтого: 100\nпрописью: 90,00", statement=STATEMENT)))
    seen.update(
        _statuses(
            check_part3(
                "Крупная сделка\nСрок: 01.01.2026\nДата заявки: 02.11.2026\n",
                statement=STATEMENT,
            )
        )
    )
    seen.update(
        _statuses(
            check_part3(
                "Крупная сделка\nЛимит: 50000\nСумма заявки: 60000\n",
                statement=STATEMENT,
            )
        )
    )
    seen.update(
        _statuses(
            check_part3(
                "Крупная сделка\nФИО: Петров Петр Петрович\n",
                statement=STATEMENT,
            )
        )
    )
    assert {"Корректно", ARITHMETIC, DEAL_EXPIRED, DEAL_LIMIT, DIRECTOR_MISMATCH} <= seen


def test_scan_without_text_layer_is_not_ok(tmp_path):
    import fitz

    folder = tmp_path / "bids" / "Ромашка" / "part3"
    folder.mkdir(parents=True)
    document = fitz.open()
    document.new_page()
    document.save(folder / "scan.pdf")
    document.close()
    package = load_bid_packages(tmp_path)[0]
    assert package.part3.status == NEEDS_REVIEW
    assert any(OCR_NEEDED in item for item in package.part3.findings)
    assert package.part3.status != ADMITTED
