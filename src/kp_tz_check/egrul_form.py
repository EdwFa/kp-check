"""Открытая форма egrul.nalog.ru. Обычный прогон сеть не вызывает."""

from __future__ import annotations

import json
import os
import re
from typing import Callable
from urllib.parse import urlencode

FLAG = "KP_REGISTRY_EGRUL"
ORIGIN = "https://egrul.nalog.ru/"
DATE_MISSING = "дата в форме не указана"
QUERY_EMPTY = "нужен ИНН или ОГРН"
CAPTCHA = "форма запросила подтверждение"
NO_CARD = "форма не вернула карточку"
NONE_FOUND = "в форме сведений нет"
AMBIGUOUS = "требует уточнения"
INCOMPLETE = "поиск не завершён"
TERMINATION_ABSENT = "дата прекращения не указана"
INVALIDATION_ABSENT = "дата признания регистрации недействительной не указана"
EXTRACT_MISSING = "выписка не получена"
_TOKEN = re.compile(r"^[A-Za-z0-9]{8,160}$")
_QUERY = re.compile(r"^(?:\d{10}|\d{12}|\d{13}|\d{15})$")
_ANSWERED = {"liquidation", "unreliable"}


def egrul_enabled() -> bool:
    return (os.environ.get(FLAG) or "").strip().lower() in {"1", "true", "yes", "on"}


