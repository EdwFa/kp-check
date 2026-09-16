from datetime import date
from pathlib import Path

from kp_tz_check.checks import audit
from kp_tz_check.graph import (
    NODE_AUDIT,
    NODE_COMPLIANCE,
    NODE_CRITIC,
    NODE_HITL,
    NODE_LOAD,
    NODE_NOMENCLATURE,
    NODE_PAIR,
    NODE_REPORT,
    audit_node,
    compliance_node,
    critic_node,
    get_pack_graph,
    load_node,
    nomenclature_node,
    hitl_node,
    pair_node,
    run_pack,
)
from kp_tz_check.models import Item, RequestRecord, TzRecord
from kp_tz_check.parse import load_incoming
from kp_tz_check.report import render_text
from kp_tz_check.serde import to_jsonable

ROOT = Path(__file__).resolve().parents[1]


def _fingerprint(results: list[dict]) -> list[dict]:
    rows = []
    for item in results:
        request = item.get("request") or {}
        kp = item.get("kp") or {}
        rows.append(
            {
                "status": item["status"],
                "date_mark": item["date_mark"],
                "product_mark": item["product_mark"],
                "comments": item["comments"],
                "outgoing_no": request.get("outgoing_no"),
                "kp_file": Path(kp["source_file"]).name if kp.get("source_file") else None,
            }
        )
    return rows


def test_graph_nodes_call_tools_not_llm():
    import inspect

    for fn in (
        load_node,
        pair_node,
        nomenclature_node,
        audit_node,
        compliance_node,
        critic_node,
        hitl_node,
    ):
        source = inspect.getsource(fn)
        if fn is not hitl_node:
            assert "invoke(" in source
        assert "ChatOpenAI" not in source
        assert "openai" not in source.lower()
        assert "anthropic" not in source.lower()
    assert "structure_incoming" in inspect.getsource(load_node)
    assert "match_nomenclature" in inspect.getsource(nomenclature_node)
    assert "critique_pack" in inspect.getsource(critic_node)
    assert "comply_pack" in inspect.getsource(compliance_node)
    assert "apply_hitl_decisions" in inspect.getsource(hitl_node)
    graph = get_pack_graph()
    assert set(graph.nodes) >= {
        NODE_LOAD,
        NODE_PAIR,
        NODE_NOMENCLATURE,
        NODE_AUDIT,
        NODE_COMPLIANCE,
        NODE_CRITIC,
        NODE_HITL,
        NODE_REPORT,
    }


def test_graph_skip_load_matches_direct_audit():
    request = RequestRecord(
        source_file=Path("Запрос.docx"),
        outgoing_no="2738",
        sent_on=date(2026, 8, 27),
        sent_on_raw="27.08.2026",
        supplier="ООО Апиген",
        email="sales@apigene.ru",
    )
    tz = TzRecord(
        source_file=Path("ТЗ.doc"),
        title="ТЗ",
        items=[Item(no="1", name="Набор", specs="300 циклов", unit="шт.", qty="12")],
    )
    direct = audit([request], [], [tz])
    state = run_pack(
        skip_load=True,
        requests=to_jsonable([request]),
        kps=[],
        tzs=to_jsonable([tz]),
    )
    assert _fingerprint(state["results"]) == _fingerprint(to_jsonable(direct))
    assert state["report_text"] == render_text(direct)
    assert state["pairs"] == []
    assert len(state["unmatched_requests"]) == 1
    assert state["unmatched_kps"] == []


def test_graph_incoming_matches_cli_audit(tmp_path):
    incoming = ROOT / "incoming"
    requests, kps, tzs = load_incoming(incoming)
    direct = audit(requests, kps, tzs)
    out = tmp_path / "report.html"
    state = run_pack(incoming=incoming, out=out)
    assert _fingerprint(state["results"]) == _fingerprint(to_jsonable(direct))
    assert state["report_text"] == render_text(direct)
    assert out.exists()
    assert "Проверка комплекта" in out.read_text(encoding="utf-8")
    assert "Доказательства compliance" in out.read_text(encoding="utf-8")
    assert state["compliance_log"]
    assert len(state["requests"]) == len(requests)
    assert len(state["kps"]) == len(kps)
    assert {item["reason"] for item in state["pairs"]} == {"outgoing_no"}
    assert len(state["pairs"]) == 3
    assert len(state["unmatched_requests"]) == 2
    assert len(state["nomenclature"]) == 3
