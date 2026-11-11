import pytest

from kp_tz_check.blocks import (
    KP_ARITHMETIC,
    NMCK_JUSTIFICATION,
    OKPD_CATALOG,
    build_blocks,
)
from kp_tz_check.models import (
    BLOCK_TITLES,
    BlockFinding,
    BlockId,
    BlockResult,
    BlockStatus,
    ConclusionVerdict,
    FindingSeverity,
    PackConclusion,
    build_conclusion,
    parse_block_status,
)
from kp_tz_check.serde import from_jsonable, to_jsonable


def _block(block_id: BlockId, status: BlockStatus, *, reason: str | None = None) -> BlockResult:
    return BlockResult(block_id, BLOCK_TITLES[block_id], status, reason=reason)


def _all(status: BlockStatus) -> list[BlockResult]:
    return [_block(block_id, status) for block_id in BlockId]


def test_block_conclusion_roundtrip():
    original = build_conclusion(
        [
            BlockResult(
                BlockId.PACKAGE,
                BLOCK_TITLES[BlockId.PACKAGE],
                BlockStatus.REMARKS,
                findings=[
                    BlockFinding(
                        "dates",
                        "Дата подготовки не прочитана",
                        "incoming/kp/a.docx",
                        FindingSeverity.REMARK,
                    )
                ],
            )
        ]
    )
    restored = from_jsonable(PackConclusion, to_jsonable(original))
    assert restored == original
    assert restored.blocks[0].findings[0].source == "incoming/kp/a.docx"
    assert restored.blocks[0].findings[0].severity == FindingSeverity.REMARK


def test_unknown_block_status_is_rejected():
    with pytest.raises(ValueError, match="Неизвестный статус"):
        parse_block_status("замечаний нет")
    with pytest.raises(ValueError):
        from_jsonable(
            BlockResult,
            {
                "block_id": "1",
                "title": "Комплектность",
                "status": "ок",
            },
        )


def test_unchecked_blocks_block_clean_verdict():
    blocks = _all(BlockStatus.CLEAN)
    for block_id in (BlockId.BASELINE, BlockId.COMPETITION, BlockId.NPA):
        blocks[int(block_id.value) - 1] = _block(block_id, BlockStatus.NOT_CHECKED)
    conclusion = build_conclusion(blocks)
    assert conclusion.verdict == ConclusionVerdict.REWORK
    assert conclusion.verdict_reason == "блоки не закрыты: 2, 3, 7"
    assert all(block.status != BlockStatus.CLEAN for block in conclusion.blocks if block.block_id in {
        BlockId.BASELINE,
        BlockId.COMPETITION,
        BlockId.NPA,
    })


def test_missing_block_is_not_treated_as_clean():
    conclusion = build_conclusion(_all(BlockStatus.CLEAN)[:7])
    assert conclusion.verdict == ConclusionVerdict.REWORK
    assert "8" in conclusion.verdict_reason
    assert conclusion.blocks[-1].status == BlockStatus.NOT_CHECKED


def test_all_clean_blocks_can_pass():
    conclusion = build_conclusion(_all(BlockStatus.CLEAN))
    assert conclusion.verdict == ConclusionVerdict.PASS
    assert len(conclusion.blocks) == 8


def test_remark_keeps_rework_even_without_unchecked_blocks():
    blocks = _all(BlockStatus.CLEAN)
    blocks[3] = _block(BlockId.NMCK, BlockStatus.REMARKS, reason="коэффициент вариации выше 33%")
    conclusion = build_conclusion(blocks)
    assert conclusion.verdict == ConclusionVerdict.REWORK
    assert conclusion.verdict_reason == "есть замечания по блокам: 4"
    assert conclusion.clarifications[0].text == "коэффициент вариации выше 33%"


def test_critical_status_is_not_a_pass():
    blocks = _all(BlockStatus.CLEAN)
    blocks[0] = _block(BlockId.PACKAGE, BlockStatus.CRITICAL, reason="нет КП на запрос")
    conclusion = build_conclusion(blocks)
    assert conclusion.verdict == ConclusionVerdict.COMMISSION
    assert conclusion.critical_risks == ["нет КП на запрос"]


def test_duplicate_block_is_rejected():
    with pytest.raises(ValueError, match="дважды"):
        build_conclusion([_block(BlockId.PACKAGE, BlockStatus.CLEAN), _block(BlockId.PACKAGE, BlockStatus.REMARKS)])


def test_empty_state_has_eight_blocks_and_no_clean_status():
    blocks = build_blocks({})
    assert [block.block_id for block in blocks] == list(BlockId)
    assert all(block.status != BlockStatus.CLEAN for block in blocks)
    for block in blocks:
        assert block.findings
        assert all(finding.source for finding in block.findings)


