from kp_tz_check.blocks import build_blocks
from kp_tz_check.models import (
    BLOCK_TITLES,
    BlockFinding,
    BlockId,
    BlockResult,
    BlockStatus,
    ConclusionVerdict,
    FindingSeverity,
    build_conclusion,
)
from kp_tz_check.npa import UNCHECKED, extract_npa


def _all(status: BlockStatus) -> list[BlockResult]:
    return [BlockResult(block_id, BLOCK_TITLES[block_id], status) for block_id in BlockId]


def test_unknown_citation_is_not_marked_active(monkeypatch):
    monkeypatch.delenv("KP_NPA_CATALOG", raising=False)
    text = "Применить ГОСТ 99999-2099 и 223-ФЗ."
    assert "ГОСТ 99999-2099" in extract_npa(text)
    assert "223-ФЗ" in extract_npa(text)
    block = build_blocks({"tzs": [{"source_file": "ТЗ.doc", "body": text}]})[6]
    assert block.status == BlockStatus.REMARKS
    assert all("действует" not in finding.text.casefold() for finding in block.findings)
    assert any(UNCHECKED in finding.text for finding in block.findings)


def test_catalog_status_is_labeled_as_local_list(tmp_path, monkeypatch):
    catalog = tmp_path / "npa.csv"
    catalog.write_text("citation,status,replaced_by\nГОСТ 12345-2020,действует,\n", encoding="utf-8")
    monkeypatch.setenv("KP_NPA_CATALOG", str(catalog))
    block = build_blocks({"tzs": [{"source_file": "ТЗ.doc", "body": "ГОСТ 12345-2020 и ГОСТ 1-2"}]})[6]
    known = next(item.text for item in block.findings if "12345" in item.text)
    unknown = next(item.text for item in block.findings if "ГОСТ 1-2" in item.text)
    assert "действует" in known
    assert "локальный перечень, не правовая база" in known
    assert "действует" not in unknown.casefold()


def test_three_verdicts_and_one_owner_per_clarification():
    clean = build_conclusion(_all(BlockStatus.CLEAN))
    assert clean.verdict == ConclusionVerdict.PASS
    assert len({clean.verdict}) == 1

    open_blocks = _all(BlockStatus.CLEAN)
    open_blocks[6] = BlockResult(BlockId.NPA, BLOCK_TITLES[BlockId.NPA], BlockStatus.NOT_CHECKED)
    assert build_conclusion(open_blocks).verdict == ConclusionVerdict.REWORK

    remarks = _all(BlockStatus.CLEAN)
    remarks[3] = BlockResult(
        BlockId.NMCK,
        BLOCK_TITLES[BlockId.NMCK],
        BlockStatus.REMARKS,
        findings=[BlockFinding("cv", "коэффициент вариации", None, FindingSeverity.REMARK)],
    )
    rework = build_conclusion(remarks)
    assert rework.verdict == ConclusionVerdict.REWORK
    assert rework.clarifications[0].owner == "инициатор заявки"

    critical = _all(BlockStatus.CLEAN)
    critical[0] = BlockResult(BlockId.PACKAGE, BLOCK_TITLES[BlockId.PACKAGE], BlockStatus.CRITICAL, reason="нет КП на запрос")
    assert build_conclusion(critical).verdict == ConclusionVerdict.COMMISSION


def test_linked_antidumping_and_confirmation_does_not_clear_findings():
    blocks = _all(BlockStatus.CLEAN)
    blocks[3] = BlockResult(
        BlockId.NMCK,
        BLOCK_TITLES[BlockId.NMCK],
        BlockStatus.REMARKS,
        findings=[BlockFinding("dump", "Антидемпинг, п. 1.9.23", None, FindingSeverity.REMARK)],
    )
    blocks[4] = BlockResult(
        BlockId.ARITHMETIC,
        BLOCK_TITLES[BlockId.ARITHMETIC],
        BlockStatus.CRITICAL,
        findings=[BlockFinding("sum", "содержательная ошибка", None, FindingSeverity.CRITICAL)],
    )
    blocks[7] = BlockResult(BlockId.SECURITY, BLOCK_TITLES[BlockId.SECURITY], BlockStatus.NOT_CHECKED, reason="не найден")
    conclusion = build_conclusion(blocks)
    texts = [item.text for item in conclusion.linked_risks]
    assert any("Антидемпинг" in text for text in texts)
    assert conclusion.verdict == ConclusionVerdict.COMMISSION
    assert blocks[3].findings[0].text.startswith("Антидемпинг")
