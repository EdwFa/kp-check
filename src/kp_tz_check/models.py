from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path


class FinalStatus(str, Enum):
    MATCH = "Соответствует"
    NEEDS_REVIEW = "Требует уточнения"
    MISMATCH = "Не соответствует"


class DateCheckMark(str, Enum):
    OK = "✅"
    FAIL = "❌"
    UNKNOWN = "требует ручной проверки"


class ProductCheckMark(str, Enum):
    OK = "✅"
    FAIL = "❌"
    PARTIAL = "частично"
    UNKNOWN = "требует ручной проверки"


class BlockId(str, Enum):
    PACKAGE = "1"
    BASELINE = "2"
    COMPETITION = "3"
    NMCK = "4"
    ARITHMETIC = "5"
    OKPD2 = "6"
    NPA = "7"
    SECURITY = "8"


class BlockStatus(str, Enum):
    CLEAN = "Проверен, замечаний нет"
    REMARKS = "Проверен, есть замечания"
    CRITICAL = "Проверен, критичные ошибки"
    NOT_CHECKED = "Не проверен — документы не предоставлены"


class FindingSeverity(str, Enum):
    NOTE = "справка"
    REMARK = "замечание"
    CRITICAL = "критичная"


class ConclusionVerdict(str, Enum):
    PASS = "Можно передавать далее без изменений"
    REWORK = "Требуется доработка"
    COMMISSION = "Требуется решение закупочной комиссии"


BLOCK_TITLES: dict[BlockId, str] = {
    BlockId.PACKAGE: "Комплектность пакета и хронология",
    BlockId.BASELINE: "Сверка позиций закупки",
    BlockId.COMPETITION: "Национальный режим и конкуренция",
    BlockId.NMCK: "Расчёт НМЦК",
    BlockId.ARITHMETIC: "Арифметическая проверка заявки",
    BlockId.OKPD2: "Коды ОКПД2 и статус СМП",
    BlockId.NPA: "Актуальность НПА и стандартов",
    BlockId.SECURITY: "Обеспечение заявки и исполнения контракта",
}


@dataclass
class Item:
    no: str
    name: str
    specs: str
    unit: str
    qty: str
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def fingerprint_text(self) -> str:
        return " ".join(part for part in (self.name, self.specs, self.unit, self.qty) if part)


@dataclass
class RequestRecord:
    source_file: Path
    outgoing_no: str | None
    sent_on: date | None
    sent_on_raw: str | None
    supplier: str | None
    email: str | None
    body: str = ""
    items: list[Item] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class KpRecord:
    source_file: Path
    prepared_on: date | None
    prepared_on_raw: str | None
    registered_on: date | None
    registered_on_raw: str | None
    supplier: str | None
    outgoing_no: str | None = None
    body: str = ""
    items: list[Item] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class TzRecord:
    source_file: Path
    title: str | None
    items: list[Item] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


ROW_INSUFFICIENT = "недостаточно данных"


@dataclass
class ApplicationRecord:
    """Заявка. Цена, скидка, НДС, сумма строки и ОКПД2 лежат в Item.extra."""

    source_file: Path
    body: str = ""
    items: list[Item] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class NmckRecord:
    """Обоснование НМЦК. Цена источника лежит в Item.extra, сверка идёт по поставщику и позиции."""

    source_file: Path
    body: str = ""
    items: list[Item] = field(default_factory=list)
    declared_total: str | None = None
    formula: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class SecurityDocument:
    source_file: Path
    body: str = ""


@dataclass
class ItemMismatch:
    kind: str
    tz_item: Item | None
    kp_item: Item | None
    detail: str


@dataclass
class PairResult:
    request: RequestRecord | None
    kp: KpRecord | None
    tz: TzRecord | None
    date_mark: DateCheckMark
    product_mark: ProductCheckMark
    status: FinalStatus
    comments: list[str]
    item_mismatches: list[ItemMismatch] = field(default_factory=list)

    @property
    def request_label(self) -> str:
        if self.request is None:
            return "—"
        bits = []
        if self.request.outgoing_no:
            bits.append(f"Исх. №{self.request.outgoing_no}")
        if self.request.supplier:
            bits.append(self.request.supplier)
        if self.request.sent_on:
            bits.append(self.request.sent_on.strftime("%d.%m.%Y"))
        elif self.request.sent_on_raw:
            bits.append(self.request.sent_on_raw)
        else:
            bits.append("дата отправки не прочитана")
        return " · ".join(bits) if bits else self.request.source_file.name


@dataclass
class BlockFinding:
    code: str
    text: str
    source: str | None
    severity: FindingSeverity


@dataclass
class BlockResult:
    block_id: BlockId
    title: str
    status: BlockStatus
    findings: list[BlockFinding] = field(default_factory=list)
    reason: str | None = None


@dataclass
class Clarification:
    text: str
    owner: str | None = None


@dataclass
class LinkedRisk:
    text: str
    block_ids: list[BlockId] = field(default_factory=list)


@dataclass
class PackConclusion:
    blocks: list[BlockResult]
    linked_risks: list[LinkedRisk] = field(default_factory=list)
    critical_risks: list[str] = field(default_factory=list)
    clarifications: list[Clarification] = field(default_factory=list)
    verdict: ConclusionVerdict = ConclusionVerdict.REWORK
    verdict_reason: str = ""


def parse_block_status(value: str) -> BlockStatus:
    """Принять только точную формулировку статуса блока."""
    try:
        return BlockStatus(value)
    except ValueError as exc:
        raise ValueError(f"Неизвестный статус блока: {value!r}") from exc


def build_conclusion(blocks: list[BlockResult]) -> PackConclusion:
    """Собрать итог комплекта. Критическая ошибка ведёт к комиссии, непроверенный блок не даёт «можно передавать»."""
    from kp_tz_check.conclusion import assemble_conclusion

    return assemble_conclusion(blocks)
