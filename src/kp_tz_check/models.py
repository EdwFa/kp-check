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
