from kp_tz_check.bids import PART_CRITICAL, PART_OK
from kp_tz_check.bids_part2 import check_part2
from kp_tz_check.competition import REGIME_CRITICAL

FORM = """Согласие (Форма 1)
Участник даёт согласие на включение сведений в РНП в соответствии с постановлением Правительства РФ № 1211 и ст. 5 Закона № 223-ФЗ.
Документ подписан ЭЦП.
"""

ROW = (
    "№ {no} | производитель: Завод | страна: {country} | ОКПД2: {code} | "
    "срок годности: {shelf}"
)


def test_complete_form_passes_and_missing_rnp_does_not():
    complete = check_part2(FORM, regime=[])
    assert complete["status"] == PART_OK
    assert complete["findings"] == []
    similar = check_part2("Согласие (Форма 1)\nДокумент подписан ЭЦП.\n", regime=[])
    assert similar["status"] == PART_CRITICAL
    assert any("нет согласия на включение в РНП" in item for item in similar["findings"])
    assert any("Форма 1" not in item for item in similar["findings"])


def test_missing_form_signature_and_title_are_separate_lines():
    report = check_part2("Текст без согласия.", regime=[])
    assert any("нет признаков формы 1" in item for item in report["findings"])
    assert any("нет согласия на включение в РНП" in item for item in report["findings"])
    assert any("нет признака подписи" in item for item in report["findings"])
    assert report["status"] == PART_CRITICAL


def test_shelf_life_and_okpd2_name_the_row():
    text = FORM + ROW.format(no="2", country="Россия", code="21.20.10.110", shelf="не менее 6 месяцев")
    tz = [{"no": "2", "specs": "срок годности не менее 12", "extra": {"okpd2": "32.50.13.190"}}]
    report = check_part2(text, tz, regime=[])
    assert any(item.startswith("Ошибка. Строка 2: срок годности") for item in report["findings"])
    assert any("Строка 2: код ОКПД2 «21.20.10.110» отличается от кода ТЗ" in item for item in report["findings"])
    assert report["status"] == PART_CRITICAL


def test_non_eaeu_country_with_measure_is_critical():
    text = FORM + ROW.format(no="1", country="Китай", code="32.50.13.190", shelf="12 месяцев")
    regime = [{"okpd2_prefix": "32.50", "measure": "ban", "source": "пример", "requires": ""}]
    report = check_part2(text, regime=regime)
    assert any(item.startswith(REGIME_CRITICAL) and "Строка 1" in item for item in report["findings"])
    assert report["status"] == PART_CRITICAL
    russia = check_part2(
        FORM + ROW.format(no="1", country="Россия", code="32.50.13.190", shelf="12 месяцев"),
        regime=regime,
    )
    assert not any(REGIME_CRITICAL in item for item in russia["findings"])


def test_catalog_remark_names_the_row_and_keeps_the_original_code():
    text = FORM + ROW.format(no="3", country="Россия", code="32.50.13.191", shelf="12 месяцев")
    catalog = [{"code": "32.50.13.190", "official_name": "Вымышленные наборы", "smp": "yes"}]
    report = check_part2(text, catalog=catalog, regime=[])
    assert any("Строка 3" in item and "32.50.13.191" in item and "32.50.13.190" in item for item in report["findings"])
    assert report["rows"][0]["okpd2"] == "32.50.13.191"