def test_audit_fixture_maps_missing_kp_to_critical_package_block():
    from datetime import date
    from pathlib import Path

    from kp_tz_check.checks import audit
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
    blocks = build_blocks({"results": results, "requests": [request], "kps": [], "tzs": [tz]})
    assert len(blocks) == 8
    assert blocks[0].status == BlockStatus.CRITICAL
    assert blocks[0].findings[0].source == "Запрос.docx"
    assert blocks[1].status == BlockStatus.REMARKS
    assert blocks[1].reason == "Заявка не предоставлена."
    assert any("Заявка не предоставлена" in finding.text for finding in blocks[1].findings)
    assert blocks[2].status == BlockStatus.REMARKS
    assert any("перечень № 1875 не загружен" in finding.text for finding in blocks[2].findings)
    assert blocks[6].status == BlockStatus.NOT_CHECKED
    assert all(block.status != BlockStatus.CLEAN for block in blocks)


def test_matching_pair_can_be_clean_while_other_blocks_stay_open():
    pair = {
        "status": "Соответствует",
        "comments": ["Хронология дат соблюдена", "Позиции ТЗ соответствуют КП"],
        "request": {"source_file": "Запрос.docx"},
        "kp": {"source_file": "КП.docx"},
    }
    blocks = build_blocks({"results": [pair]})
    assert blocks[0].status == BlockStatus.CLEAN
    assert blocks[3].status == BlockStatus.REMARKS
    assert blocks[4].status == BlockStatus.REMARKS
    assert NMCK_JUSTIFICATION in blocks[3].findings[0].text
    assert KP_ARITHMETIC in (blocks[4].reason or "")


def test_nmck_heterogeneous_prices_stay_remarks():
    offers = [
        _offer("a.docx", "А", "10"),
        _offer("b.docx", "Б", "10"),
        _offer("c.docx", "В", "100"),
    ]
    block = build_blocks({"kps": offers})[3]
    assert block.status == BlockStatus.REMARKS
    assert any("неоднородная совокупность цен" in finding.text for finding in block.findings)
    assert any(NMCK_JUSTIFICATION in finding.text for finding in block.findings)


def test_homogeneous_nmck_still_not_clean_without_justification_file():
    offers = [
        _offer("a.docx", "А", "100"),
        _offer("b.docx", "Б", "100"),
        _offer("c.docx", "В", "100"),
    ]
    block = build_blocks({"kps": offers})[3]
    assert block.status == BlockStatus.REMARKS
    assert any(NMCK_JUSTIFICATION in finding.text for finding in block.findings)
    assert not any("неоднородная совокупность цен" in finding.text for finding in block.findings)


def test_kp_total_mismatch_is_critical_and_labeled_as_kp_math():
    offer = _offer("a.docx", "А", "10", qty="2", body="Итого 10,00")
    block = build_blocks({"kps": [offer]})[4]
    assert block.status == BlockStatus.CRITICAL
    assert block.reason == KP_ARITHMETIC
    assert any(finding.severity == FindingSeverity.CRITICAL for finding in block.findings)


def test_matching_okpd_cannot_pass_without_smp_catalog():
    requests = [{"source_file": "Запрос.docx", "body": "ОКПД2 32.50.13"}]
    tzs = [{"source_file": "ТЗ.doc", "title": "ТЗ", "body": "ОКПД2 32.50.13"}]
    block = build_blocks({"requests": requests, "tzs": tzs})[5]
    assert block.status == BlockStatus.NOT_CHECKED
    assert block.reason == OKPD_CATALOG
    assert any("совпадают" in finding.text for finding in block.findings)


def test_security_without_requirements_is_not_checked():
    block = build_blocks({"requests": [{"source_file": "Запрос.docx", "body": "Просим КП"}]})[7]
    assert block.status == BlockStatus.NOT_CHECKED
    assert block.reason == "Требования к обеспечению не найдены."


def test_security_percent_without_nmck_needs_clarification():
    block = build_blocks(
        {"requests": [{"source_file": "Запрос.docx", "body": "Обеспечение заявки 5%"}]}
    )[7]
    assert block.status == BlockStatus.REMARKS
    assert "ТРЕБУЕТ УТОЧНЕНИЯ" in (block.reason or "")
    assert "REVIEW" not in (block.reason or "")
    assert block.findings[0].source == "Запрос.docx"


def _offer(filename: str, supplier: str, price: str, *, qty: str = "1", body: str = "") -> dict:
    return {
        "supplier": supplier,
        "source_file": filename,
        "body": body,
        "items": [
            {
                "no": "1",
                "name": "Набор",
                "qty": qty,
                "unit": "шт",
                "extra": {"price": price, "price_kind": "price_unit", "vat": "20%"},
            }
        ],
    }
