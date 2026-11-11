import hashlib
import json
from pathlib import Path

import pytest

from kp_tz_check.characteristic_search import (
    DATE_MISSING,
    FLAG,
    REGISTRY_NOTE,
    SEARCH_INCOMPLETE,
    AllowlistClient,
    CharacteristicConfigError,
    DisabledLookup,
    FixtureLookup,
    build_characteristic_lookup,
    build_characteristic_query,
    build_live_lookup,
    describe_pages,
    load_allowlist,
)
from kp_tz_check.contract_check import NO_SPEC
from kp_tz_check.journal import append_characteristic_record, append_hitl_decisions, load_hitl_decisions
from kp_tz_check.risk_report import UNCHECKED, build_risk_report, render_risk_html


CUSTOMER = "Заказчик Пример"
FIO = "Иванов Иван Иванович"
ROOT = Path(__file__).resolve().parents[1]


def _param(name, value, unit="шт", from_table=True):
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "required": True,
        "from_table": from_table,
    }


def _page(url, text, checked_at="02.11.2026"):
    return {"url": url, "text": text, "checked_at": checked_at}


def _allow(*hosts):
    classes = [
        "официальный сайт производителя",
        "государственный реестр",
        "сторонний ресурс",
    ]
    return [
        {"host": host, "source_class": classes[index]}
        for index, host in enumerate(hosts)
    ]


class _Boom:
    def lookup(self, query):
        raise AssertionError(query)


def test_disabled_report_matches_sprint_15():
    report = build_risk_report([_param("срок", "12")], None)
    assert report["percent"] is None
    assert report["specification"]["status"] == NO_SPEC
    assert report["sources"]["internet_search"] is False
    assert report["sources"]["resources"] == []
    assert report["candidates"] == []
    html = render_risk_html(report)
    assert NO_SPEC in html
    assert "http" not in html


def test_local_specification_does_not_call_the_client():
    report = build_risk_report(
        [_param("срок", "12")],
        [_param("срок", "12")],
        lookup=_Boom(),
        query={"name": "Набор", "customer": CUSTOMER},
    )
    assert report["sources"]["status"] == "локальная спецификация, интернет не использовался"
    assert report["sources"]["internet_search"] is False


def test_fixture_candidates_do_not_score_a_percent():
    lookup = FixtureLookup(
        [_page("https://a.example/item", "срок | 12 | месяцев")]
    )
    report = build_risk_report(
        [_param("срок", "12", "месяцев")],
        None,
        lookup=lookup,
        query={"name": "Набор"},
        allowlist=_allow("a.example"),
    )
    assert report["percent"] is None
    assert report["risks"][0]["status"] == UNCHECKED
    assert report["risks"][0]["probability"] == UNCHECKED
    assert report["candidates"][0]["from_table"] is False
    assert lookup.calls == [
        {"name": "Набор", "manufacturer": "", "article": "", "registration": ""}
    ]


def test_flag_without_client_raises(monkeypatch):
    monkeypatch.setenv("KP_CHARACTERISTIC_SEARCH", "1")
    with pytest.raises(CharacteristicConfigError):
        build_characteristic_lookup(None)


def test_flag_off_ignores_a_client(monkeypatch):
    monkeypatch.delenv("KP_CHARACTERISTIC_SEARCH", raising=False)
    lookup = build_characteristic_lookup(_Boom())
    assert isinstance(lookup, DisabledLookup)
    assert lookup.lookup({"name": "Набор"})["internet_search"] is False


def test_query_drops_customer_and_does_not_call_when_empty():
    built = build_characteristic_query(
        {
            "name": "Набор",
            "customer": CUSTOMER,
            "operator": FIO,
            "director": FIO,
        }
    )
    encoded = json.dumps(built, ensure_ascii=False)
    assert CUSTOMER not in encoded
    assert FIO not in encoded
    lookup = FixtureLookup([])
    report = build_risk_report(
        [_param("срок", "12")],
        None,
        lookup=lookup,
        query={"customer": CUSTOMER, "director": FIO},
    )
    assert lookup.calls == []
    assert report["sources"]["status"] == "недостаточно данных"
    assert CUSTOMER not in json.dumps(report, ensure_ascii=False)
    assert FIO not in json.dumps(report, ensure_ascii=False)


