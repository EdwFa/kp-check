"""Пакет заявки участника. Сеть не вызывается. У части 3 читается только текстовый слой PDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from kp_tz_check.dates import parse_date_string


SCHEMA_ENV = "KP_EGRUL_SCHEMA"
SCHEMA_MISSING = "схема XML не настроена"
PDF_NEEDS_TEXT = "нужна текстовая выписка или XML"
HEADER_MISMATCH = "Требует ручной проверки"
PART_OK = "Корректно"
PART_CRITICAL = "Критическая ошибка"
PART_REVIEW = "Требует уточнения"
PART_STATUSES = {PART_OK, PART_CRITICAL, PART_REVIEW}

_HEADER = re.compile(r"наименование\s*[:\-]\s*(.+)", re.IGNORECASE)
_SIGNER = re.compile(r"подписант\s*[:\-]\s*(.+)", re.IGNORECASE)
_SUBMITTED = re.compile(r"дата\s+подачи\s*[:\-]\s*([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4})", re.IGNORECASE)
_POWER = re.compile(r"доверенност\w*(?:\s+до)?\s*[:\-]?\s*([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4})", re.IGNORECASE)
_TEXT_EXTS = {".txt", ".docx", ".doc", ".docm", ".dotx"}


@dataclass
class Statement:
    configured: bool
    name: str | None = None
    inn: str | None = None
    kpp: str | None = None
    ogrn: str | None = None
    director: str | None = None
    legal_status: str | None = None
    note: str = ""


@dataclass
class BidPart:
    files: list[str] = field(default_factory=list)
    status: str | None = None
    findings: list[str] = field(default_factory=list)
    statement: Statement | None = None
    header_name: str | None = None
    signer: str | None = None
    submitted_on: date | None = None
    power_until: date | None = None


@dataclass
class BidPackage:
    participant: str
    part1: BidPart
    part2: BidPart
    part3: BidPart


def load_bid_packages(root: Path, *, schema: dict[str, str] | None = None, load_schema: bool = True) -> list[BidPackage]:
    folder = Path(root) / "bids"
    if not folder.exists():
        return []
    if load_schema and schema is None:
        schema = load_egrul_schema()
    packages = []
    for participant in sorted(path for path in folder.iterdir() if path.is_dir()):
        part1 = _part1(participant / "part1", schema)
        packages.append(
            BidPackage(
                participant=participant.name,
                part1=part1,
                part2=_part2(participant / "part2"),
                part3=_part3(participant / "part3", part1.statement),
            )
        )
    return packages


def load_egrul_schema(path: Path | str | None = None) -> dict[str, str] | None:
    raw = path if path is not None else os.environ.get(SCHEMA_ENV)
    if not raw:
        return None
    payload = json.loads(Path(raw).read_text(encoding="utf-8"))
    return {key: str(value) for key, value in payload.items() if key != "note"}


def parse_statement_xml(text: str, schema: dict[str, str] | None) -> Statement:
    if not schema:
        return Statement(configured=False, note=SCHEMA_MISSING)
    values = _tag_values(text)
    wanted = {field_name: values.get(tag) for field_name, tag in schema.items()}
    return Statement(
        configured=True,
        name=wanted.get("name"),
        inn=wanted.get("inn"),
        kpp=wanted.get("kpp"),
        ogrn=wanted.get("ogrn"),
        director=wanted.get("director"),
        legal_status=wanted.get("status"),
        note="",
    )


def _part1(folder: Path, schema: dict[str, str] | None) -> BidPart:
    files = _files(folder)
    part = BidPart(files=files)
    xml_files = [path for path in _paths(folder) if path.suffix.lower() == ".xml"]
    pdf_files = [path for path in _paths(folder) if path.suffix.lower() == ".pdf"]
    text = "\n".join(_read_text(path) for path in _paths(folder) if path.suffix.lower() in _TEXT_EXTS)
    header = _header(text)
    part.header_name = header["name"]
    part.signer = header["signer"]
    part.submitted_on = header["submitted_on"]
    part.power_until = header["power_until"]
    findings: list[tuple[str, str]] = []
    if xml_files:
        statement = parse_statement_xml(xml_files[0].read_text(encoding="utf-8"), schema)
        part.statement = statement
        if not statement.configured:
            findings.append(("review", SCHEMA_MISSING))
        else:
            findings.extend(_statement_findings(part, statement))
    elif pdf_files or not text.strip():
        findings.append(("review", PDF_NEEDS_TEXT))
    else:
        findings.append(("review", PDF_NEEDS_TEXT))
    if not files:
        findings = [("review", "Файлы части 1 не загружены.")]
    part.findings = [text for _, text in findings]
    part.status = PART_CRITICAL if any(level == "critical" for level, _ in findings) else (
        PART_REVIEW if findings else PART_OK
    )
    return part


def _part2(folder: Path) -> BidPart:
    from kp_tz_check.bids_part2 import check_part2

    files = _files(folder)
    text = "\n".join(
        _read_text(path)
        for path in _paths(folder)
        if path.suffix.lower() in _TEXT_EXTS
    )
    report = check_part2(text)
    return BidPart(files=files, status=report["status"], findings=report["findings"])


def _part3(folder: Path, statement: Statement | None) -> BidPart:
    from kp_tz_check.bids_part3 import check_part3

    files = _files(folder)
    if not files:
        return BidPart(files=files, status=PART_REVIEW, findings=["Файлы части 3 не загружены."])
    chunks = []
    saw_pdf = False
    for path in _paths(folder):
        suffix = path.suffix.lower()
        if suffix in _TEXT_EXTS:
            chunks.append(_read_text(path))
        elif suffix == ".pdf":
            saw_pdf = True
            chunks.append(_pdf_layer(path))
    text = "\n".join(chunk for chunk in chunks if chunk and chunk.strip())
    report = check_part3(
        text,
        statement=_statement_payload(statement),
        pdf_empty=saw_pdf and not text.strip(),
        load_vat=True,
    )
    findings = [f"{row['status']}: {row['text']}" for row in report["protocol"]]
    return BidPart(files=files, status=report["verdict"], findings=findings)


def _statement_findings(part: BidPart, statement: Statement) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    legal = (statement.legal_status or "").casefold()
    if any(token in legal for token in ("ликвидац", "исключен", "банкрот")):
        findings.append(("critical", f"{PART_CRITICAL}: статус выписки «{statement.legal_status}»."))
    if statement.name and part.header_name and _fold(statement.name) != _fold(part.header_name):
        findings.append(("review", f"{HEADER_MISMATCH}: наименование в шапке не совпадает с выпиской."))
    if statement.director and part.signer and _fold(statement.director) != _fold(part.signer):
        if part.power_until is None:
            findings.append(("review", "Несовпадение подписанта без доверенности: требует уточнения."))
        elif part.submitted_on is None:
            findings.append(("review", "Дата подачи не указана: требует уточнения."))
        elif part.submitted_on > part.power_until:
            findings.append(("critical", f"{PART_CRITICAL}: доверенность просрочена."))
    elif part.signer and statement.director is None:
        findings.append(("review", "ФИО руководителя не прочитано: требует уточнения."))
    return findings


def _header(text: str) -> dict:
    name = _first(_HEADER, text)
    signer = _first(_SIGNER, text)
    submitted = _first(_SUBMITTED, text)
    power = _first(_POWER, text)
    return {
        "name": name,
        "signer": signer,
        "submitted_on": parse_date_string(submitted) if submitted else None,
        "power_until": parse_date_string(power) if power else None,
    }


def _tag_values(text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    values: dict[str, str] = {}
    for node in root.iter():
        local = node.tag.rsplit("}", 1)[-1]
        if node.text and node.text.strip() and local not in values:
            values[local] = node.text.strip()
    return values


def _files(folder: Path) -> list[str]:
    return [path.name for path in _paths(folder)]


def _paths(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        (path for path in folder.iterdir() if path.is_file() and not path.name.startswith(".")),
        key=lambda path: path.name.lower(),
    )


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8")
    from kp_tz_check.extract import extract_document

    return extract_document(path).text


def _pdf_layer(path: Path) -> str:
    try:
        from kp_tz_check.extract import extract_document

        return extract_document(path).text or ""
    except Exception:
        return ""


def _statement_payload(statement: Statement | None) -> dict | None:
    if statement is None:
        return None
    return {
        "name": statement.name,
        "inn": statement.inn,
        "kpp": statement.kpp,
        "ogrn": statement.ogrn,
        "director": statement.director,
    }


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text or "")
    return match.group(1).strip() if match else None


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", value).casefold().strip()
