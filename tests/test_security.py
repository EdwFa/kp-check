from kp_tz_check.blocks import build_blocks
from kp_tz_check.models import BlockStatus
from kp_tz_check.security import evaluate_security


def test_security_boundaries():
    cases = [
        ({"nmck_total": 5_000_000, "smp": False, "application_percent": 5, "contract_percent": 5, "advance": 10, "advance_security": 10}, "ОК"),
        ({"nmck_total": 4_999_999.99, "smp": False, "application_percent": 5, "contract_percent": 5, "advance": None, "advance_security": None}, "НЕ ПРИМЕНЯЕТСЯ"),
        ({"nmck_total": 5_000_000, "smp": True, "application_percent": 2, "contract_percent": 5, "advance": 1, "advance_security": 1}, "ОК"),
        ({"nmck_total": 5_000_000, "smp": True, "application_percent": 2.01, "contract_percent": 5, "advance": 1, "advance_security": 1}, "ОШИБКА"),
        ({"nmck_total": 5_000_000, "smp": False, "application_percent": 5, "contract_percent": 30, "advance": 1, "advance_security": 1}, "ОК"),
        ({"nmck_total": 5_000_000, "smp": False, "application_percent": 5, "contract_percent": 30.01, "advance": 1, "advance_security": 1}, "ОШИБКА"),
        ({"nmck_total": 5_000_000, "smp": None, "application_percent": 2, "contract_percent": 5, "advance": 1, "advance_security": 1}, "ТРЕБУЕТ УТОЧНЕНИЯ"),
        ({"nmck_total": None, "smp": False, "application_percent": 5, "contract_percent": 5, "advance": 1, "advance_security": 2}, "ТРЕБУЕТ УТОЧНЕНИЯ"),
    ]
    for kwargs, expected in cases:
        rows = evaluate_security(**kwargs)
        assert any(row["status"] == expected for row in rows)


def test_block_security_can_be_ok_or_error():
    ok = build_blocks(
        {
            "requests": [{"source_file": "Запрос.docx", "body": "Обеспечение заявки 5%. Обеспечение исполнения контракта 10%."}],
            "nmck_total": 5_000_000,
            "smp": False,
        }
    )[7]
    assert any(item.text.startswith("ОК:") for item in ok.findings)
    assert ok.status == BlockStatus.REMARKS
    error = build_blocks(
        {
            "requests": [{"source_file": "Запрос.docx", "body": "Обеспечение заявки 6%."}],
            "nmck_total": 5_000_000,
            "smp": False,
        }
    )[7]
    assert error.status == BlockStatus.CRITICAL
    assert any(item.text.startswith("ОШИБКА:") for item in error.findings)
