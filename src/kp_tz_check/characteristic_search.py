"""Поиск характеристик по фиктивному клиенту. Обычный прогон сеть не вызывает."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlencode, urlparse


FLAG = "KP_CHARACTERISTIC_SEARCH"
DATE_MISSING = "дата не указана"
QUERY_FIELDS = ("name", "manufacturer", "article", "registration")
CONFIRMED = "кандидат подтверждён источниками"
FEW_SOURCES = "недостаточно источников"
EXTRACTED_NONE = "источники проверены, характеристики не извлечены"
PENDING = "требует уточнения"
QUERY_EMPTY = "недостаточно данных"
SEARCH_INCOMPLETE = "поиск не завершён"
OFFICIAL = "официальный сайт производителя"
REGISTRY = "государственный реестр"
THIRD_PARTY = "сторонний ресурс"
ALLOWED_CLASSES = {OFFICIAL, REGISTRY, THIRD_PARTY}
REGISTRY_NOTE = "Найденная карточка не подтверждает допуск товара."


class CharacteristicConfigError(RuntimeError):
    """Флаг поиска включён, а клиента нет."""


class CharacteristicLookup(Protocol):
    def lookup(self, query: dict) -> dict:
        """Вернуть internet_search и pages. Сеть здесь не открывается."""


class DisabledLookup:
    def lookup(self, query: dict) -> dict:
        return {
            "status": "not_checked",
            "internet_search": False,
            "pages": [],
            "query": query,
        }


class FixtureLookup:
    """Страницы задаёт тест или локальный файл. Исходящих вызовов нет."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = list(pages)
        self.calls: list[dict] = []

    def lookup(self, query: dict) -> dict:
        self.calls.append(dict(query))
        return {
            "status": "checked",
            "internet_search": True,
            "pages": self.pages,
            "query": query,
        }


class AllowlistClient:
    """Запрос только к хостам списка. Транспорт подставляет тест."""

    def __init__(
        self,
        allowlist: list[dict],
        transport: Callable[[str, float], dict],
        *,
        host_timeout: float = 5.0,
        total_timeout: float = 20.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.allowlist = list(allowlist)
        self.transport = transport
        self.host_timeout = host_timeout
        self.total_timeout = total_timeout
        self.clock = clock or _monotonic
        self.hosts = {_bare_host(str(row.get("host") or "")) for row in self.allowlist}
        self.hosts.discard("")
        self.calls: list[str] = []

    def lookup(self, query: dict) -> dict:
        pages = []
        started = self.clock()
        incomplete = False
        for row in self.allowlist:
            if self.clock() - started > self.total_timeout:
                incomplete = True
                break
            host = _bare_host(str(row.get("host") or ""))
            if host not in self.hosts:
                continue
            url = _host_url(host, query)
            page = self._read(url)
            if page is None:
                incomplete = True
                break
            if page:
                pages.append(page)
        return {
            "status": SEARCH_INCOMPLETE if incomplete else "checked",
            "internet_search": True,
            "pages": pages,
            "query": query,
        }

    def _read(self, url: str) -> dict | None:
        if not self._allowed(url):
            return {}
        try:
            response = self._open(url)
        except TimeoutError:
            return None
        location = str(response.get("location") or "").strip()
        if location:
            if not self._allowed(location):
                return {}
            try:
                response = self._open(location)
            except TimeoutError:
                return None
            if str(response.get("location") or "").strip():
                return {}
        final = str(response.get("url") or url).strip()
        if not self._allowed(final):
            return {}
        return {
            "url": final,
            "text": str(response.get("text") or ""),
            "checked_at": str(response.get("checked_at") or ""),
        }

    def _open(self, url: str) -> dict:
        self.calls.append(url)
        return self.transport(url, self.host_timeout)

    def _allowed(self, url: str) -> bool:
        return _host_from_url(url) in self.hosts


def build_live_lookup(
    allowlist_path: Path | str | None,
    transport: Callable[[str, float], dict],
    *,
    host_timeout: float = 5.0,
    total_timeout: float = 20.0,
    clock: Callable[[], float] | None = None,
) -> CharacteristicLookup:
    if not search_enabled():
        return DisabledLookup()
    path = Path(allowlist_path) if allowlist_path else None
    if path is None or not path.is_file():
        raise CharacteristicConfigError("Включён поиск характеристик без списка хостов.")
    return AllowlistClient(
        load_allowlist(path),
        transport,
        host_timeout=host_timeout,
        total_timeout=total_timeout,
        clock=clock,
    )


def http_transport(url: str, timeout: float) -> dict:
    """Один ответ без перехода по редиректу. Тесты эту функцию не вызывают."""
    import urllib.error
    import urllib.request

    class _StopRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(_StopRedirect)
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            text = response.read(200_000).decode("utf-8", errors="replace")
            return {
                "status": getattr(response, "status", 200),
                "url": response.geturl(),
                "location": "",
                "text": text,
                "checked_at": "",
            }
    except urllib.error.HTTPError as exc:
        location = ""
        if exc.code in {301, 302, 303, 307, 308}:
            location = exc.headers.get("Location") or ""
        if not location:
            raise
        return {
            "status": exc.code,
            "url": url,
            "location": location,
            "text": "",
            "checked_at": "",
        }


def _monotonic() -> float:
    import time

    return time.monotonic()


def _host_url(host: str, query: dict) -> str:
    params = {key: value for key, value in query.items() if str(value or "").strip()}
    tail = urlencode(params)
    return f"https://{host}/" + (f"?{tail}" if tail else "")


def search_enabled() -> bool:
    return (os.environ.get(FLAG) or "").strip().lower() in {"1", "true", "yes", "on"}


def build_characteristic_lookup(client: CharacteristicLookup | None = None) -> CharacteristicLookup:
    if search_enabled() and client is None:
        raise CharacteristicConfigError("Включён поиск характеристик без клиента.")
    if client is None or not search_enabled():
        return DisabledLookup()
    return client


def build_characteristic_query(source: dict | None) -> dict:
    raw = source or {}
    query = {key: str(raw.get(key) or "").strip() for key in QUERY_FIELDS}
    return {"query": query, "ready": any(query.values())}


def load_allowlist(path: Path | str) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            rows.append(
                {
                    "host": str(row.get("host") or "").strip(),
                    "source_class": str(row.get("source_class") or "").strip(),
                }
            )
    return rows


def load_fixture_pages(path: Path | str) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload.get("pages") or [])