def test_unlabeled_page_extracts_nothing():
    described = describe_pages(
        [_page("https://a.example/item", "абзац без подписи параметра")],
        _allow("a.example"),
    )
    assert described["candidates"] == []
    assert described["status"] == "источники проверены, характеристики не извлечены"


def test_three_hosts_confirm_a_candidate_and_html_lists_only_returned_urls():
    pages = [
        _page("https://a.example/1", "срок | 12 | месяцев"),
        _page("https://b.example/1", "срок | 12 | месяцев", checked_at=""),
        _page("https://c.example/1", "срок | 12 | месяцев"),
        _page("https://stranger.example/1", "срок | 99 | месяцев"),
    ]
    report = build_risk_report(
        [_param("срок", "12", "месяцев")],
        None,
        lookup=FixtureLookup(pages),
        query={"name": "Набор", "customer": CUSTOMER, "operator": FIO},
        allowlist=_allow("a.example", "b.example", "c.example"),
    )
    assert report["percent"] is None
    assert report["candidates"][0]["note"] == "кандидат подтверждён источниками"
    assert report["sources"]["resources"][1]["checked_at"] == DATE_MISSING
    assert report["sources"]["resources"][1]["source_class"] == "государственный реестр"
    html = render_risk_html(report)
    assert "https://a.example/1" in html
    assert "https://b.example/1" in html
    assert "https://c.example/1" in html
    assert "stranger.example" not in html
    assert REGISTRY_NOTE in html
    assert CUSTOMER not in html
    assert FIO not in html
    assert DATE_MISSING in html


def test_two_mirrors_of_one_host_are_one_source():
    pages = [
        _page("https://a.example/1", "срок | 12 | месяцев"),
        _page("https://www.a.example/2", "срок | 12 | месяцев"),
        _page("https://b.example/1", "срок | 12 | месяцев"),
    ]
    described = describe_pages(pages, _allow("a.example", "b.example"))
    assert described["candidates"][0]["note"] == "недостаточно источников"


def test_unknown_class_is_not_rewritten_as_official():
    described = describe_pages(
        [_page("https://a.example/1", "срок | 12 | месяцев")],
        [{"host": "a.example", "source_class": "сайт"}],
    )
    assert described["resources"] == []
    assert "официальный сайт производителя" not in json.dumps(described, ensure_ascii=False)


def test_example_allowlist_is_not_used_by_a_normal_report():
    readme = (ROOT / "data" / "characteristics" / "README.md").read_text(encoding="utf-8")
    assert "не загружается" in readme
    rows = load_allowlist(ROOT / "data" / "characteristics" / "allowlist.example.csv")
    assert rows[1]["source_class"] == "государственный реестр"
    report = build_risk_report([_param("срок", "12")], None)
    assert report["sources"]["internet_search"] is False


def test_characteristic_journal_skips_hitl_and_omits_page_html(tmp_path: Path):
    journal = tmp_path / "hitl.jsonl"
    secret = "<html>секрет страницы"
    decision = {
        "result_index": 1,
        "action": "confirm",
        "reviewer": "edwf",
        "reason": "Проверено",
    }
    append_hitl_decisions(journal, fingerprint="abc", decisions=[decision])
    append_characteristic_record(
        journal,
        fingerprint="abc",
        operator=FIO,
        query={"name": "Набор", "customer": CUSTOMER},
        urls=["https://a.example/1"],
        page_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
    )
    saved = journal.read_text(encoding="utf-8")
    assert secret not in saved
    assert FIO not in saved
    assert CUSTOMER not in saved
    assert '"kind": "characteristic"' in saved
    assert load_hitl_decisions(journal, fingerprint="abc") == [decision]


