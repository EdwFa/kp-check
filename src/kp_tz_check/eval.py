"""Регрессионная оценка direct audit против LangGraph-прохода."""

from __future__ import annotations

import argparse
import copy
import json
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
    requests, kps, tzs, _applications = load_incoming(incoming)
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


def evaluate_golden(
    incoming: Path | str,
    golden_path: Path | str,
) -> dict[str, Any]:
    """Сравнивает direct audit с ожидаемым golden-результатом."""
    import json

    incoming = Path(incoming)
    golden_path = Path(golden_path)
    result = evaluate_incoming(incoming)
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    actual = result["direct"]
    mismatches = [
        {
            "row": index + 1,
            "expected": expected_row,
            "actual": actual[index] if index < len(actual) else None,
        }
        for index, expected_row in enumerate(expected)
        if index >= len(actual) or actual[index] != expected_row
    ]
    if len(actual) > len(expected):
        mismatches.extend(
            {
                "row": index + 1,
                "expected": None,
                "actual": actual[index],
            }
            for index in range(len(expected), len(actual))
        )
    return {
        "case": golden_path.name,
        "expected_rows": len(expected),
        "actual_rows": len(actual),
        "passed": not mismatches,
        "mismatches": mismatches,
        "graph_passed": result["status_exact_match"]
        and all(result["invariants"].values()),
    }


def evaluate_suite(
    incoming: Path | str,
    cases_dir: Path | str,
) -> dict[str, Any]:
    """Запускает доступные golden-кейсы и сообщает об отсутствующих negative-кейсах."""
    cases_dir = Path(cases_dir)
    golden_cases = sorted(cases_dir.glob("golden*.json"))
    negative_cases = sorted(cases_dir.glob("negative*.json"))
    cases = [evaluate_golden(incoming, path) for path in golden_cases]
    negative_results = evaluate_negative_cases(incoming, negative_cases[0]) if negative_cases else []
    return {
        "cases": cases,
        "golden_count": len(golden_cases),
        "negative_count": len(negative_results),
        "negative_results": negative_results,
        "passed": all(item["passed"] and item["graph_passed"] for item in cases)
        and all(item["passed"] for item in negative_results),
        "negative_cases": [path.name for path in negative_cases],
    }


def evaluate_negative_cases(
    incoming: Path | str,
    cases_path: Path | str,
) -> list[dict[str, Any]]:
    """Проверяет, что намеренные дефекты не проходят как MATCH."""
    from datetime import timedelta

    incoming = Path(incoming)
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for case in cases:
        requests, kps, tzs, _applications = load_incoming(incoming)
        requests, kps, tzs = copy.deepcopy((requests, kps, tzs))
        operation = case["operation"]
        if operation == "missing_kp":
            kps.pop()
        elif operation == "supplier_mismatch":
            kps[0].supplier = "ООО Несовпадающий поставщик"
        elif operation == "date_violation":
            kps[0].prepared_on = requests[0].sent_on - timedelta(days=1)
        elif operation == "unit_mismatch":
            kps[0].items[0].unit = "кг"
        elif operation == "spec_mismatch":
            kps[0].items[0].specs = f"{kps[0].items[0].specs} 999 Гб"
        else:
            raise ValueError(f"Неизвестная negative-операция: {operation}")

        audited = to_jsonable(audit(requests, kps, tzs))
        statuses = [row["status"] for row in audited]
        passed = any(status != "Соответствует" for status in statuses)
        results.append(
            {
                "case": case["id"],
                "description": case["description"],
                "operation": operation,
                "statuses": statuses,
                "passed": passed,
            }
        )
    return results


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
