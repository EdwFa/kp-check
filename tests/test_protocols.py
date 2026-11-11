from kp_tz_check.protocols import (
    PRICE_ADVICE,
    PROCEDURE_CRITICAL,
    QUORUM_UNCHECKED,
    SIGNING_REVIEW,
    STATUS_ATTENTION,
    STATUS_CRITICAL,
    STATUS_OK,
    check_protocol,
    load_protocols,
)


MEMBERS = [
    "Иванов Иван Иванович",
    "Петров Петр Петрович",
    "Сидоров Сидор Сидорович",
]
BID = {"name": "ООО Ромашка", "inn": "7701234567", "total": "90"}


def _protocol(price: str = "90", inn: str = "7701234567", ending: str = "") -> str:
    return f"""
Протокол № 12
Дата: 02.11.2026
Предмет: Поставка реагентов
НМЦК: 100
Состав: Иванов И.И., Петров П.П.
Участник: ООО Ромашка
ИНН: {inn}
Заявка № 5 от 01.11.2026
Решение: допущен
Основание: п. 1.18.1.1 Положения
Цена: {price}
{ending}
"""


def test_fields_and_decision_stay_verbatim():
    report = check_protocol(
        "Решение: отклонён\nОснование: пункт 1.14.2 Положения о закупке\n",
    )
    assert report["fields"]["decision"] == "отклонён"
    assert report["fields"]["basis"] == "пункт 1.14.2 Положения о закупке"
    assert report["decision_text"] == "отклонён. Основание: пункт 1.14.2 Положения о закупке"
    assert report["fields"]["number"] == ""
    assert report["fields"]["subject"] == ""
    assert report["quorum"] == QUORUM_UNCHECKED


def test_single_admitted_auction_without_failure_is_critical():
    report = check_protocol(
        _protocol(ending="Аукцион состоялся."),
        bid=BID,
        members=MEMBERS,
    )
    assert report["status"] == STATUS_CRITICAL
    assert PROCEDURE_CRITICAL in report["findings"]
    assert report["fields"]["number"] == "12"
    assert report["fields"]["participant"] == "ООО Ромашка"
    assert report["letter_sent"] is False
    assert report["draft_letter"] == ""


def test_failed_auction_with_lower_price_is_correct():
    report = check_protocol(
        _protocol(ending="Аукцион признан несостоявшимся.\nПроект договора передать единственному участнику."),
        bid=BID,
        members=MEMBERS,
    )
    assert report["status"] == STATUS_OK
    assert report["quorum"] == "кворум есть"
    assert any("10,00 руб." in item for item in report["notes"])
    assert PROCEDURE_CRITICAL not in report["findings"]
    assert report["letter_sent"] is False
    assert "Черновик не отправлен." in report["draft_letter"]
    assert "ООО Ромашка" in report["draft_letter"]


def test_price_equal_to_nmck_is_advice_not_an_error():
    report = check_protocol(
        _protocol(price="100", ending="Аукцион признан несостоявшимся.\nПроект договора передать единственному участнику."),
        bid={"name": "ООО Ромашка", "inn": "7701234567", "total": "100"},
        members=MEMBERS,
    )
    assert PRICE_ADVICE in report["findings"]
    assert report["status"] == STATUS_ATTENTION
    assert report["status"] != STATUS_CRITICAL
    assert "ошибка" not in PRICE_ADVICE
    assert report["letter_sent"] is False
    assert PRICE_ADVICE in report["draft_letter"]


def test_inn_or_sum_mismatch_needs_review_before_signing():
    inn = check_protocol(
        _protocol(inn="7700000000", ending="Аукцион признан несостоявшимся.\nПроект договора передать единственному участнику."),
        bid=BID,
        members=MEMBERS,
    )
    assert inn["status"] == STATUS_ATTENTION
    assert any(SIGNING_REVIEW in item and "7700000000" in item for item in inn["findings"])
    amount = check_protocol(
        _protocol(price="80", ending="Аукцион признан несостоявшимся.\nПроект договора передать единственному участнику."),
        bid=BID,
        members=MEMBERS,
    )
    assert any(SIGNING_REVIEW in item and "сумма" in item for item in amount["findings"])


def test_quorum_requires_the_approved_roster():
    missing = check_protocol(_protocol(ending="Аукцион признан несостоявшимся.\nПроект договора передать единственному участнику."), bid=BID)
    assert missing["quorum"] == QUORUM_UNCHECKED
    stranger = check_protocol(
        _protocol(ending="Аукцион признан несостоявшимся.\nПроект договора передать единственному участнику.").replace(
            "Иванов И.И.", "Кузнецов К.К."
        ),
        bid=BID,
        members=MEMBERS,
    )
    assert stranger["quorum"] == "фамилия не входит в утверждённый состав"


def test_empty_scan_is_not_checked(tmp_path):
    import fitz

    folder = tmp_path / "protocols"
    folder.mkdir()
    document = fitz.open()
    document.new_page()
    document.save(folder / "scan.pdf")
    document.close()
    (folder / "protocol.txt").write_text(_protocol(), encoding="utf-8")
    reports = {item["source_file"]: item for item in load_protocols(tmp_path, members=MEMBERS)}
    assert reports["scan.pdf"]["status"] == STATUS_ATTENTION
    assert "нужен OCR" in reports["scan.pdf"]["findings"]
    assert reports["scan.pdf"]["fields"]["number"] == ""
    assert reports["protocol.txt"]["fields"]["number"] == "12"
