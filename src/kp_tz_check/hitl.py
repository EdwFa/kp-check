"""Human-in-the-loop decisions for reviewable audit rows."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from kp_tz_check.models import FinalStatus


VALID_ACTIONS = {"confirm", "reject", "keep"}


def apply_hitl_decisions(
    results: list[dict[str, Any]],
    decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply explicit operator decisions and return an append-only audit log.

    A decision is accepted only for a NEEDS_REVIEW row. Missing or invalid
    decisions are ignored and recorded as rejected actions.
    """

    updated = deepcopy(results)
    log: list[dict[str, Any]] = []
    for decision in decisions or []:
        index = decision.get("result_index")
        action = decision.get("action")
        reviewer = str(decision.get("reviewer") or "").strip()
        reason = str(decision.get("reason") or "").strip()
        entry = {
            "result_index": index,
            "action": action,
            "reviewer": reviewer,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "accepted": False,
        }
        if (
            not isinstance(index, int)
            or not 0 <= index < len(updated)
            or action not in VALID_ACTIONS
            or not reviewer
            or not reason
        ):
            entry["error"] = "Нужны корректные индекс, действие, reviewer и reason"
            log.append(entry)
            continue
        current = updated[index]
        if current.get("status") != FinalStatus.NEEDS_REVIEW.value:
            entry["error"] = "Решение HITL разрешено только для статуса «Требует уточнения»"
            log.append(entry)
            continue
        if action == "confirm":
            current["status"] = FinalStatus.MATCH.value
        elif action == "reject":
            current["status"] = FinalStatus.MISMATCH.value
        entry["accepted"] = True
        current.setdefault("comments", []).append(
            f"HITL: {action}; reviewer={reviewer}; причина: {reason}"
        )
        log.append(entry)
    return {"results": updated, "hitl_log": log}