def describe_pages(pages: list[dict] | None, allowlist: list[dict] | None) -> dict:
    classes = _classes(allowlist or [])
    resources = []
    observations = []
    for page in pages or []:
        url = str(page.get("url") or "").strip()
        host = _host_from_url(url)
        source_class = classes.get(host)
        if not url or source_class is None:
            continue
        text = str(page.get("text") or "")
        checked_at = str(page.get("checked_at") or "").strip() or DATE_MISSING
        resources.append(
            {
                "url": url,
                "host": host,
                "source_class": source_class,
                "checked_at": checked_at,
                "page_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        for row in _extract_rows(text):
            observations.append({**row, "host": host, "url": url})
    if not observations:
        return {
            "status": EXTRACTED_NONE,
            "resources": resources,
            "candidates": [],
            "internet_search": True,
        }
    return {
        "status": PENDING,
        "resources": resources,
        "candidates": _vote(observations),
        "internet_search": True,
    }


def _classes(allowlist: list[dict]) -> dict[str, str]:
    classes = {}
    for row in allowlist:
        host = _bare_host(str(row.get("host") or ""))
        source_class = str(row.get("source_class") or "").strip()
        if host and source_class in ALLOWED_CLASSES:
            classes[host] = source_class
    return classes


def _extract_rows(text: str) -> list[dict]:
    rows = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "|" in line:
            parts = [part.strip() for part in line.split("|")]
            if not parts[0]:
                continue
            rows.append(
                {
                    "name": parts[0],
                    "value": parts[1] if len(parts) > 1 else "",
                    "unit": parts[2] if len(parts) > 2 else "",
                }
            )
            continue
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            rows.append({"name": name, "value": value, "unit": ""})
    return rows


def _vote(observations: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for item in observations:
        groups.setdefault(_norm(item["name"]), []).append(item)
    candidates = []
    for items in groups.values():
        by_host: dict[str, list[dict]] = {}
        for item in items:
            by_host.setdefault(item["host"], []).append(item)
        votes: dict[tuple[str, str], set[str]] = {}
        urls: dict[tuple[str, str], list[str]] = {}
        originals: dict[tuple[str, str], dict] = {}
        for host, host_items in by_host.items():
            signatures = {(_norm(row["value"]), _norm(row["unit"])) for row in host_items}
            if len(signatures) != 1:
                continue
            signature = signatures.pop()
            votes.setdefault(signature, set()).add(host)
            urls.setdefault(signature, []).extend(row["url"] for row in host_items)
            originals.setdefault(signature, host_items[0])
        if not votes:
            signature = (_norm(items[0]["value"]), _norm(items[0]["unit"]))
            chosen = items[0]
            note = FEW_SOURCES
            chosen_urls = [row["url"] for row in items]
        else:
            signature = max(votes, key=lambda item: (len(votes[item]), item))
            chosen = originals[signature]
            note = CONFIRMED if len(votes[signature]) >= 3 else FEW_SOURCES
            chosen_urls = urls[signature]
        candidates.append(
            {
                "name": chosen["name"],
                "value": chosen["value"],
                "unit": chosen["unit"],
                "from_table": False,
                "required": True,
                "note": note,
                "urls": chosen_urls,
            }
        )
    return candidates


def _host_from_url(url: str) -> str:
    return _bare_host(urlparse(url).hostname or "")


def _bare_host(host: str) -> str:
    host = host.strip().casefold()
    if host.startswith("www."):
        host = host[4:]
    return host


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).casefold().strip()