def _allow_file(path: Path) -> Path:
    path.write_text(
        "host,source_class\n"
        "maker.example,официальный сайт производителя\n"
        "catalog.example,сторонний ресурс\n",
        encoding="utf-8",
    )
    return path


def test_flag_off_report_does_not_call_transport(monkeypatch, tmp_path: Path):
    monkeypatch.delenv(FLAG, raising=False)
    calls = []

    def transport(url, timeout):
        calls.append(url)
        raise AssertionError(url)

    lookup = build_live_lookup(_allow_file(tmp_path / "allow.csv"), transport)
    assert isinstance(lookup, DisabledLookup)
    lookup.lookup({"name": "Набор"})
    report = build_risk_report([_param("срок", "12", "месяцев")], None)
    assert calls == []
    assert report["sources"]["internet_search"] is False
    assert report["sources"]["status"] == NO_SPEC


def test_flag_on_without_allowlist_does_not_call_transport(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(FLAG, "1")
    calls = []

    def transport(url, timeout):
        calls.append(url)
        return {}

    with pytest.raises(CharacteristicConfigError):
        build_live_lookup(tmp_path / "missing.csv", transport)
    assert calls == []


def test_off_allowlist_redirect_is_not_opened(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(FLAG, "1")
    path = tmp_path / "allow.csv"
    path.write_text(
        "host,source_class\nmaker.example,официальный сайт производителя\n",
        encoding="utf-8",
    )
    calls = []

    def transport(url, timeout):
        calls.append(url)
        return {
            "status": 302,
            "url": url,
            "location": "https://evil.example/item",
            "text": "срок | 1 | шт",
        }

    lookup = build_live_lookup(path, transport, clock=lambda: 0)
    found = lookup.lookup({"name": "Набор"})
    assert calls == ["https://maker.example/?name=%D0%9D%D0%B0%D0%B1%D0%BE%D1%80"]
    assert found["pages"] == []
    assert "evil.example" not in "".join(calls)


def test_timeout_keeps_only_pages_already_fetched(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(FLAG, "1")
    calls = []
    ticks = iter([0, 0, 30])

    def transport(url, timeout):
        calls.append(url)
        return {
            "status": 200,
            "url": url,
            "location": "",
            "text": "срок | 12 | месяцев",
            "checked_at": "02.11.2026",
        }

    client = AllowlistClient(
        load_allowlist(_allow_file(tmp_path / "allow.csv")),
        transport,
        total_timeout=5,
        clock=lambda: next(ticks),
    )
    report = build_risk_report(
        [_param("срок", "12", "месяцев")],
        None,
        lookup=client,
        query={"name": "Набор"},
        allowlist=load_allowlist(tmp_path / "allow.csv"),
    )
    assert calls == ["https://maker.example/?name=%D0%9D%D0%B0%D0%B1%D0%BE%D1%80"]
    assert report["sources"]["status"] == SEARCH_INCOMPLETE
    assert report["percent"] is None
    assert report["risks"][0]["status"] == UNCHECKED
    assert [item["url"] for item in report["sources"]["resources"]] == [
        "https://maker.example/?name=%D0%9D%D0%B0%D0%B1%D0%BE%D1%80"
    ]
    assert report["candidates"][0]["value"] == "12"
    assert "catalog.example" not in "".join(calls)


def test_accepting_one_row_does_not_invent_the_other():
    requirements = [_param("срок", "12", "месяцев"), _param("объем", "10", "мл")]
    report = build_risk_report(
        requirements,
        None,
        accepted=[{"name": "срок", "value": "12", "unit": "месяцев", "from_table": True}],
    )
    assert report["percent"] == 50
    assert report["specification"]["confidence"] == "низкая"
    missing = next(row for row in report["specification"]["rows"] if row["name"] == "объем")
    assert "отсутствует" in missing["text"]
    assert report["risks"][0]["probability"] == "высокая"
