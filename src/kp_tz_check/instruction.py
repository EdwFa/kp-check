from __future__ import annotations

import re

from kp_tz_check.models import Item, ItemMismatch

VAGUE = re.compile(r"\b(не\s+менее|не\s+более|должен(?:\s+быть)?|\bили\b|\bлибо\b)\b", re.I)

SPEC_LABELS = {
    "cycles": "число циклов",
    "gb": "объём данных, Гб",
    "hours": "время секвенирования, ч",
    "bp": "длина прочтения, п.н.",
    "mln": "производительность, млн прочтений",
}


def vague_wording_issue(tz_item: Item, kp_item: Item) -> ItemMismatch | None:
    blob = f"{kp_item.name} {kp_item.specs}"
    if VAGUE.search(blob):
        return ItemMismatch(
            "instruction",
            tz_item,
            kp_item,
            "В КП использована неопределённая формулировка («не менее»/«не более»/«или») — "
            "по инструкции нужны конкретные показатели",
        )
    return None


def missing_concrete_specs(tz_item: Item, kp_item: Item, tz_fp: dict[str, str], kp_fp: dict[str, str]) -> list[ItemMismatch]:
    issues: list[ItemMismatch] = []
    for key, tz_val in tz_fp.items():
        if key in kp_fp:
            continue
        label = SPEC_LABELS.get(key, key)
        issues.append(
            ItemMismatch(
                "instruction",
                tz_item,
                kp_item,
                f"В КП нет конкретного показателя «{label}» (в ТЗ: {tz_val}). "
                "По инструкции единица и значение из ТЗ должны быть указаны явно.",
            )
        )
    return issues