class EgrulRegistry:
    """Один запрос формы на ИНН или ОГРН. Остальные критерии остаются непроверенными."""

    def __init__(
        self,
        transport: Callable[[str, str, bytes | None, float], dict] | None = None,
        *,
        timeout: float = 20.0,
        polls: int = 5,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.transport = transport or http_transport
        self.timeout = timeout
        self.polls = polls
        self.sleep = sleep or _sleep
        self.calls: list[str] = []
        self._cards: dict[str, dict] = {}

    def lookup(self, kind: str, key: str) -> dict:
        if kind not in _ANSWERED:
            return _row(kind, key, "not_checked", None, None)
        card = self.card_for(key)
        if card.get("status") != "checked" or not card.get("row"):
            return _row(kind, key, "not_checked", card.get("status"), card.get("source_url"))
        found = card["row"]
        if kind == "liquidation":
            value = found.get("terminated") or TERMINATION_ABSENT
        else:
            value = found.get("invalidated") or INVALIDATION_ABSENT
        return _row(kind, key, "checked", value, ORIGIN)

    def card_for(self, key: str) -> dict:
        query = _digits(key)
        if query in self._cards:
            return self._cards[query]
        card = fetch_card(
            query,
            self.transport,
            timeout=self.timeout,
            polls=self.polls,
            sleep=self.sleep,
            calls=self.calls,
        )
        self._cards[query] = card
        return card


def fetch_card(
    query: str,
    transport: Callable[[str, str, bytes | None, float], dict],
    *,
    timeout: float = 20.0,
    polls: int = 5,
    sleep: Callable[[float], None] | None = None,
    calls: list[str] | None = None,
) -> dict:
    """Карточка с формы. Подтверждение формы не обходится."""
    pause = sleep or _sleep
    query = _digits(query)
    if not _QUERY.fullmatch(query):
        return _card(QUERY_EMPTY, query, None, source=None)
    try:
        opened = _open(transport, "POST", ORIGIN, _body(query), timeout, calls)
    except TimeoutError:
        return _card(INCOMPLETE, query, None)
    payload = _json(opened)
    if payload.get("captchaRequired") is True:
        return _card(CAPTCHA, query, None)
    token = str(payload.get("t") or "")
    if not _TOKEN.fullmatch(token):
        return _card(NO_CARD, query, None)
    result = _poll(transport, f"{ORIGIN}search-result/{token}", timeout, polls, pause, calls)
    if result.get("status") == "wait":
        return _card(INCOMPLETE, query, None)
    if result.get("captchaRequired") is True:
        return _card(CAPTCHA, query, None)
    rows = _companies(result.get("rows") or [])
    matched = [row for row in rows if _same(query, row)]
    if not matched:
        return _card(NONE_FOUND, query, None)
    if len(matched) > 1:
        return _card(AMBIGUOUS, query, None, rows=len(matched))
    return _card("checked", query, _fields(matched[0]), rows=1)


def fetch_extract(
    token: str,
    transport: Callable[[str, str, bytes | None, float], dict],
    *,
    timeout: float = 20.0,
    polls: int = 5,
    sleep: Callable[[float], None] | None = None,
    calls: list[str] | None = None,
) -> dict:
    """PDF-выписка с формы. Если форма просит подтверждение, файл не запрашивается."""
    pause = sleep or _sleep
    if not _TOKEN.fullmatch(token or ""):
        return {"status": NO_CARD, "pdf": None}
    try:
        opened = _open(transport, "GET", f"{ORIGIN}vyp-request/{token}", None, timeout, calls)
    except TimeoutError:
        return {"status": INCOMPLETE, "pdf": None}
    payload = _json(opened)
    if payload.get("captchaRequired") is True:
        return {"status": CAPTCHA, "pdf": None}
    result = _poll(transport, f"{ORIGIN}vyp-status/{token}", timeout, polls, pause, calls)
    if result.get("captchaRequired") is True:
        return {"status": CAPTCHA, "pdf": None}
    if result.get("status") != "ready":
        return {"status": INCOMPLETE if result.get("status") == "wait" else EXTRACT_MISSING, "pdf": None}
    try:
        downloaded = _open(transport, "GET", f"{ORIGIN}vyp-download/{token}", None, timeout, calls)
    except TimeoutError:
        return {"status": INCOMPLETE, "pdf": None}
    body = downloaded.get("body") or b""
    if not body.startswith(b"%PDF"):
        return {"status": EXTRACT_MISSING, "pdf": None}
    return {"status": "checked", "pdf": body}


def http_transport(method: str, url: str, body: bytes | None, timeout: float) -> dict:
    """Один ответ формы без перехода по редиректу. Тесты эту функцию не вызывают."""
    import ssl
    import urllib.error
    import urllib.request

    import certifi

    if not _allowed(url):
        raise ValueError(NO_CARD)

    class _StopRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(_StopRedirect, urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"User-Agent": "kp-tz-check", "Accept": "application/json, application/pdf"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return {
                "status": getattr(response, "status", 200),
                "url": response.geturl(),
                "location": "",
                "body": response.read(2_000_000),
            }
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") or "" if exc.code in {301, 302, 303, 307, 308} else ""
        return {"status": exc.code, "url": url, "location": location, "body": b""}
    except TimeoutError:
        raise
    except Exception as exc:
        if exc.__class__.__name__ == "URLError" and isinstance(getattr(exc, "reason", None), TimeoutError):
            raise TimeoutError from exc
        raise


def _open(transport, method: str, url: str, body: bytes | None, timeout: float, calls: list[str] | None) -> dict:
    if not _allowed(url):
        return {"status": 0, "url": url, "location": "", "body": b""}
    if calls is not None:
        calls.append(url)
    return transport(method, url, body, timeout)


def _poll(transport, url: str, timeout: float, polls: int, sleep: Callable[[float], None], calls: list[str] | None) -> dict:
    payload: dict = {"status": "wait"}
    for attempt in range(max(polls, 1)):
        if attempt:
            sleep(1.0)
        try:
            opened = _open(transport, "GET", url, None, timeout, calls)
        except TimeoutError:
            return {"status": "wait"}
        payload = _json(opened)
        if payload.get("status") != "wait":
            return payload
    return payload


def _companies(rows: list) -> list[dict]:
    found = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("cnt")) == "0":
            continue
        found.append(row)
    return found


def _fields(row: dict) -> dict:
    return {
        "name": row.get("n") or row.get("c") or "",
        "short_name": row.get("c") or "",
        "inn": row.get("i") or "",
        "kpp": row.get("p") or "",
        "ogrn": row.get("o") or "",
        "director": row.get("g") or "",
        "registered": row.get("r") or "",
        "terminated": row.get("e") or "",
        "invalidated": row.get("v") or "",
        "kind": row.get("k") or "",
        "extract_token": row.get("t") if _TOKEN.fullmatch(str(row.get("t") or "")) else "",
    }


def _same(query: str, row: dict) -> bool:
    if len(query) in {10, 12}:
        return str(row.get("i") or "") == query
    return str(row.get("o") or "") == query


def _body(query: str) -> bytes:
    return urlencode(
        {"query": query, "page": "", "region": "", "vyp3CaptchaToken": ""}
    ).encode()


def _json(opened: dict) -> dict:
    if opened.get("location"):
        return {}
    try:
        payload = json.loads(opened.get("body") or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _card(status: str, query: str, row: dict | None, *, rows: int = 0, source: str | None = ORIGIN) -> dict:
    return {
        "status": status,
        "query": query,
        "source_url": source,
        "checked_at": DATE_MISSING if source else None,
        "row": row,
        "rows": rows,
    }


def _row(kind: str, key: str, status: str, value, source: str | None) -> dict:
    return {
        "status": status,
        "value": value,
        "source_url": source,
        "checked_at": DATE_MISSING if status == "checked" else None,
        "kind": kind,
        "key": key,
    }


def _digits(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def _allowed(url: str) -> bool:
    return url == ORIGIN or url.startswith(ORIGIN)


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
