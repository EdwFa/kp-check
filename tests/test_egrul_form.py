import json

import pytest

from kp_tz_check.egrul_form import (
    AMBIGUOUS,
    CAPTCHA,
    DATE_MISSING,
    INCOMPLETE,
    NONE_FOUND,
    NO_CARD,
    ORIGIN,
    QUERY_EMPTY,
    TERMINATION_ABSENT,
    fetch_card,
    fetch_extract,
    http_transport,
)
from kp_tz_check.registries import build_registry
from kp_tz_check.supplier_checks import check_suppliers

TOKEN = "searchtoken"
ROW_TOKEN = "extracttoken"


def _response(payload: dict, *, location: str = "") -> dict:
    return {"status": 200, "url": ORIGIN, "location": location, "body": json.dumps(payload).encode()}


def _row(**extra) -> dict:
    row = {
        "n": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ ПОСТАВЩИК",
        "c": "ООО ПОСТАВЩИК",
        "i": "7701234567",
        "p": "770101001",
        "o": "1027700132195",
        "g": "Генеральный директор: Иванов Иван Иванович",
        "r": "01.02.2002",
        "k": "ul",
        "t": ROW_TOKEN,
        "cnt": "1",
    }
    row.update(extra)
    return row


def test_transport_refuses_another_host():
    with pytest.raises(ValueError):
        http_transport("GET", "https://evil.example/item", None, 1.0)


def test_flag_off_does_not_call_transport(monkeypatch):
    monkeypatch.delenv("KP_REGISTRY_EGRUL", raising=False)

    def transport(*_args):
        raise AssertionError("transport")

    registry = build_registry(egrul_transport=transport)
    found = registry.lookup("liquidation", "7701234567")
    assert found["status"] == "not_checked"
    assert found["source_url"] is None


def test_name_is_not_sent():
    calls = []

    def transport(*_args):
        calls.append(_args)
        return _response({})

    card = fetch_card("ООО Поставщик", transport, calls=calls)
    assert calls == []
    assert card["status"] == QUERY_EMPTY
    assert card["source_url"] is None


def test_captcha_stops_before_the_card():
    calls = []

    def transport(method, url, body, timeout):
        calls.append(url)
        return _response({"captchaRequired": True})

    card = fetch_card("7701234567", transport)
    assert calls == [ORIGIN]
    assert card["status"] == CAPTCHA
    assert card["row"] is None


def test_redirect_is_not_followed():
    calls = []

    def transport(method, url, body, timeout):
        calls.append(url)
        return {"status": 302, "url": url, "location": "https://evil.example/item", "body": b""}

    card = fetch_card("7701234567", transport)
    assert calls == [ORIGIN]
    assert card["status"] == NO_CARD


def test_one_row_maps_the_form_fields():
    calls = []

    def transport(method, url, body, timeout):
        calls.append(url)
        if method == "POST":
            return _response({"t": TOKEN, "captchaRequired": False})
        return _response({"rows": [_row()]})

    card = fetch_card("7701234567", transport)
    assert calls == [ORIGIN, f"{ORIGIN}search-result/{TOKEN}"]
    assert card["status"] == "checked"
    assert card["checked_at"] == DATE_MISSING
    assert card["row"]["name"].startswith("ОБЩЕСТВО")
    assert card["row"]["inn"] == "7701234567"
    assert card["row"]["ogrn"] == "1027700132195"
    assert card["row"]["director"].startswith("Генеральный директор")
    assert card["row"]["extract_token"] == ROW_TOKEN


def test_two_rows_are_not_collapsed():
    def transport(method, url, body, timeout):
        if method == "POST":
            return _response({"t": TOKEN})
        return _response({"rows": [_row(), _row(n="ДРУГОЕ ОБЩЕСТВО", t="ABCDE12345FGHI67")]})

    card = fetch_card("7701234567", transport)
    assert card["status"] == AMBIGUOUS
    assert card["row"] is None
    assert card["rows"] == 2


def test_empty_result_is_not_a_company():
    def transport(method, url, body, timeout):
        if method == "POST":
            return _response({"t": TOKEN})
        return _response({"rows": [{"cnt": "0", "t": TOKEN}]})

    card = fetch_card("7701234567", transport)
    assert card["status"] == NONE_FOUND


def test_wait_does_not_invent_a_row():
    calls = []

    def transport(method, url, body, timeout):
        calls.append(url)
        if method == "POST":
            return _response({"t": TOKEN})
        return _response({"status": "wait"})

    card = fetch_card("7701234567", transport, polls=2, sleep=lambda _seconds: None)
    assert card["status"] == INCOMPLETE
    assert card["row"] is None
    assert calls.count(f"{ORIGIN}search-result/{TOKEN}") == 2


def test_extract_captcha_does_not_download():
    calls = []

    def transport(method, url, body, timeout):
        calls.append(url)
        return _response({"captchaRequired": True})

    statement = fetch_extract(ROW_TOKEN, transport)
    assert calls == [f"{ORIGIN}vyp-request/{ROW_TOKEN}"]
    assert statement["status"] == CAPTCHA
    assert statement["pdf"] is None


def test_extract_pdf_comes_only_after_ready():
    calls = []

    def transport(method, url, body, timeout):
        calls.append(url)
        if url.endswith(f"vyp-request/{ROW_TOKEN}"):
            return _response({"captchaRequired": False})
        if url.endswith(f"vyp-status/{ROW_TOKEN}"):
            return _response({"status": "ready"})
        return {"status": 200, "url": url, "location": "", "body": b"%PDF-1.4 sample"}

    statement = fetch_extract(ROW_TOKEN, transport)
    assert calls[-1] == f"{ORIGIN}vyp-download/{ROW_TOKEN}"
    assert statement["status"] == "checked"
    assert statement["pdf"].startswith(b"%PDF")


def test_supplier_check_keeps_pair_status(monkeypatch):
    monkeypatch.setenv("KP_REGISTRY_EGRUL", "1")

    def transport(method, url, body, timeout):
        if method == "POST":
            return _response({"t": TOKEN, "captchaRequired": False})
        return _response({"rows": [_row()]})

    result = check_suppliers(
        [
            {
                "request": {"supplier": "ООО Поставщик"},
                "kp": {"supplier": "ООО Поставщик", "source_file": "offer.pdf"},
            }
        ],
        kps=[{"source_file": "offer.pdf", "body": "ИНН 7701234567 КПП 770101001 ОГРН 1027700132195"}],
        registry=build_registry(egrul_transport=transport),
    )[0]
    liquidation = next(row for row in result["criteria"] if row["criterion"] == "Ликвидация")
    koap = next(row for row in result["criteria"] if row["criterion"] == "КоАП 19.28")
    assert result["status"] == "PASS"
    assert result["card"] != "Все поставщики легитимны"
    assert liquidation["value"] == TERMINATION_ABSENT
    assert liquidation["source"] == ORIGIN
    assert koap["status"] == "not_checked"
    assert result["egrul"]["row"]["inn"] == "7701234567"
