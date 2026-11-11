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
    if not VAGUE.search(blob):
        return None
    if re.search(r"документац\w*.{0,40}производител|производител\w*.{0,40}документац", blob, re.I):
        return ItemMismatch(
            "instruction",
            tz_item,
            kp_item,
            "требует ручной проверки: формулировка отсылает к документации производителя",
        )
    return ItemMismatch(
        "instruction",
        tz_item,
        kp_item,
        "В КП использована неопределённая формулировка («не менее»/«не более»/«или») — "
        "по инструкции нужны конкретные показатели",
    )


_ABBREVIATION = re.compile(r"\b([A-ZА-ЯЁ]{3,6})\b")
_ABBREVIATION_SKIP = {"ООО", "ПАО", "ЗАО", "НДС", "ОКПД", "ГОСТ", "ЕАЭС"}
_ENUMERATION = re.compile(r"\d+(?:[.,]\d+)?\s*(?:и|,)\s*\d+(?:[.,]\d+)?", re.I)


def abbreviation_issues(text: str, document_text: str) -> list[str]:
    """Сокращение без расшифровки в скобках или отдельной строке того же КП."""
    issues: list[str] = []
    for match in _ABBREVIATION.finditer(text or ""):
        token = match.group(1)
        if token in _ABBREVIATION_SKIP or _abbreviation_explained(token, document_text or ""):
            continue
        if token not in issues:
            issues.append(token)
    return issues


def _abbreviation_explained(token: str, document_text: str) -> bool:
    if re.search(rf"{re.escape(token)}\s*\([^)]+\)", document_text):
        return True
    return bool(re.search(rf"(?m)^\s*{re.escape(token)}\s*[-–:]\s*\S+", document_text))


def enumeration_issue(tz_specs: str, kp_specs: str) -> str | None:
    """Два числа через «и» или запятую, когда в ТЗ названы оба показателя."""
    named = [
        part.strip()
        for part in re.split(r"[;\n]", tz_specs or "")
        if re.search(r"[A-Za-zА-Яа-яЁё]{3,}", part) and re.search(r"\d", part)
    ]
    if len(named) < 2 or not _ENUMERATION.search(kp_specs or ""):
        return None
    return "В КП числа соединены «и» или запятой, а в ТЗ требуются оба именованных показателя."


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
