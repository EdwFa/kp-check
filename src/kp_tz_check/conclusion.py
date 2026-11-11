"""Итог комплекта: один вердикт, связанные риски и ответственный у уточнения."""

from __future__ import annotations

from kp_tz_check.models import (
    BlockId,
    BlockResult,
    BlockStatus,
    Clarification,
    ConclusionVerdict,
    FindingSeverity,
    LinkedRisk,
    PackConclusion,
)


OWNERS = {
    BlockId.PACKAGE: "инициатор заявки",
    BlockId.BASELINE: "ответственный за ТЗ",
    BlockId.COMPETITION: "поставщик",
    BlockId.NMCK: "инициатор заявки",
    BlockId.ARITHMETIC: "инициатор заявки",
    BlockId.OKPD2: "ответственный за ТЗ",
    BlockId.NPA: "ответственный за ТЗ",
    BlockId.SECURITY: "инициатор заявки",
}


def assemble_conclusion(blocks: list[BlockResult]) -> PackConclusion:
    ordered = _ordered(blocks)
    critical = [block for block in ordered if block.status == BlockStatus.CRITICAL]
    unchecked = [block for block in ordered if block.status == BlockStatus.NOT_CHECKED]
    remarked = [block for block in ordered if block.status == BlockStatus.REMARKS]
    if critical:
        verdict = ConclusionVerdict.COMMISSION
        reason = "критичные ошибки по блокам: " + ", ".join(block.block_id.value for block in critical)
    elif unchecked:
        verdict = ConclusionVerdict.REWORK
        reason = "блоки не закрыты: " + ", ".join(block.block_id.value for block in unchecked)
    elif remarked:
        verdict = ConclusionVerdict.REWORK
        reason = "есть замечания по блокам: " + ", ".join(block.block_id.value for block in remarked)
    else:
        verdict = ConclusionVerdict.PASS
        reason = "все 8 блоков проверены, замечаний нет"

    critical_risks: list[str] = []
    clarifications: list[Clarification] = []
    for block in ordered:
        owner = OWNERS[block.block_id]
        for finding in block.findings:
            if finding.severity == FindingSeverity.CRITICAL:
                critical_risks.append(finding.text)
            elif finding.severity == FindingSeverity.REMARK:
                clarifications.append(Clarification(finding.text, owner))
        if block.status == BlockStatus.CRITICAL and not any(
            finding.severity == FindingSeverity.CRITICAL for finding in block.findings
        ):
            critical_risks.append(block.reason or block.title)
        if (
            block.status == BlockStatus.REMARKS
            and block.reason
            and not any(finding.severity == FindingSeverity.REMARK for finding in block.findings)
        ):
            clarifications.append(Clarification(block.reason, owner))

    return PackConclusion(
        blocks=ordered,
        linked_risks=_linked(ordered),
        critical_risks=critical_risks,
        clarifications=clarifications,
        verdict=verdict,
        verdict_reason=reason,
    )


def _ordered(blocks: list[BlockResult]) -> list[BlockResult]:
    by_id: dict[BlockId, BlockResult] = {}
    for block in blocks:
        if block.block_id in by_id:
            raise ValueError(f"Блок {block.block_id.value} передан дважды")
        by_id[block.block_id] = block
    ordered = []
    for block_id in BlockId:
        existing = by_id.get(block_id)
        if existing is None:
            from kp_tz_check.models import BLOCK_TITLES

            ordered.append(
                BlockResult(block_id, BLOCK_TITLES[block_id], BlockStatus.NOT_CHECKED, reason="блок не передан")
            )
        else:
            ordered.append(existing)
    return ordered


def _linked(blocks: list[BlockResult]) -> list[LinkedRisk]:
    by_id = {block.block_id: block for block in blocks}
    risks: list[LinkedRisk] = []
    nmck = by_id[BlockId.NMCK]
    arithmetic = by_id[BlockId.ARITHMETIC]
    security = by_id[BlockId.SECURITY]
    baseline = by_id[BlockId.BASELINE]
    if _critical(nmck) and _critical(arithmetic):
        risks.append(
            LinkedRisk(
                "Ошибка НМЦК и арифметическая ошибка заявки относятся к одной позиции.",
                [BlockId.NMCK, BlockId.ARITHMETIC],
            )
        )
    if any("антидемпинг" in finding.text.casefold() for finding in nmck.findings) and _security_open(security):
        risks.append(
            LinkedRisk(
                "Антидемпинг при незакрытом обеспечении.",
                [BlockId.NMCK, BlockId.SECURITY],
            )
        )
    if any("расхожд" in finding.text.casefold() and "кп" in finding.text.casefold() for finding in baseline.findings):
        risks.append(
            LinkedRisk(
                "Расхождение базовых документов и несовпадение КП.",
                [BlockId.BASELINE],
            )
        )
    return risks


def _critical(block: BlockResult) -> bool:
    return block.status == BlockStatus.CRITICAL or any(
        finding.severity == FindingSeverity.CRITICAL for finding in block.findings
    )


def _security_open(block: BlockResult) -> bool:
    blob = " ".join([block.reason or "", *(finding.text for finding in block.findings)]).casefold()
    return block.status == BlockStatus.NOT_CHECKED or "уточнен" in blob or "не загружен" in blob or "не найден" in blob
