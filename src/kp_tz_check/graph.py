"""LangGraph-каркас комплекта: ноды зовут tools.

Цепочка: structure_incoming → pair → nomenclature → audit → critic → report.
Critic смотрит серую зону и может только понизить статус.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from kp_tz_check.models import PairResult
from kp_tz_check.report import render_html, render_text, write_html_report
from kp_tz_check.serde import from_jsonable
from kp_tz_check.tools import invoke

NODE_LOAD = "load"
NODE_PAIR = "pair"
NODE_NOMENCLATURE = "nomenclature"
NODE_AUDIT = "audit"
NODE_COMPLIANCE = "compliance"
NODE_CRITIC = "critic"
NODE_HITL = "hitl"
NODE_REPORT = "report"


class PackState(TypedDict, total=False):
    incoming: str
    out: str
    skip_load: bool
    requests: list[dict[str, Any]]
    kps: list[dict[str, Any]]
    tzs: list[dict[str, Any]]
    pairs: list[dict[str, Any]]
    unmatched_requests: list[dict[str, Any]]
    unmatched_kps: list[dict[str, Any]]
    nomenclature: list[dict[str, Any]]
    results: list[dict[str, Any]]
    compliance_log: list[dict[str, Any]]
    critic_log: list[str]
    hitl_decisions: list[dict[str, Any]]
    hitl_log: list[dict[str, Any]]
    summary: dict[str, Any]
    report_text: str
    report_html: str
    report_path: str


def load_node(state: PackState) -> dict[str, Any]:
    if state.get("skip_load"):
        return {}
    incoming = state.get("incoming")
    if not incoming:
        raise ValueError("incoming обязателен, если skip_load не задан")
    return invoke("structure_incoming", {"incoming": incoming})


def pair_node(state: PackState) -> dict[str, Any]:
    return invoke(
        "pair_requests_and_kps",
        {
            "requests": state.get("requests") or [],
            "kps": state.get("kps") or [],
        },
    )


def nomenclature_node(state: PackState) -> dict[str, Any]:
    return invoke(
        "match_nomenclature",
        {
            "tzs": state.get("tzs") or [],
            "pairs": state.get("pairs") or [],
        },
    )


def audit_node(state: PackState) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "requests": state.get("requests") or [],
        "kps": state.get("kps") or [],
        "tzs": state.get("tzs") or [],
    }
    if "pairs" in state:
        payload["pairs"] = state.get("pairs") or []
    if "nomenclature" in state:
        payload["nomenclature"] = state.get("nomenclature") or []
    return invoke("audit", payload)


def critic_node(state: PackState) -> dict[str, Any]:
    return invoke(
        "critique_pack",
        {
            "results": state.get("results") or [],
            "pairs": state.get("pairs") or [],
            "nomenclature": state.get("nomenclature") or [],
        },
    )


def compliance_node(state: PackState) -> dict[str, Any]:
    return invoke(
        "comply_pack",
        {
            "results": state.get("results") or [],
            "kps": state.get("kps") or [],
        },
    )


def hitl_node(state: PackState) -> dict[str, Any]:
    from kp_tz_check.hitl import apply_hitl_decisions

    return apply_hitl_decisions(
        state.get("results") or [],
        state.get("hitl_decisions") or [],
    )


def report_node(state: PackState) -> dict[str, Any]:
    results = [from_jsonable(PairResult, item) for item in state.get("results") or []]
    compliance_log = state.get("compliance_log") or []
    hitl_log = state.get("hitl_log") or []
    update: dict[str, Any] = {
        "report_text": render_text(results),
        "report_html": render_html(
            results,
            compliance_log=compliance_log,
            hitl_log=hitl_log,
        ),
    }
    dest = state.get("out")
    if dest:
        update["report_path"] = str(
            write_html_report(
                results,
                Path(dest),
                compliance_log=compliance_log,
                hitl_log=hitl_log,
            )
        )
    return update


def build_pack_graph():
    builder = StateGraph(PackState)
    builder.add_node(NODE_LOAD, load_node)
    builder.add_node(NODE_PAIR, pair_node)
    builder.add_node(NODE_NOMENCLATURE, nomenclature_node)
    builder.add_node(NODE_AUDIT, audit_node)
    builder.add_node(NODE_COMPLIANCE, compliance_node)
    builder.add_node(NODE_CRITIC, critic_node)
    builder.add_node(NODE_HITL, hitl_node)
    builder.add_node(NODE_REPORT, report_node)
    builder.add_edge(START, NODE_LOAD)
    builder.add_edge(NODE_LOAD, NODE_PAIR)
    builder.add_edge(NODE_PAIR, NODE_NOMENCLATURE)
    builder.add_edge(NODE_NOMENCLATURE, NODE_AUDIT)
    builder.add_edge(NODE_AUDIT, NODE_COMPLIANCE)
    builder.add_edge(NODE_COMPLIANCE, NODE_CRITIC)
    builder.add_edge(NODE_CRITIC, NODE_HITL)
    builder.add_edge(NODE_HITL, NODE_REPORT)
    builder.add_edge(NODE_REPORT, END)
    return builder.compile()


_compiled = None


def get_pack_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_pack_graph()
    return _compiled


def run_pack(
    *,
    incoming: Path | str | None = None,
    out: Path | str | None = None,
    skip_load: bool = False,
    requests: list[dict[str, Any]] | None = None,
    kps: list[dict[str, Any]] | None = None,
    tzs: list[dict[str, Any]] | None = None,
    hitl_decisions: list[dict[str, Any]] | None = None,
    llm_client: Any | None = None,
) -> PackState:
    payload: PackState = {}
    if incoming is not None:
        payload["incoming"] = str(incoming)
    if out is not None:
        payload["out"] = str(out)
    if skip_load:
        payload["skip_load"] = True
        payload["requests"] = list(requests or [])
        payload["kps"] = list(kps or [])
        payload["tzs"] = list(tzs or [])
    if hitl_decisions is not None:
        payload["hitl_decisions"] = list(hitl_decisions)
    from kp_tz_check.llm_proposers import private_llm_context

    with private_llm_context(llm_client):
        return get_pack_graph().invoke(payload)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Сверка комплекта через LangGraph (без LLM)")
    parser.add_argument("--incoming", type=Path, default=root / "incoming")
    parser.add_argument("--out", type=Path, default=root / "reports" / "report.html")
    args = parser.parse_args(argv)
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    state = run_pack(incoming=args.incoming, out=args.out)
    print(state.get("report_text") or "")
    print(f"\nHTML-отчёт: {state.get('report_path') or args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
