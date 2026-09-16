"""Регрессионная оценка direct audit против LangGraph-прохода."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from kp_tz_check.checks import audit
from kp_tz_check.graph import run_pack
from kp_tz_check.parse import load_incoming
from kp_tz_check.serde import to_jsonable


def _row_fingerprint(row: dict[str, Any]) -> dict[str, Any]:
    request = row.get("request") or {}
    kp = row.get("kp") or {}
    return {
        "status": row.get("status"),
        "date_mark": row.get("date_mark"),
        "product_mark": row.get("product_mark"),
        "outgoing_no": request.get("outgoing_no"),
        "kp_file": Path(kp["source_file"]).name if kp.get("source_file") else None,
    }


def evaluate_incoming(incoming: Path | str) -> dict[str, Any]:
    incoming = Path(incoming)
    requests, kps, tzs = load_incoming(incoming)
    direct = to_jsonable(audit(requests, kps, tzs))
    graph = run_pack(incoming=incoming)
    direct_rows = [_row_fingerprint(row) for row in direct]
    graph_rows = [_row_fingerprint(row) for row in graph.get("results") or []]
    return {
        "incoming": str(incoming),
        "rows": len(direct_rows),
        "status_exact_match": direct_rows == graph_rows,
        "direct": direct_rows,
        "graph": graph_rows,
        "compliance_log_entries": len(graph.get("compliance_log") or []),
        "hitl_log_entries": len(graph.get("hitl_log") or []),
        "invariants": {
            "no_graph_status_upgrade": all(
                direct_row["status"] == graph_row["status"]
                or direct_row["status"] != "Не соответствует"
                for direct_row, graph_row in zip(direct_rows, graph_rows)
            ),
            "no_hitl_without_decision": not graph.get("hitl_log"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Eval kp-tz-check")
    parser.add_argument("--incoming", type=Path, default=root / "incoming")
    args = parser.parse_args(argv)
    result = evaluate_incoming(args.incoming)
    print(f"Строк: {result['rows']}")
    print(f"Direct == Graph: {'PASS' if result['status_exact_match'] else 'FAIL'}")
    for name, passed in result["invariants"].items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    print(f"Compliance evidence: {result['compliance_log_entries']}")
    print(f"HITL decisions: {result['hitl_log_entries']}")
    return 0 if result["status_exact_match"] and all(result["invariants"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
