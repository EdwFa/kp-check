from pathlib import Path

from kp_tz_check.journal import (
    append_hitl_decisions,
    load_hitl_decisions,
    pack_fingerprint,
)


def test_pack_fingerprint_changes_when_document_changes(tmp_path: Path):
    root = tmp_path / "incoming"
    (root / "kp").mkdir(parents=True)
    document = root / "kp" / "offer.pdf"
    document.write_bytes(b"one")
    first = pack_fingerprint(root)
    document.write_bytes(b"two")
    assert pack_fingerprint(root) != first


def test_journal_returns_only_decisions_for_same_fingerprint(tmp_path: Path):
    journal = tmp_path / "reports" / "hitl.jsonl"
    decision = {
        "result_index": 1,
        "action": "confirm",
        "reviewer": "edwf",
        "reason": "Проверено",
    }
    append_hitl_decisions(journal, fingerprint="abc", decisions=[decision])
    append_hitl_decisions(
        journal,
        fingerprint="other",
        decisions=[{**decision, "result_index": 2}],
    )
    assert load_hitl_decisions(journal, fingerprint="abc") == [decision]
    assert load_hitl_decisions(journal, fingerprint="missing") == []
