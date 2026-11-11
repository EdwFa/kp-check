"""Сверка базовых документов и сравнение КП с каждым вариантом.

Шаг 2.1 сопоставляет ТЗ, заявку и запрос по номеру, затем по item_score.
Шаг 2.2 сравнивает каждое КП с согласованным требованием или отдельно
с каждым разошедшимся документом. Верный источник не выбирается.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from kp_tz_check.match import compare_requirement, item_score, normalize_unit, parse_qty
from kp_tz_check.models import BlockFinding, FindingSeverity, Item

# Тот же порог, что у match_items.
_MATCH_MIN = 0.52

_DOCUMENTS = ("tz", "application", "request")
_LABELS = {"tz": "ТЗ", "application": "Заявка", "request": "Запрос"}
_MISSING_NOTES = {
    "tz": "ТЗ не предоставлено",
    "application": "Заявка не предоставлена",
    "request": "Запрос не предоставлен",
}
_FIELDS = (
    ("name", "наименование"),
    ("specs", "характеристика"),
    ("unit", "единица"),
    ("qty", "количество"),
)


class BaselineStatus(str, Enum):
    AGREED = "Полностью согласовано"
    DIVERGED = "Расхождение между базовыми документами"
    ABSENT = "Отсутствует в одном из документов"


class OfferMatchStatus(str, Enum):
    MATCH = "Соответствует"
    MISMATCH = "Не соответствует"
    NO_REQUIREMENT = "Нет базового требования"


@dataclass
class BaselineSource:
    document: str
    no: str
    name: str
    specs: str
    unit: str
    qty: str

    @property
    def verbatim(self) -> str:
        return " | ".join((self.name, self.specs, self.unit, self.qty))


@dataclass
class BaselineRow:
    status: BaselineStatus
    sources: list[BaselineSource] = field(default_factory=list)
    differing_fields: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class BaselineOffer:
    supplier: str
    source_file: str
    items: list[Item]


@dataclass
class OfferComparisonRow:
    position_no: str
    position_name: str
    supplier: str
    source_file: str
    requirement_source: str
    status: OfferMatchStatus
    requirement_text: str
    offer_text: str
    differences: list[str] = field(default_factory=list)


@dataclass
class BaselineReconciliation:
    rows: list[BaselineRow]
    offer_rows: list[OfferComparisonRow] = field(default_factory=list)
    critical_findings: list[BlockFinding] = field(default_factory=list)


def reconcile_pack(
    tzs: list[Any] | None = None,
    applications: list[Any] | None = None,
    requests: list[Any] | None = None,
    kps: list[Any] | None = None,
) -> BaselineReconciliation:
    """Сверить загруженные документы. Пустой список значит, что вида документа нет."""
    return reconcile_baseline(
        _collect_items(tzs),
        _collect_items(applications),
        _collect_items(requests),
        offers=_offers(kps),
    )


def reconcile_baseline(
    tz_items: list[Item] | None = None,
    application_items: list[Item] | None = None,
    request_items: list[Item] | None = None,
    offers: list[BaselineOffer] | None = None,
) -> BaselineReconciliation:
    """Сверить три списка позиций. None — документа нет, [] — документ без позиций."""
    groups = {
        "tz": tz_items,
        "application": application_items,
        "request": request_items,
    }
    present = {name: items for name, items in groups.items() if items is not None}
    aligned = _align(present)
    rows = [_row_from_alignment(slot, present) for slot in aligned]
    for name, items in groups.items():
        if items is None:
            rows.append(BaselineRow(status=BaselineStatus.ABSENT, note=_MISSING_NOTES[name]))
    offer_rows, findings = _compare_offers(aligned, present, offers or [])
    return BaselineReconciliation(rows=rows, offer_rows=offer_rows, critical_findings=findings)


def render_baseline(result: BaselineReconciliation) -> str:
    """Текст шага 2.1: статус и дословные значения присутствующих документов."""
    lines: list[str] = []
    for row in result.rows:
        lines.append(row.status.value)
        for source in row.sources:
            lines.append(f"{source.document}: {source.verbatim}")
        if row.note:
            lines.append(row.note)
    return "\n".join(lines)


def render_offer_comparison(result: BaselineReconciliation) -> str:
    """Текст шага 2.2: позиция, поставщик и источник требования."""
    lines: list[str] = []
    for row in result.offer_rows:
        lines.append(
            " | ".join(
                (
                    row.position_no,
                    row.position_name,
                    row.supplier,
                    row.requirement_source or "—",
                    row.status.value,
                )
            )
        )
    return "\n".join(lines)


def _align(present: dict[str, list[Item]]) -> list[dict[str, Item | None]]:
    used = {name: set() for name in present}
    rows: list[dict[str, Item | None]] = []
    for number in _numbers(present):
        slot = {name: None for name in present}
        for name, items in present.items():
            for index, item in enumerate(items):
                if index in used[name] or item.no.strip() != number:
                    continue
                slot[name] = item
                used[name].add(index)
                break
        if any(item is not None for item in slot.values()):
            rows.append(slot)
    for name, items in present.items():
        for index, item in enumerate(items):
            if index in used[name]:
                continue
            target = _best_slot(rows, name, item)
            if target is None:
                slot = {doc: None for doc in present}
                slot[name] = item
                rows.append(slot)
            else:
                target[name] = item
            used[name].add(index)
    return rows


def _numbers(present: dict[str, list[Item]]) -> list[str]:
    seen: list[str] = []
    for name in _DOCUMENTS:
        for item in present.get(name) or []:
            number = item.no.strip()
            if number and number not in seen:
                seen.append(number)
    return seen


def _best_slot(
    rows: list[dict[str, Item | None]],
    document: str,
    item: Item,
) -> dict[str, Item | None] | None:
    best: dict[str, Item | None] | None = None
    best_score = 0.0
    for slot in rows:
        if slot.get(document) is not None:
            continue
        if _number_conflict(slot, item):
            continue
        score = max(
            (item_score(other, item) for other in slot.values() if other is not None),
            default=0.0,
        )
        if score > best_score:
            best_score = score
            best = slot
    if best is None or best_score < _MATCH_MIN:
        return None
    return best


def _number_conflict(slot: dict[str, Item | None], item: Item) -> bool:
    number = item.no.strip()
    if not number:
        return False
    return any(
        other is not None and other.no.strip() and other.no.strip() != number
        for other in slot.values()
    )


def _row_from_alignment(
    slot: dict[str, Item | None],
    present: dict[str, list[Item]],
) -> BaselineRow:
    filled = [(name, item) for name, item in slot.items() if item is not None]
    sources = [_source(name, item) for name, item in filled]
    differing = _differing_fields([item for _, item in filled]) if len(filled) >= 2 else []
    missing = [name for name in present if slot.get(name) is None]
    if differing:
        status = BaselineStatus.DIVERGED
    elif missing:
        status = BaselineStatus.ABSENT
    else:
        status = BaselineStatus.AGREED
    note = None
    if status == BaselineStatus.ABSENT and missing:
        note = "нет в документе: " + ", ".join(_LABELS[name] for name in _DOCUMENTS if name in missing)
    return BaselineRow(status=status, sources=sources, differing_fields=differing, note=note)


def _source(document: str, item: Item) -> BaselineSource:
    return BaselineSource(
        document=_LABELS[document],
        no=item.no,
        name=item.name,
        specs=item.specs,
        unit=item.unit,
        qty=item.qty,
    )


def _differing_fields(items: list[Item]) -> list[str]:
    found: list[str] = []
    for attr, label in _FIELDS:
        values = [getattr(item, attr) for item in items]
        if not _same_field(attr, values):
            found.append(label)
    return found


def _same_field(attr: str, values: list[str]) -> bool:
    if attr == "qty":
        parsed = [parse_qty(value) for value in values]
        if all(value is not None for value in parsed):
            return len(set(parsed)) == 1
    if attr == "unit":
        return len({normalize_unit(value) for value in values}) == 1
    return len({_plain(value) for value in values}) == 1


def _plain(value: str) -> str:
    text = (value or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


_CRITICAL_KINDS = {"name", "specs", "unit", "qty"}
_AGREED_REQUIREMENT = "Согласованное требование"


def _compare_offers(
    slots: list[dict[str, Item | None]],
    present: dict[str, list[Item]],
    offers: list[BaselineOffer],
) -> tuple[list[OfferComparisonRow], list[BlockFinding]]:
    rows: list[OfferComparisonRow] = []
    findings: list[BlockFinding] = []
    for offer in offers:
        assignment, extras = _match_offer_items(slots, offer.items)
        for slot_index, item_index in assignment.items():
            slot = slots[slot_index]
            offer_item = offer.items[item_index]
            for label, requirement in _requirement_variants(slot, present):
                rows.append(_offer_row(offer, offer_item, requirement, label, findings))
        for item_index in extras:
            rows.append(_offer_without_requirement(offer, offer.items[item_index], findings))
    return rows, findings


def _requirement_variants(
    slot: dict[str, Item | None],
    present: dict[str, list[Item]],
) -> list[tuple[str, Item]]:
    filled = [(name, item) for name, item in slot.items() if item is not None]
    if not filled:
        return []
    status = _row_from_alignment(slot, present).status
    if status == BaselineStatus.AGREED:
        return [(_AGREED_REQUIREMENT, filled[0][1])]
    return [(_LABELS[name], item) for name, item in filled]


def _match_offer_items(
    slots: list[dict[str, Item | None]],
    items: list[Item],
) -> tuple[dict[int, int], list[int]]:
    used: set[int] = set()
    assignment: dict[int, int] = {}
    for slot_index, slot in enumerate(slots):
        numbers = {item.no.strip() for item in slot.values() if item is not None and item.no.strip()}
        if len(numbers) != 1:
            continue
        number = next(iter(numbers))
        for item_index, item in enumerate(items):
            if item_index in used or item.no.strip() != number:
                continue
            assignment[slot_index] = item_index
            used.add(item_index)
            break
    for slot_index, slot in enumerate(slots):
        if slot_index in assignment:
            continue
        best_index: int | None = None
        best_score = 0.0
        for item_index, item in enumerate(items):
            if item_index in used:
                continue
            score = max(
                (item_score(requirement, item) for requirement in slot.values() if requirement is not None),
                default=0.0,
            )
            if score > best_score:
                best_score = score
                best_index = item_index
        if best_index is not None and best_score >= _MATCH_MIN:
            assignment[slot_index] = best_index
            used.add(best_index)
    extras = [index for index in range(len(items)) if index not in used]
    return assignment, extras


def _offer_row(
    offer: BaselineOffer,
    offer_item: Item,
    requirement: Item,
    label: str,
    findings: list[BlockFinding],
) -> OfferComparisonRow:
    mismatches = [
        item
        for item in compare_requirement(requirement, offer_item, label)
        if item.kind in _CRITICAL_KINDS
    ]
    differences = [item.detail for item in mismatches]
    status = OfferMatchStatus.MISMATCH if differences else OfferMatchStatus.MATCH
    for detail in differences:
        findings.append(
            BlockFinding(
                code="2",
                text=f"{offer.supplier}: {detail}",
                source=offer.source_file,
                severity=FindingSeverity.CRITICAL,
            )
        )
    return OfferComparisonRow(
        position_no=offer_item.no or requirement.no,
        position_name=offer_item.name or requirement.name,
        supplier=offer.supplier,
        source_file=offer.source_file,
        requirement_source=label,
        status=status,
        requirement_text=_verbatim(requirement),
        offer_text=_verbatim(offer_item),
        differences=differences,
    )


def _offer_without_requirement(
    offer: BaselineOffer,
    item: Item,
    findings: list[BlockFinding],
) -> OfferComparisonRow:
    text = f"{offer.supplier}: в КП позиция без базового требования: {item.name or item.specs}"
    findings.append(
        BlockFinding(
            code="2",
            text=text,
            source=offer.source_file,
            severity=FindingSeverity.CRITICAL,
        )
    )
    return OfferComparisonRow(
        position_no=item.no,
        position_name=item.name,
        supplier=offer.supplier,
        source_file=offer.source_file,
        requirement_source="",
        status=OfferMatchStatus.NO_REQUIREMENT,
        requirement_text="",
        offer_text=_verbatim(item),
        differences=[text],
    )


def _verbatim(item: Item) -> str:
    return " | ".join((item.name, item.specs, item.unit, item.qty))


def _collect_items(records: list[Any] | None) -> list[Item] | None:
    if not records:
        return None
    seen: set[tuple[str, str, str, str, str, str]] = set()
    items: list[Item] = []
    for record in records:
        data = _as_dict(record)
        for raw in data.get("items") or []:
            item = _as_item(raw)
            key = (item.no, item.name, item.specs, item.unit, item.qty, item.extra.get("article", ""))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def _offers(records: list[Any] | None) -> list[BaselineOffer]:
    offers: list[BaselineOffer] = []
    for record in records or []:
        data = _as_dict(record)
        source = str(data.get("source_file") or "")
        supplier = str(data.get("supplier") or "").strip() or Path(source).name or "КП"
        offers.append(
            BaselineOffer(
                supplier=supplier,
                source_file=source or supplier,
                items=[_as_item(item) for item in data.get("items") or []],
            )
        )
    return offers


def _as_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    from kp_tz_check.serde import to_jsonable

    return to_jsonable(record)


def _as_item(raw: Any) -> Item:
    data = raw if isinstance(raw, dict) else _as_dict(raw)
    extra = data.get("extra") or {}
    if not isinstance(extra, dict):
        extra = {}
    return Item(
        no=str(data.get("no") or ""),
        name=str(data.get("name") or ""),
        specs=str(data.get("specs") or ""),
        unit=str(data.get("unit") or ""),
        qty=str(data.get("qty") or ""),
        extra={str(key): str(value) for key, value in extra.items()},
    )
