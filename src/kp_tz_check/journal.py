"""Persistent, fingerprint-bound HITL decision journal."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from kp_tz_check.characteristic_search import build_characteristic_query
from kp_tz_check.redaction import build_contours


DOC_EXTENSIONS = {".doc", ".docx", ".docm", ".dotx", ".pdf"}


def pack_fingerprint(root: Path | str) -> str:
    root = Path(root)
    digest = hashlib.sha256()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in DOC_EXTENSIONS
    )
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def append_conclusion_ack(
    journal_path: Path | str,
    *,
    fingerprint: str,
    verdict: str,
    reviewer: str,
) -> dict[str, Any]:
    record = {
        "kind": "conclusion",
        "verdict": verdict,
        "reviewer": reviewer,
        "fingerprint": fingerprint,
    }
    append_hitl_decisions(journal_path, fingerprint=fingerprint, decisions=[record])
    return record


def append_hitl_decisions(
    journal_path: Path | str,
    *,
    fingerprint: str,
    decisions: list[dict[str, Any]],
) -> None:
    path = Path(journal_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for decision in decisions:
            record = {
                "fingerprint": fingerprint,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                **decision,
            }
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def load_hitl_decisions(
    journal_path: Path | str,
    *,
    fingerprint: str,
) -> list[dict[str, Any]]:
    path = Path(journal_path)
    if not path.exists():
        return []
    decisions: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Некорректная запись HITL в строке {line_number}") from exc
        if record.get("kind") in {"conclusion", "contract", "characteristic"}:
            continue
        if record.get("fingerprint") == fingerprint:
            decisions.append(
                {
                    key: record[key]
                    for key in ("result_index", "action", "reviewer", "reason")
                    if key in record
                }
            )
    return decisions


def load_conclusion_acks(
    journal_path: Path | str,
    *,
    fingerprint: str,
) -> list[dict[str, Any]]:
    path = Path(journal_path)
    if not path.exists():
        return []
    acks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("fingerprint") == fingerprint and record.get("kind") == "conclusion":
            acks.append(
                {
                    "kind": "conclusion",
                    "verdict": record.get("verdict"),
                    "reviewer": record.get("reviewer"),
                    "accepted": True,
                }
            )
    return acks


def append_characteristic_record(
    journal_path: Path | str,
    *,
    fingerprint: str,
    operator: str,
    query: dict,
    urls: list[str],
    page_hash: str,
) -> dict[str, Any]:
    record = {
        "kind": "characteristic",
        "operator": build_contours({"operator": operator})["journal_code"],
        "query": build_characteristic_query(query)["query"],
        "urls": [str(url) for url in urls],
        "page_hash": str(page_hash),
    }
    append_hitl_decisions(journal_path, fingerprint=fingerprint, decisions=[record])
    return record


def append_contract_record(
    journal_path: Path | str,
    *,
    fingerprint: str,
    operator: str,
    reason: str,
    filename: str,
    winner: str = "",
) -> dict[str, Any]:
    record = {
        "kind": "contract",
        "operator": operator,
        "reason": reason,
        "filename": filename,
        "winner": winner,
    }
    append_hitl_decisions(journal_path, fingerprint=fingerprint, decisions=[record])
    return record
