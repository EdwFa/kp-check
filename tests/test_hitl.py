from kp_tz_check.hitl import apply_hitl_decisions
from kp_tz_check.models import FinalStatus


def _results():
    return [
        {
            "status": FinalStatus.NEEDS_REVIEW.value,
            "comments": ["требует ручной проверки"],
        },
        {
            "status": FinalStatus.NEEDS_REVIEW.value,
            "comments": ["требует ручной проверки"],
        },
    ]


def test_hitl_confirm_and_reject_are_explicit_and_logged():
    result = apply_hitl_decisions(
        _results(),
        [
            {
                "result_index": 0,
                "action": "confirm",
                "reviewer": "edwf",
                "reason": "Проверено по оригиналу КП",
            },
            {
                "result_index": 1,
                "action": "reject",
                "reviewer": "edwf",
                "reason": "Подтверждено ответственным сотрудником",
            },
        ],
    )
    assert result["results"][0]["status"] == FinalStatus.MATCH.value
    assert result["results"][1]["status"] == FinalStatus.MISMATCH.value
    assert all(item["accepted"] for item in result["hitl_log"])
    assert all(item["timestamp"] for item in result["hitl_log"])


def test_hitl_does_not_allow_decision_without_reason_or_on_hard_failure():
    results = _results()
    results[1]["status"] = FinalStatus.MISMATCH.value
    result = apply_hitl_decisions(
        results,
        [
            {"result_index": 0, "action": "confirm", "reviewer": "edwf"},
            {
                "result_index": 1,
                "action": "confirm",
                "reviewer": "edwf",
                "reason": "неверное действие",
            },
        ],
    )
    assert result["results"][0]["status"] == FinalStatus.NEEDS_REVIEW.value
    assert result["results"][1]["status"] == FinalStatus.MISMATCH.value
    assert not any(item["accepted"] for item in result["hitl_log"])
