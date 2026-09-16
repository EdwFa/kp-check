"""Critic: только серая зона. Статус можно понизить, поднять до «Соответствует» нельзя."""

from __future__ import annotations

import copy
from contextvars import ContextVar
from typing import Any, Protocol

from kp_tz_check.models import FinalStatus, ProductCheckMark

GRAY_MIN = 0.45
GRAY_MAX = 0.70
REVIEW_NOTE = "требует ручной проверки"

_RANK = {
    FinalStatus.MISMATCH.value: 0,
    FinalStatus.NEEDS_REVIEW.value: 1,
    FinalStatus.MATCH.value: 2,
}

_proposer: ContextVar["CriticProposer | None"] = ContextVar("critic_proposer", default=None)


class CriticProposer(Protocol):
    def critique(
        self,
        *,
        gray_pairs: list[dict[str, Any]],
        gray_links: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """actions: reject_pair | reject_item | downgrade. upgrade игнорируется."""
        ...


def get_critic_proposer() -> CriticProposer | None:
    return _proposer.get()


def set_critic_proposer(proposer: CriticProposer | None):
    return _proposer.set(proposer)


def reset_critic_proposer(token) -> None:
    _proposer.reset(token)


def in_gray(score: Any) -> bool:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return False
    return GRAY_MIN <= value <= GRAY_MAX


def pair_is_gray(pair: dict[str, Any]) -> bool:
    if (pair.get("reason") or "") == "outgoing_no":
        return False
    return in_gray(pair.get("score") or 0)


def link_is_reviewable(link: dict[str, Any]) -> bool:
    reason = link.get("reason") or ""
    if reason == "article":
        return True
    if reason == "rule":
        return in_gray(link.get("score") or 0)
    return in_gray(link.get("score") or 0)


def apply_critic(
    results: list[dict[str, Any]],
    pairs: list[dict[str, Any]] | None = None,
    nomenclature: list[dict[str, Any]] | None = None,
    proposer: CriticProposer | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(results)
    log: list[str] = []
    pairs = pairs or []
    nomenclature = nomenclature or []
    proposer = proposer if proposer is not None else get_critic_proposer()

    gray_pairs = [item for item in pairs if pair_is_gray(item)]
    gray_links = _collect_gray_links(nomenclature)

    for pair in gray_pairs:
        comment = (
            f"Critic: пара в серой зоне ({pair.get('reason')}, score={_fmt_score(pair.get('score'))}), "
            f"{REVIEW_NOTE}"
        )
        target = _find_result(updated, pair)
        if target is None:
            continue
        _add_comment(target, comment)
        _lower_status(target, FinalStatus.NEEDS_REVIEW)
        log.append(comment)

    for item in gray_links:
        comment = (
            f"Critic: позиция в серой зоне ({item['link'].get('reason')}, "
            f"score={_fmt_score(item['link'].get('score'))}), {REVIEW_NOTE}"
        )
        target = _find_result_by_keys(updated, item.get("outgoing_no"), item.get("kp_file"))
        if target is None:
            continue
        _add_comment(target, comment)
        _lower_status(target, FinalStatus.NEEDS_REVIEW)
        log.append(comment)

    for action in _safe_critique(proposer, gray_pairs, gray_links):
        kind = action.get("action")
        if kind in {"upgrade", "accept", "raise"}:
            log.append("Critic: попытка повысить статус проигнорирована")
            continue
        if kind == "reject_pair":
            applied = _reject_pair(updated, pairs, action)
            log.append(applied or "Critic: reject_pair отклонён — цель не в серой зоне")
        elif kind == "reject_item":
            applied = _reject_item(updated, gray_links, action)
            log.append(applied or "Critic: reject_item отклонён — цель не в серой зоне")
        elif kind == "downgrade":
            target = _find_result_by_keys(
                updated, action.get("request_outgoing_no"), action.get("kp_file")
            )
            if target:
                _add_comment(target, action.get("comment") or f"Critic: {REVIEW_NOTE}")
                _lower_status(target, FinalStatus.NEEDS_REVIEW)
                log.append("Critic: принудительное понижение до «Требует уточнения»")

    return {"results": updated, "critic_log": _unique(log)}


def _collect_gray_links(nomenclature: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = []
    for row in nomenclature:
        outgoing = row.get("request_outgoing_no")
        kp_file = row.get("kp_file_name") or row.get("kp_file")
        for link in row.get("links") or []:
            if not link_is_reviewable(link):
                continue
            found.append({"outgoing_no": outgoing, "kp_file": kp_file, "link": link, "row": row})
    return found


def _safe_critique(
    proposer: CriticProposer | None,
    gray_pairs: list[dict[str, Any]],
    gray_links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if proposer is None:
        return []
    try:
        return list(proposer.critique(gray_pairs=gray_pairs, gray_links=gray_links) or [])
    except Exception as exc:  # noqa: BLE001
        return [{"action": "downgrade", "comment": f"Critic не ответил ({exc}), {REVIEW_NOTE}"}]


def _reject_pair(
    results: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    action: dict[str, Any],
) -> str | None:
    pair = _resolve_pair(pairs, action)
    if pair is None or not pair_is_gray(pair):
        return None
    target = _find_result(results, pair)
    if target is None:
        return None
    comment = (
        f"Critic отклонил пару в серой зоне ({pair.get('reason')}, "
        f"score={_fmt_score(pair.get('score'))})"
    )
    _add_comment(target, comment)
    _lower_status(target, FinalStatus.MISMATCH)
    return comment


def _reject_item(
    results: list[dict[str, Any]],
    gray_links: list[dict[str, Any]],
    action: dict[str, Any],
) -> str | None:
    hit = None
    for item in gray_links:
        link = item["link"]
        if int(link.get("tz_index", -1)) == int(action.get("tz_index", -2)) and int(
            link.get("kp_index", -1)
        ) == int(action.get("kp_index", -2)):
            if action.get("request_outgoing_no") and action["request_outgoing_no"] != item.get("outgoing_no"):
                continue
            hit = item
            break
    if hit is None:
        return None
    target = _find_result_by_keys(results, hit.get("outgoing_no"), hit.get("kp_file"))
    if target is None:
        return None
    comment = (
        f"Critic отклонил позицию в серой зоне (tz={hit['link'].get('tz_index')}, "
        f"kp={hit['link'].get('kp_index')})"
    )
    _add_comment(target, comment)
    _add_comment(target, "Позиция ТЗ не найдена в КП: отклонено critic")
    target["product_mark"] = ProductCheckMark.FAIL.value
    _lower_status(target, FinalStatus.MISMATCH)
    return comment


def _resolve_pair(pairs: list[dict[str, Any]], action: dict[str, Any]) -> dict[str, Any] | None:
    outgoing = action.get("request_outgoing_no")
    kp_file = action.get("kp_file")
    for pair in pairs:
        if _pair_outgoing(pair) != outgoing:
            continue
        if kp_file and _pair_kp_name(pair) != _file_name(kp_file):
            continue
        return pair
    return None


def _find_result(results: list[dict[str, Any]], pair: dict[str, Any]) -> dict[str, Any] | None:
    return _find_result_by_keys(results, _pair_outgoing(pair), _pair_kp_name(pair))


def _find_result_by_keys(
    results: list[dict[str, Any]], outgoing: str | None, kp_file: str | None
) -> dict[str, Any] | None:
    kp_name = _file_name(kp_file) if kp_file else None
    for item in results:
        request = item.get("request") or {}
        kp = item.get("kp") or {}
        if request.get("outgoing_no") != outgoing:
            continue
        if kp_name and _file_name(kp.get("source_file")) != kp_name:
            continue
        return item
    return None


def _pair_outgoing(pair: dict[str, Any]) -> str | None:
    request = pair.get("request") or {}
    return request.get("outgoing_no")


def _pair_kp_name(pair: dict[str, Any]) -> str | None:
    kp = pair.get("kp") or {}
    return _file_name(kp.get("source_file"))


def _file_name(path: str | None) -> str | None:
    if not path:
        return None
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def _lower_status(result: dict[str, Any], proposed: FinalStatus) -> None:
    current = result.get("status") or FinalStatus.MATCH.value
    if _RANK.get(proposed.value, 0) < _RANK.get(current, 0):
        result["status"] = proposed.value


def _add_comment(result: dict[str, Any], comment: str) -> None:
    comments = list(result.get("comments") or [])
    if comment not in comments:
        comments.append(comment)
    result["comments"] = comments


def _fmt_score(score: Any) -> str:
    try:
        return f"{float(score):.2f}"
    except (TypeError, ValueError):
        return "?"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = (value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result
