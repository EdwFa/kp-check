"""Structure-агент: парсер — база, LLM предлагает, regex/dates.py подтверждают.

Неподтверждённую дату модель подставить не может.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from kp_tz_check.dates import date_from_filename, find_dates, parse_date_string
from kp_tz_check.extract import ExtractedDoc, extract_document
from kp_tz_check.models import Item, KpRecord, RequestRecord, TzRecord
from kp_tz_check.parse import (
    EMAIL_RE,
    PREP_HINTS,
    _iter_docs,
    parse_kp,
    parse_requests,
    parse_tz,
)
from kp_tz_check.serde import from_jsonable, to_jsonable

REVIEW = "требует ручной проверки"
OUTGOING_NO_RE = re.compile(r"^\d{3,}$")
PREP_CONTEXT = PREP_HINTS + ("коммерческ", "предложен")

_proposer: ContextVar["StructureProposer | None"] = ContextVar("structure_proposer", default=None)


class StructureProposer(Protocol):
    def propose_requests(
        self, *, text: str, tables: list, baseline: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def propose_kp(
        self, *, text: str, filename: str, tables: list, baseline: dict[str, Any]
    ) -> dict[str, Any]: ...

    def propose_tz(
        self, *, text: str, tables: list, baseline: dict[str, Any]
    ) -> dict[str, Any]: ...


def get_proposer() -> StructureProposer | None:
    return _proposer.get()


def set_proposer(proposer: StructureProposer | None):
    return _proposer.set(proposer)


def reset_proposer(token) -> None:
    _proposer.reset(token)


def source_blob(extracted: ExtractedDoc) -> str:
    return f"{extracted.path.name}\n{extracted.text}"


def date_in_source(raw: str | None, parsed: date, source: str) -> bool:
    text = (source or "").replace("\u00a0", " ")
    lowered = text.lower()
    candidates = [
        (raw or "").strip(),
        parsed.strftime("%d.%m.%Y"),
        parsed.strftime("%d.%m.%y"),
        parsed.isoformat(),
    ]
    for item in candidates:
        if item and item.lower() in lowered:
            return True
    return any(value == parsed for value, _, _ in find_dates(text))


def confirm_date(
    raw: str | None,
    source: str,
    *,
    context_hints: tuple[str, ...] | None = None,
) -> tuple[date | None, str | None, str | None]:
    if not raw or not str(raw).strip():
        return None, None, None
    proposed = str(raw).strip()
    parsed = parse_date_string(proposed)
    if parsed is None:
        return None, None, f"дата «{proposed}» не разобрана dates.py, {REVIEW}"
    if not date_in_source(proposed, parsed, source):
        return None, None, f"дата «{proposed}» не найдена в документе, не подставлена"
    if context_hints:
        idx = _span_index(source, proposed, parsed)
        if idx is None:
            return None, None, f"дата «{proposed}» без якоря в тексте, {REVIEW}"
        window = source.lower()[max(0, idx - 80) : idx + 80]
        if not any(hint in window for hint in context_hints):
            return None, None, f"дата «{proposed}» есть в тексте, но не в контексте подготовки, не подставлена"
    return parsed, proposed, None


def confirm_outgoing_no(value: str | None, source: str) -> str | None:
    number = (value or "").strip()
    if not OUTGOING_NO_RE.fullmatch(number):
        return None
    return number if number in source else None


def confirm_email(value: str | None, source: str) -> str | None:
    if not value:
        return None
    match = EMAIL_RE.search(value)
    if not match:
        return None
    email = match.group(0)
    return email if email.lower() in source.lower() else None


def confirm_supplier(value: str | None, source: str) -> str | None:
    name = re.sub(r"[«»\"']", "", value or "").strip()
    if len(name) < 3:
        return None
    core = re.sub(r"^(ооо|зао|оао|ао|пао|ип)\s+", "", name.lower().replace("ё", "е")).strip()
    haystack = source.lower().replace("ё", "е")
    if core and core in haystack:
        return name
    return None


def confirm_item(payload: dict[str, Any], source: str) -> Item | None:
    item = from_jsonable(Item, {**{"no": "", "name": "", "specs": "", "unit": "", "qty": ""}, **payload})
    if not re.search(r"\d", item.qty or ""):
        return None
    needle = (item.name or item.specs or "").strip()
    if len(needle) < 4:
        return None
    if needle.lower() not in source.lower() and not any(
        token in source.lower() for token in needle.lower().split() if len(token) > 5
    ):
        return None
    return item


def structure_requests(
    extracted: ExtractedDoc, proposer: StructureProposer | None = None
) -> list[RequestRecord]:
    baseline = parse_requests(extracted)
    proposer = _resolve(proposer)
    if proposer is None:
        return baseline
    proposal = _safe_propose(
        lambda: proposer.propose_requests(
            text=extracted.text, tables=extracted.tables, baseline=to_jsonable(baseline)
        ),
        baseline,
    )
    if not isinstance(proposal, list):
        return baseline
    return merge_requests(extracted, baseline, proposal)


def structure_kp(extracted: ExtractedDoc, proposer: StructureProposer | None = None) -> KpRecord:
    baseline = parse_kp(extracted)
    proposer = _resolve(proposer)
    if proposer is None:
        return baseline
    proposal = _safe_propose(
        lambda: proposer.propose_kp(
            text=extracted.text,
            filename=extracted.path.name,
            tables=extracted.tables,
            baseline=to_jsonable(baseline),
        ),
        baseline,
    )
    if not isinstance(proposal, dict):
        return baseline
    return merge_kp(extracted, baseline, proposal)


def structure_tz(extracted: ExtractedDoc, proposer: StructureProposer | None = None) -> TzRecord:
    baseline = parse_tz(extracted)
    proposer = _resolve(proposer)
    if proposer is None:
        return baseline
    proposal = _safe_propose(
        lambda: proposer.propose_tz(
            text=extracted.text, tables=extracted.tables, baseline=to_jsonable(baseline)
        ),
        baseline,
    )
    if not isinstance(proposal, dict):
        return baseline
    return merge_tz(extracted, baseline, proposal)


def structure_incoming(
    root: Path, proposer: StructureProposer | None = None
) -> tuple[list[RequestRecord], list[KpRecord], list[TzRecord]]:
    proposer = _resolve(proposer)
    requests: list[RequestRecord] = []
    for path in _iter_docs(root / "requests"):
        requests.extend(structure_requests(extract_document(path), proposer))
    kps = [structure_kp(extract_document(path), proposer) for path in _iter_docs(root / "kp")]
    tzs = [structure_tz(extract_document(path), proposer) for path in _iter_docs(root / "tz")]
    return requests, kps, tzs


def merge_requests(
    extracted: ExtractedDoc,
    baseline: list[RequestRecord],
    proposal: list[dict[str, Any]],
) -> list[RequestRecord]:
    source = source_blob(extracted)
    confirmed: list[RequestRecord] = []
    for raw in proposal:
        letter = _confirm_letter(extracted, source, raw)
        if letter is not None:
            confirmed.append(letter)

    if _unstructured(baseline) and confirmed:
        dummy = baseline[0]
        notes = list(dummy.notes)
        notes.append("Structure-агент: исходящие письма подтверждены regex по тексту")
        merged = []
        for item in confirmed:
            merged.append(
                replace(
                    item,
                    body=dummy.body,
                    items=dummy.items,
                    sent_on=item.sent_on or dummy.sent_on,
                    sent_on_raw=item.sent_on_raw or dummy.sent_on_raw,
                    supplier=item.supplier or dummy.supplier,
                    email=item.email or dummy.email,
                    notes=_unique(list(item.notes) + notes),
                )
            )
        return merged

    by_no = {item.outgoing_no: item for item in baseline if item.outgoing_no}
    extra_notes: list[str] = []
    for letter in confirmed:
        existing = by_no.get(letter.outgoing_no) if letter.outgoing_no else None
        if existing is None:
            extra_notes.append(
                f"Structure-агент предложил исх. №{letter.outgoing_no}, но парсер его не видел — "
                f"добавлен после подтверждения в тексте"
            )
            baseline.append(letter)
            if letter.outgoing_no:
                by_no[letter.outgoing_no] = letter
            continue
        filled = _fill_request_gaps(existing, letter)
        idx = baseline.index(existing)
        baseline[idx] = filled
        by_no[filled.outgoing_no] = filled
    if extra_notes and baseline:
        baseline[0] = replace(baseline[0], notes=list(baseline[0].notes) + extra_notes)
    return baseline


def merge_kp(extracted: ExtractedDoc, baseline: KpRecord, proposal: dict[str, Any]) -> KpRecord:
    source = source_blob(extracted)
    notes = list(baseline.notes)
    prepared, prepared_raw = baseline.prepared_on, baseline.prepared_on_raw
    if prepared is None:
        parsed, raw, reason = confirm_date(
            proposal.get("prepared_on_raw") or proposal.get("prepared_on"),
            source,
            context_hints=PREP_CONTEXT,
        )
        if parsed:
            prepared, prepared_raw = parsed, raw
            notes.append("Structure-агент: дата подготовки подтверждена dates.py по тексту")
        elif reason:
            notes.append(reason)

    registered, registered_raw = date_from_filename(extracted.path.name)
    proposed_reg = proposal.get("registered_on_raw") or proposal.get("registered_on")
    if proposed_reg:
        parsed_reg = parse_date_string(str(proposed_reg))
        file_date, _ = date_from_filename(extracted.path.name)
        if parsed_reg is not None and file_date is not None and parsed_reg != file_date:
            notes.append(
                f"Structure-агент предложил дату регистрации {proposed_reg}, "
                f"она не совпадает с именем файла — оставлена дата из файла"
            )
    if registered is None:
        notes.append("Дата регистрации КП в названии файла не прочитана, требует ручной проверки")

    supplier = baseline.supplier or confirm_supplier(proposal.get("supplier"), source)
    outgoing = baseline.outgoing_no or confirm_outgoing_no(proposal.get("outgoing_no"), source)
    items = list(baseline.items)
    if not items:
        items = [item for item in (confirm_item(row, source) for row in proposal.get("items") or []) if item]

    return replace(
        baseline,
        prepared_on=prepared,
        prepared_on_raw=prepared_raw,
        registered_on=registered,
        registered_on_raw=registered_raw or baseline.registered_on_raw,
        supplier=supplier,
        outgoing_no=outgoing,
        items=items,
        notes=_unique(notes),
    )


def merge_tz(extracted: ExtractedDoc, baseline: TzRecord, proposal: dict[str, Any]) -> TzRecord:
    if baseline.items:
        return baseline
    source = source_blob(extracted)
    items = [item for item in (confirm_item(row, source) for row in proposal.get("items") or []) if item]
    notes = list(baseline.notes)
    if items:
        notes.append("Structure-агент: позиции ТЗ подтверждены по тексту")
        notes = [item for item in notes if "Таблица позиций ТЗ не прочитана" not in item]
    return replace(baseline, items=items or baseline.items, notes=_unique(notes))


def _confirm_letter(extracted: ExtractedDoc, source: str, raw: dict[str, Any]) -> RequestRecord | None:
    outgoing = confirm_outgoing_no(raw.get("outgoing_no"), source)
    if outgoing is None:
        return None
    sent, sent_raw, reason = confirm_date(raw.get("sent_on_raw") or raw.get("sent_on"), source)
    if sent is not None and not _date_on_outgoing_line(source, sent, sent_raw, outgoing):
        reason = (
            f"дата «{raw.get('sent_on_raw') or raw.get('sent_on')}» не рядом с исх. №{outgoing}, "
            "не подставлена"
        )
        sent, sent_raw = None, None
    notes = [reason] if reason else []
    if sent is None:
        notes.append("Дата отправки запроса не прочитана, требует ручной проверки")
    return RequestRecord(
        source_file=extracted.path,
        outgoing_no=outgoing,
        sent_on=sent,
        sent_on_raw=sent_raw or raw.get("sent_on_raw"),
        supplier=confirm_supplier(raw.get("supplier"), source),
        email=confirm_email(raw.get("email"), source),
        notes=_unique(notes),
    )


def _fill_request_gaps(base: RequestRecord, proposal: RequestRecord) -> RequestRecord:
    notes = list(base.notes)
    sent, sent_raw = base.sent_on, base.sent_on_raw
    if sent is None and proposal.sent_on is not None:
        sent, sent_raw = proposal.sent_on, proposal.sent_on_raw
        notes.append("Structure-агент: дата отправки подтверждена dates.py по тексту")
        notes = [item for item in notes if "Дата отправки запроса не прочитана" not in item]
    return replace(
        base,
        sent_on=sent,
        sent_on_raw=sent_raw,
        supplier=base.supplier or proposal.supplier,
        email=base.email or proposal.email,
        notes=_unique(notes),
    )


def _unstructured(records: list[RequestRecord]) -> bool:
    return len(records) == 1 and records[0].outgoing_no is None


def _date_on_outgoing_line(source: str, parsed: date, raw: str | None, outgoing: str) -> bool:
    for line in source.splitlines():
        if outgoing not in line and not re.search(r"исх", line, re.I):
            continue
        if date_in_source(raw, parsed, line):
            return True
    return False


def _span_index(source: str, raw: str, parsed: date) -> int | None:
    text = source.replace("\u00a0", " ")
    for candidate in ((raw or "").strip(), parsed.strftime("%d.%m.%Y"), parsed.isoformat()):
        if not candidate:
            continue
        idx = text.lower().find(candidate.lower())
        if idx >= 0:
            return idx
    for value, _, start in find_dates(text):
        if value == parsed:
            return start
    return None


def _resolve(proposer: StructureProposer | None) -> StructureProposer | None:
    return proposer if proposer is not None else get_proposer()


def _safe_propose(fn, fallback):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        if isinstance(fallback, list):
            for item in fallback:
                item.notes.append(f"Structure-агент не ответил ({exc}), использован парсер")
        else:
            fallback.notes.append(f"Structure-агент не ответил ({exc}), использован парсер")
        return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = (value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result
