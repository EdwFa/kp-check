import json
from pathlib import Path

from kp_tz_check.eval import evaluate_incoming


ROOT = Path(__file__).resolve().parents[1]


def test_incoming_matches_golden_and_graph():
    result = evaluate_incoming(ROOT / "incoming")
    golden = json.loads(
        (ROOT / "tests" / "eval" / "golden_incoming.json").read_text(encoding="utf-8")
    )
    assert result["direct"] == golden
    assert result["status_exact_match"]
    assert all(result["invariants"].values())


def test_eval_reports_compliance_evidence_without_hitl_decisions():
    result = evaluate_incoming(ROOT / "incoming")
    assert result["compliance_log_entries"] >= 1
    assert result["hitl_log_entries"] == 0
