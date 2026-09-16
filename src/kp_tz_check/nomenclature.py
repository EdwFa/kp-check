"""Nomenclature-агент: fingerprints + rapidfuzz, LLM только с якорем в тексте.

Конфликт циклов/Гб запрещает пару позиций. missing/extra ставит rule-engine.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Protocol

from kp_tz_check.match import (
    PairLink,
    _compare_matched,
    _ratio,
    choose_tz,
    fingerprints_conflict,
    item_score,
    match_items,
    parse_qty,
    spec_fingerprint,
)
from kp_tz_check.models import Item, ItemMismatch, TzRecord

ACCEPT = 0.52

_proposer: ContextVar["NomenclatureProposer | None"] = ContextVar(
    "nomenclature_proposer", default=None
)
_encoder: ContextVar[Any] = ContextVar("nomenclature_encoder", default=None)


class NomenclatureProposer(Protocol):
    def propose_item_links(
        self,
        *,
        tz_items: list[dict[str, Any]],
        kp_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """[{tz_index, kp_index, article?, reason?}]"""
        ...


def get_nomenclature_proposer() -> NomenclatureProposer | None:
    return _proposer.get()


def set_nomenclature_proposer(proposer: NomenclatureProposer | None):
    return _proposer.set(proposer)


def reset_nomenclature_proposer(token) -> None:
    _proposer.reset(token)


def set_encoder(encoder) -> Any:
    return _encoder.set(encoder)


def reset_encoder(token) -> None:
    _encoder.reset(token)


def nomenclature_score(tz_item: Item, kp_item: Item) -> float:
    if fingerprints_conflict(tz_item, kp_item):
        return 0.0
    name = max(
        _ratio(tz_item.name, kp_item.name),
        _ratio(tz_item.fingerprint_text, kp_item.fingerprint_text),
    )
    fp = _fingerprint_part(tz_item, kp_item)
    embed = _embedding_ratio(tz_item, kp_item)
    if embed is None:
        return (0.50 * fp + 0.30 * name) / 0.80
    return 0.50 * fp + 0.30 * name + 0.20 * embed


def match_nomenclature(
    tz_items: list[Item],
    kp_items: list[Item],
    proposer: NomenclatureProposer | None = None,
) -> tuple[list[ItemMismatch], list[dict[str, Any]]]:
    proposer = proposer if proposer is not None else get_nomenclature_proposer()
    if proposer is None and _encoder.get() is None:
        mismatches = match_items(tz_items, kp_items)
        return mismatches, _links_from_greedy(tz_items, kp_items, item_score)

    used_kp: set[int] = set()
    used_tz: set[int] = set()
    links: list[dict[str, Any]] = []
    mismatches: list[ItemMismatch] = []

    for tz_index, tz_item in enumerate(tz_items):
        best: tuple[float, int] | None = None
        for kp_index, kp_item in enumerate(kp_items):
            if kp_index in used_kp:
                continue
            score = nomenclature_score(tz_item, kp_item)
            if best is None or score > best[0]:
                best = (score, kp_index)
        if best is None or best[0] < ACCEPT:
            continue
        kp_index = best[1]
        used_tz.add(tz_index)
        used_kp.add(kp_index)
        links.append(
            {
                "tz_index": tz_index,
                "kp_index": kp_index,
                "score": best[0],
                "reason": "hybrid",
            }
        )
        mismatches.extend(_compare_matched(tz_item, kp_items[kp_index]))

    if proposer is not None:
        try:
            proposals = proposer.propose_item_links(
                tz_items=_brief_items(tz_items),
                kp_items=_brief_items(kp_items),
            )
        except Exception:  # noqa: BLE001
            proposals = []
        for raw in proposals or []:
            try:
                tz_index = int(raw["tz_index"])
                kp_index = int(raw["kp_index"])
            except (KeyError, TypeError, ValueError):
                continue
            if tz_index in used_tz or kp_index in used_kp:
                continue
            if not (0 <= tz_index < len(tz_items) and 0 <= kp_index < len(kp_items)):
                continue
            tz_item, kp_item = tz_items[tz_index], kp_items[kp_index]
            if fingerprints_conflict(tz_item, kp_item):
                continue
            evidence = link_evidence(tz_item, kp_item, raw)
            if not evidence:
                continue
            score = nomenclature_score(tz_item, kp_item)
            used_tz.add(tz_index)
            used_kp.add(kp_index)
            links.append(
                {
                    "tz_index": tz_index,
                    "kp_index": kp_index,
                    "score": score,
                    "reason": evidence,
                }
            )
            mismatches.extend(_compare_matched(tz_item, kp_item))

    for tz_index, tz_item in enumerate(tz_items):
        if tz_index in used_tz:
            continue
        mismatches.append(
            ItemMismatch(
                kind="missing",
                tz_item=tz_item,
                kp_item=None,
                detail=f"Позиция ТЗ не найдена в КП: {tz_item.name or tz_item.specs[:80]}",
            )
        )
    for kp_index, kp_item in enumerate(kp_items):
        if kp_index in used_kp:
            continue
        mismatches.append(
            ItemMismatch(
                kind="extra",
                tz_item=None,
                kp_item=kp_item,
                detail=f"В КП лишняя позиция, которой нет в ТЗ: {kp_item.name or kp_item.specs[:80]}",
            )
        )
    return mismatches, links


def match_pack_nomenclature(
    links: list[PairLink],
    tzs: list[TzRecord],
    proposer: NomenclatureProposer | None = None,
) -> list[dict[str, Any]]:
    from kp_tz_check.serde import to_jsonable

    rows = []
    for link in links:
        tz = choose_tz(tzs, link.request)
        tz_items = tz.items if tz else []
        mismatches, item_links = match_nomenclature(tz_items, link.kp.items, proposer=proposer)
        rows.append(
            {
                "request_outgoing_no": link.request.outgoing_no if link.request else None,
                "request_file": str(link.request.source_file) if link.request else None,
                "kp_file": str(link.kp.source_file),
                "kp_file_name": link.kp.source_file.name,
                "pair_reason": link.reason,
                "pair_score": link.score,
                "links": item_links,
                "mismatches": to_jsonable(mismatches),
            }
        )
    return rows


def link_evidence(tz_item: Item, kp_item: Item, proposal: dict[str, Any] | None = None) -> str | None:
    if fingerprints_conflict(tz_item, kp_item):
        return None
    tz_blob = _item_blob(tz_item)
    kp_blob = _item_blob(kp_item)
    article = ""
    if proposal:
        article = str(proposal.get("article") or "").strip()
    if not article:
        article = (tz_item.extra.get("article") or kp_item.extra.get("article") or "").strip()
    if article and article.lower() in tz_blob and article.lower() in kp_blob:
        return "article"
    tz_fp, kp_fp = spec_fingerprint(tz_item), spec_fingerprint(kp_item)
    shared = [key for key, value in tz_fp.items() if value and kp_fp.get(key) == value]
    if shared:
        return f"fingerprint:{shared[0]}"
    return None


def _item_blob(item: Item) -> str:
    return f"{item.name} {item.specs} {item.extra.get('article', '')}".lower()


def _fingerprint_part(tz_item: Item, kp_item: Item) -> float:
    tz_fp, kp_fp = spec_fingerprint(tz_item), spec_fingerprint(kp_item)
    parts: list[float] = []
    if tz_fp and kp_fp:
        keys = set(tz_fp) | set(kp_fp)
        overlap = sum(1 for key in keys if tz_fp.get(key) == kp_fp.get(key))
        parts.append(overlap / max(len(keys), 1))
    tz_qty, kp_qty = parse_qty(tz_item.qty), parse_qty(kp_item.qty)
    if tz_qty is not None and kp_qty is not None:
        parts.append(1.0 if tz_qty == kp_qty else 0.0)
    if not parts:
        return 1.0 if _ratio(tz_item.specs, kp_item.specs) >= 0.72 else 0.0
    return sum(parts) / len(parts)


def _embedding_ratio(tz_item: Item, kp_item: Item) -> float | None:
    encoder = _encoder.get()
    if encoder is None:
        return None
    try:
        return float(encoder(tz_item.fingerprint_text, kp_item.fingerprint_text))
    except Exception:  # noqa: BLE001
        return None


def _brief_items(items: list[Item]) -> list[dict[str, str]]:
    return [
        {
            "no": item.no,
            "name": item.name,
            "specs": item.specs,
            "unit": item.unit,
            "qty": item.qty,
            "article": item.extra.get("article", ""),
        }
        for item in items
    ]


def _links_from_greedy(tz_items: list[Item], kp_items: list[Item], score_fn) -> list[dict[str, Any]]:
    used_kp: set[int] = set()
    links: list[dict[str, Any]] = []
    for tz_index, tz_item in enumerate(tz_items):
        best: tuple[float, int] | None = None
        for kp_index, kp_item in enumerate(kp_items):
            if kp_index in used_kp:
                continue
            score = score_fn(tz_item, kp_item)
            if best is None or score > best[0]:
                best = (score, kp_index)
        if best is None or best[0] < ACCEPT:
            continue
        used_kp.add(best[1])
        links.append(
            {
                "tz_index": tz_index,
                "kp_index": best[1],
                "score": best[0],
                "reason": "rule",
            }
        )
    return links
