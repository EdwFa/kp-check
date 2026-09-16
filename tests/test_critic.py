from dataclasses import dataclass

from kp_tz_check.critic import apply_critic, reset_critic_proposer, set_critic_proposer
from kp_tz_check.models import FinalStatus, ProductCheckMark
from kp_tz_check.tools import invoke


def _result(outgoing="2738", kp_file="kp.pdf", status=FinalStatus.MATCH.value):
    return {
        "request": {"outgoing_no": outgoing, "source_file": "Запрос.docx"},
        "kp": {"source_file": kp_file},
        "status": status,
        "date_mark": "✅",
        "product_mark": "✅",
        "comments": ["Хронология дат соблюдена", "Позиции ТЗ соответствуют КП"],
        "item_mismatches": [],
    }


def _pair(outgoing="2738", kp_file="kp.pdf", reason="supplier", score=0.5):
    return {
        "request": {"outgoing_no": outgoing},
        "kp": {"source_file": kp_file},
        "reason": reason,
        "score": score,
    }


@dataclass
class FakeCritic:
    actions: list[dict]

    def critique(self, **kwargs):
        return list(self.actions)


def test_gray_pair_lowers_match_to_review():
    out = apply_critic(
        [_result()],
        [_pair()],
        [],
    )
    assert out["results"][0]["status"] == FinalStatus.NEEDS_REVIEW.value
    assert any("серой зоне" in item for item in out["results"][0]["comments"])
    assert any("серой зоне" in item for item in out["critic_log"])


def test_outgoing_pair_is_not_gray_and_cannot_be_rejected():
    token = set_critic_proposer(
        FakeCritic([{"action": "reject_pair", "request_outgoing_no": "2738", "kp_file": "kp.pdf"}])
    )
    try:
        out = apply_critic(
            [_result()],
            [_pair(reason="outgoing_no", score=1.0)],
            [],
        )
        assert out["results"][0]["status"] == FinalStatus.MATCH.value
        assert not any("отклонил пару" in item for item in out["results"][0]["comments"])
    finally:
        reset_critic_proposer(token)


def test_critic_cannot_upgrade_to_match():
    token = set_critic_proposer(FakeCritic([{"action": "upgrade", "request_outgoing_no": "2738"}]))
    try:
        out = apply_critic(
            [_result(status=FinalStatus.NEEDS_REVIEW.value)],
            [_pair(reason="outgoing_no", score=1.0)],
            [],
        )
        assert out["results"][0]["status"] == FinalStatus.NEEDS_REVIEW.value
        assert any("повысить" in item for item in out["critic_log"])
    finally:
        reset_critic_proposer(token)


def test_reject_gray_pair_lowers_to_mismatch():
    token = set_critic_proposer(
        FakeCritic([{"action": "reject_pair", "request_outgoing_no": "2738", "kp_file": "kp.pdf"}])
    )
    try:
        out = apply_critic([_result()], [_pair()], [])
        assert out["results"][0]["status"] == FinalStatus.MISMATCH.value
        assert any("отклонил пару" in item for item in out["results"][0]["comments"])
    finally:
        reset_critic_proposer(token)


def test_reject_article_link_fails_product():
    nomenclature = [
        {
            "request_outgoing_no": "2738",
            "kp_file": "kp.pdf",
            "kp_file_name": "kp.pdf",
            "links": [{"tz_index": 0, "kp_index": 0, "score": 0.3, "reason": "article"}],
            "mismatches": [],
        }
    ]
    token = set_critic_proposer(
        FakeCritic(
            [{"action": "reject_item", "tz_index": 0, "kp_index": 0, "request_outgoing_no": "2738"}]
        )
    )
    try:
        out = apply_critic([_result()], [_pair(reason="outgoing_no", score=1.0)], nomenclature)
        assert out["results"][0]["status"] == FinalStatus.MISMATCH.value
        assert out["results"][0]["product_mark"] == ProductCheckMark.FAIL.value
    finally:
        reset_critic_proposer(token)


def test_critique_pack_tool_roundtrip():
    out = invoke(
        "critique_pack",
        {
            "results": [_result()],
            "pairs": [_pair()],
            "nomenclature": [],
        },
    )
    assert out["results"][0]["status"] == FinalStatus.NEEDS_REVIEW.value
    assert "critic_log" in out
