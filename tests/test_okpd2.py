from kp_tz_check.blocks import build_blocks
from kp_tz_check.models import BlockStatus
from kp_tz_check.okpd2 import check_catalog_codes


CATALOG = [
    {"code": "32.50.13.190", "official_name": "Вымышленные наборы для анализа", "smp": "yes"},
    {"code": "21.20.10.110", "official_name": "Вымышленные реагенты", "smp": "no"},
]


def test_catalog_flags_missing_short_name_and_smp():
    result = check_catalog_codes(
        [
            {"name": "Другое имя", "extra": {"okpd2": "32.50.13.190"}, "source": "заявка"},
            {"name": "Короткий", "extra": {"okpd2": "32.50.13"}, "source": "заявка"},
            {"name": "Нет кода", "extra": {"okpd2": "99.99.99.999"}, "source": "тз"},
        ],
        CATALOG,
    )
    texts = " ".join(item["text"] for item in result["findings"])
    assert "не совпало" in texts
    assert "неполный" in texts
    assert "отсутствует" in texts
    assert result["smp_count"] == 1
    assert result["smp"] is None


def test_typo_shows_candidate_and_keeps_original():
    result = check_catalog_codes(
        [{"name": "Набор", "extra": {"okpd2": "32.50.13.191"}, "source": "заявка"}],
        CATALOG,
    )
    text = result["findings"][0]["text"]
    assert "32.50.13.191" in text
    assert "32.50.13.190" in text
    assert "не заменён" in text


def test_page_block_comes_from_session_catalog():
    block = build_blocks(
        {
            "applications": [
                {
                    "source_file": "заявка.docx",
                    "items": [
                        {
                            "name": "Вымышленные наборы для анализа",
                            "extra": {"okpd2": "32.50.13.190"},
                        }
                    ],
                }
            ],
            "okpd2_catalog": CATALOG,
        }
    )[5]
    assert block.status == BlockStatus.CLEAN
    assert any("Позиций СМП: 1" in item.text for item in block.findings)
