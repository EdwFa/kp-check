from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from kp_tz_check.instruction import missing_concrete_specs, vague_wording_issue
from kp_tz_check.models import Item, ItemMismatch, KpRecord, RequestRecord, TzRecord

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None


def _org_core(name: str) -> str:
    text = _norm(name)
    return re.sub(r"^(ооо|зао|оао|ао|пао|ип)\s+", "", text).strip(" «»\"'")


def suppliers_conflict(request_name: str | None, kp_name: str | None) -> bool:
    if not request_name or not kp_name:
        return False
    return _ratio(_org_core(request_name), _org_core(kp_name)) < 0.55


def _ratio(a: str, b: str) -> float:
    left, right = _norm(a), _norm(b)
    if not left or not right:
        return 0.0
    if fuzz is not None:
        return fuzz.token_set_ratio(left, right) / 100.0
    return SequenceMatcher(None, left, right).ratio()


def _norm(value: str) -> str:
    text = (value or "").lower().replace("ё", "е")
    text = re.sub(r"код окпд2[:\s]*[\d.]+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def normalize_unit(unit: str) -> str:
    text = _norm(unit).replace(".", "")
    aliases = {
        "шт": "шт",
        "штука": "шт",
        "штук": "шт",
        "штуки": "шт",
        "набор": "набор",
        "наб": "набор",
        "упак": "упак",
        "упаковка": "упак",
        "флакон": "фл",
        "фл": "фл",
        "комплект": "комплект",
        "компл": "комплект",
    }
    return aliases.get(text, text)


def parse_qty(value: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", value or "")
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


SPEC_KEYS = (
    ("cycles", re.compile(r"(?:циклов[^\d]{0,24}(\d+)|(\d+)\s*циклов)", re.I)),
    ("cycles_model", re.compile(r"3700/(\d{2,4})", re.I)),
    ("gb", re.compile(r"(\d+)\s*гб", re.I)),
    ("hours", re.compile(r"(\d+)\s*час", re.I)),
    ("bp", re.compile(r"(\d+)\s*п\.?\s*н", re.I)),
    ("mln", re.compile(r"(\d+)\s*млн", re.I)),
)


def spec_fingerprint(item: Item) -> dict[str, str]:
    blob = f"{item.name} {item.specs} {item.extra.get('article', '')}"
    found: dict[str, str] = {}
    for key, pattern in SPEC_KEYS:
        match = pattern.search(blob)
        if match:
            value = next((group for group in match.groups() if group), None)
            if not value:
                continue
            store = "cycles" if key.startswith("cycles") else key
            found.setdefault(store, value)
    return found


def fingerprints_conflict(tz_item: Item, kp_item: Item) -> bool:
    tz_fp, kp_fp = spec_fingerprint(tz_item), spec_fingerprint(kp_item)
    return any(key in kp_fp and kp_fp[key] != value for key, value in tz_fp.items())


def item_score(tz_item: Item, kp_item: Item) -> float:
    if fingerprints_conflict(tz_item, kp_item):
        return 0.0
    name_score = max(
        _ratio(tz_item.name, kp_item.name),
        _ratio(tz_item.fingerprint_text, kp_item.fingerprint_text),
    )
    score = name_score * 0.45
    tz_qty, kp_qty = parse_qty(tz_item.qty), parse_qty(kp_item.qty)
    if tz_qty is not None and kp_qty is not None:
        score += 0.2 if tz_qty == kp_qty else 0.0
    tz_fp, kp_fp = spec_fingerprint(tz_item), spec_fingerprint(kp_item)
    if tz_fp and kp_fp:
        keys = set(tz_fp) | set(kp_fp)
        overlap = sum(1 for key in keys if tz_fp.get(key) == kp_fp.get(key))
        score += 0.35 * (overlap / max(len(keys), 1))
    elif _ratio(tz_item.specs, kp_item.specs) >= 0.72:
        score += 0.25
    cycles_match = tz_fp.get("cycles") and tz_fp.get("cycles") == kp_fp.get("cycles")
    if tz_qty is not None and kp_qty is not None and tz_qty == kp_qty and cycles_match:
        score = max(score, 0.85)
    return score


@dataclass
class PairLink:
    request: RequestRecord
    kp: KpRecord
    reason: str
    score: float


def pair_requests_and_kps(
    requests: list[RequestRecord],
    kps: list[KpRecord],
) -> tuple[list[tuple[RequestRecord, KpRecord]], list[RequestRecord], list[KpRecord]]:
    links, unmatched_requests, unmatched_kps = pair_requests_and_kps_detailed(requests, kps)
    return [(item.request, item.kp) for item in links], unmatched_requests, unmatched_kps


def pair_requests_and_kps_detailed(
    requests: list[RequestRecord],
    kps: list[KpRecord],
) -> tuple[list[PairLink], list[RequestRecord], list[KpRecord]]:
    unused_kps = list(kps)
    links: list[PairLink] = []

    remaining_requests: list[RequestRecord] = []
    for request in requests:
        if not request.outgoing_no:
            remaining_requests.append(request)
            continue
        hit = next((i for i, kp in enumerate(unused_kps) if kp.outgoing_no == request.outgoing_no), None)
        if hit is None:
            remaining_requests.append(request)
        else:
            kp = unused_kps.pop(hit)
            links.append(PairLink(request=request, kp=kp, reason="outgoing_no", score=1.0))

    still_unmatched: list[RequestRecord] = []
    for request in remaining_requests:
        best_i = None
        best_score = 0.0
        best_reason = "none"
        for i, kp in enumerate(unused_kps):
            score, reason = _pair_score_detailed(request, kp)
            if score > best_score:
                best_score = score
                best_reason = reason
                best_i = i
        if best_i is not None and best_score >= 0.45:
            kp = unused_kps.pop(best_i)
            links.append(PairLink(request=request, kp=kp, reason=best_reason, score=best_score))
        else:
            still_unmatched.append(request)
    return links, still_unmatched, unused_kps


def _pair_score(request: RequestRecord, kp: KpRecord) -> float:
    score, _reason = _pair_score_detailed(request, kp)
    return score


def _pair_score_detailed(request: RequestRecord, kp: KpRecord) -> tuple[float, str]:
    if request.outgoing_no and kp.outgoing_no and request.outgoing_no == kp.outgoing_no:
        return 1.0, "outgoing_no"
    best_score = 0.0
    best_reason = "none"
    if request.supplier and kp.supplier:
        score = _ratio(request.supplier, kp.supplier)
        if score > best_score:
            best_score, best_reason = score, "supplier"
    if request.email and request.email.lower() in (kp.body or "").lower() and 0.95 > best_score:
        best_score, best_reason = 0.95, "email"
    if request.outgoing_no and request.outgoing_no in (kp.body or "") and 0.9 > best_score:
        best_score, best_reason = 0.9, "outgoing_in_body"
    filename = kp.source_file.stem
    if request.supplier:
        score = _ratio(request.supplier, filename)
        if score > best_score:
            best_score, best_reason = score, "filename"
    return best_score, best_reason


def match_items(tz_items: list[Item], kp_items: list[Item]) -> list[ItemMismatch]:
    unused = list(enumerate(kp_items))
    mismatches: list[ItemMismatch] = []
    used_kp: set[int] = set()

    for tz_item in tz_items:
        best: tuple[float, int, Item] | None = None
        for idx, kp_item in unused:
            if idx in used_kp:
                continue
            score = item_score(tz_item, kp_item)
            if best is None or score > best[0]:
                best = (score, idx, kp_item)
        if best is None or best[0] < 0.52:
            mismatches.append(
                ItemMismatch(
                    kind="missing",
                    tz_item=tz_item,
                    kp_item=None,
                    detail=f"Позиция ТЗ не найдена в КП: {tz_item.name or tz_item.specs[:80]}",
                )
            )
            continue
        _, idx, kp_item = best
        used_kp.add(idx)
        mismatches.extend(compare_requirement(tz_item, kp_item))

    for idx, kp_item in unused:
        if idx not in used_kp:
            mismatches.append(
                ItemMismatch(
                    kind="extra",
                    tz_item=None,
                    kp_item=kp_item,
                    detail=f"В КП лишняя позиция, которой нет в ТЗ: {kp_item.name or kp_item.specs[:80]}",
                )
            )
    return mismatches


# с чем сравниваем, в чём, родительный падеж. «ТЗ» сохраняет прежние формулировки блока 1.
_REQUIREMENT_FORMS = {
    "ТЗ": ("ТЗ", "ТЗ", "ТЗ"),
    "Заявка": ("заявкой", "заявке", "заявки"),
    "Запрос": ("запросом", "запросе", "запроса"),
    "Согласованное требование": (
        "согласованным требованием",
        "согласованном требовании",
        "согласованного требования",
    ),
}


def compare_requirement(
    requirement: Item,
    offer: Item,
    requirement_label: str = "ТЗ",
) -> list[ItemMismatch]:
    """Сравнить строку КП с одним базовым требованием. Блок 1 по-прежнему зовёт это с подписью «ТЗ»."""
    with_label, in_label, genitive = _REQUIREMENT_FORMS.get(
        requirement_label, (requirement_label, requirement_label, requirement_label)
    )
    details: list[ItemMismatch] = []
    name_ok = (
        _ratio(requirement.name, offer.name) >= 0.55
        or spec_fingerprint(requirement).get("cycles") == spec_fingerprint(offer).get("cycles")
    )
    if not name_ok:
        details.append(
            ItemMismatch("name", requirement, offer, f"Наименование в КП не совпадает с {with_label}")
        )

    requirement_fp, offer_fp = spec_fingerprint(requirement), spec_fingerprint(offer)
    if requirement_fp and offer_fp:
        for key, requirement_value in requirement_fp.items():
            if key in offer_fp and offer_fp[key] != requirement_value:
                details.append(
                    ItemMismatch(
                        "specs",
                        requirement,
                        offer,
                        f"Характеристика {key}: в {in_label} {requirement_value}, в КП {offer_fp[key]}",
                    )
                )
    elif requirement.specs and offer.specs and _ratio(requirement.specs, offer.specs) < 0.55:
        details.append(
            ItemMismatch("specs", requirement, offer, f"Характеристики {genitive} и КП расходятся")
        )

    requirement_unit, offer_unit = normalize_unit(requirement.unit), normalize_unit(offer.unit)
    offer_unit_looks_price = bool(re.search(r"\d[\s\d]*[.,]\d{2}", offer.unit or ""))
    if requirement_unit and offer_unit and requirement_unit != offer_unit and not offer_unit_looks_price:
        details.append(
            ItemMismatch(
                "unit",
                requirement,
                offer,
                f"Единица измерения: в {in_label} «{requirement.unit}», в КП «{offer.unit}»",
            )
        )

    requirement_qty, offer_qty = parse_qty(requirement.qty), parse_qty(offer.qty)
    if requirement_qty is not None and offer_qty is not None and requirement_qty != offer_qty:
        details.append(
            ItemMismatch(
                "qty",
                requirement,
                offer,
                f"Количество: в {in_label} {requirement.qty}, в КП {offer.qty}",
            )
        )
    vague = vague_wording_issue(requirement, offer)
    if vague:
        details.append(vague)
    details.extend(missing_concrete_specs(requirement, offer, requirement_fp, offer_fp))
    return details


def _compare_matched(tz_item: Item, kp_item: Item) -> list[ItemMismatch]:
    return compare_requirement(tz_item, kp_item)


def choose_tz(tzs: list[TzRecord], request: RequestRecord | None) -> TzRecord | None:
    if not tzs:
        return None
    if request is None or len(tzs) == 1:
        return tzs[0]
    best = tzs[0]
    best_score = -1.0
    for tz in tzs:
        score = _ratio(tz.source_file.stem, request.source_file.stem)
        if request.items and tz.items:
            score = max(score, item_score(tz.items[0], request.items[0]) if request.items else 0)
        if score > best_score:
            best, best_score = tz, score
    return best
