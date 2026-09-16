"""Проверка неявных нормативных правил через OKF-концепции.

Compliance не выбирает итоговый статус вместо audit. Он добавляет только
проверяемые пояснения и понижает MATCH при подтверждённом нарушении.
"""

from __future__ import annotations

import copy
from typing import Any

from kp_tz_check.calculations import check_spec_constraint, collect_market_prices
from kp_tz_check.knowledge import Concept, get_concepts
from kp_tz_check.models import FinalStatus


def _lower_status(status: str, target: FinalStatus) -> str:
    rank = {
        FinalStatus.MISMATCH.value: 0,
        FinalStatus.NEEDS_REVIEW.value: 1,
        FinalStatus.MATCH.value: 2,
    }
    return target.value if rank.get(status, 0) > rank[target.value] else status


def _concept_span(concept: Concept, phrase: str) -> str | None:
    if phrase.lower() in concept.body.lower():
        return phrase
    return None


def apply_compliance(
    results: list[dict[str, Any]],
    *,
    kps: list[dict[str, Any]] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(results)
    concepts = get_concepts(tags=["instruction"], root=root)
    quote = next((item for item in concepts if item.type == "Quote"), None)
    playbook = next((item for item in concepts if item.type == "Playbook"), None)
    log: list[dict[str, Any]] = []

    # Цены проверяем только при наличии хотя бы одного явного ценового поля.
    # Иначе старый парсер не может отличить отсутствие цены от КП без цены.
    offers = kps or []
    has_price_field = any(
        (item.get("extra") or {}).get("price")
        for offer in offers
        for item in offer.get("items") or []
    )
    if has_price_field:
        market = collect_market_prices(offers)
        log.append(
            {
                "concept_id": "quotes/market-variation",
                "type": "calculation",
                "source": "docs/laws/Положение 223-ФЗ от 27.03.2026 г..docx",
                "evidence": market,
            }
        )
        if market["status"] in {"heterogeneous", "insufficient_data"}:
            target = (
                FinalStatus.NEEDS_REVIEW
                if market["status"] == "heterogeneous"
                else FinalStatus.NEEDS_REVIEW
            )
            for result in updated:
                result["status"] = _lower_status(result.get("status", ""), target)

    for result in updated:
        mismatches = result.get("item_mismatches") or []
        for mismatch in mismatches:
            if mismatch.get("kind") != "instruction":
                continue
            tz_item = mismatch.get("tz_item") or {}
            kp_item = mismatch.get("kp_item") or {}
            check = check_spec_constraint(tz_item.get("specs", ""), kp_item.get("specs", ""))
            if check["status"] not in {"fail", "insufficient_data"}:
                continue
            phrase = "не допускается использование двусмысленных толкований"
            source = quote or playbook
            span = _concept_span(source, phrase) if source else None
            if span is None:
                log.append({"concept_id": source.concept_id if source else None, "status": "missing_span"})
                continue
            if check["status"] == "fail":
                result["status"] = _lower_status(result.get("status", ""), FinalStatus.MISMATCH)
            else:
                result["status"] = _lower_status(result.get("status", ""), FinalStatus.NEEDS_REVIEW)
            comment = f"Compliance: {mismatch.get('detail', 'проверка инструкции')}. Цитата: «{span}»"
            if comment not in result.setdefault("comments", []):
                result["comments"].append(comment)
            log.append(
                {
                    "concept_id": source.concept_id,
                    "type": source.type,
                    "status": check["status"],
                    "span": span,
                    "source": source.metadata.get("sources"),
                    "evidence": {
                        "request_item": tz_item,
                        "kp_item": kp_item,
                        "check": check,
                    },
                }
            )
    return {"results": updated, "compliance_log": log}
