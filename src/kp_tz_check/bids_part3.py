"""Часть 3 заявки: цена, НДС, декларация, крупная сделка и реквизиты."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import re

from kp_tz_check.application_math import check_application
from kp_tz_check.registries import DisabledRegistry


NMCK_REJECT = "Критическая ошибка: отклонение заявки"
VAT_REVIEW = "требует ручной проверки"
NO_RATE_RULE = "нет правила ставки"
OCR_NEEDED = "нужен OCR"
ADMITTED = "Допущен к аукциону"
REJECTED = "Отклонен"
NEEDS_REVIEW = "Требует уточнения"
ARITHMETIC = "Арифметическая ошибка"
DEAL_EXPIRED = "Истек срок крупной сделки"
DEAL_LIMIT = "Превышен лимит крупной сделки"
DIRECTOR_MISMATCH = "Расхождение ФИО директора с ЕГРЮЛ"
VAT_ENV = "KP_VAT_RATES"
DECLARATION_POINTS = (
    ("ликвидац", "ликвидация"),
    ("банкрот", "банкротство"),
    ("недоимк", "недоимка"),
    ("судимост", "судимость"),
    ("конфликт", "конфликт интересов"),
    ("иностранн", "иностранный агент"),
    ("рнп", "РНП"),
)

_HEADINGS = ("анкета", "декларация", "приказ", "крупная сделка")
_LABELS = (
    ("фио директора", "director"),
    ("расчётный счёт", "account"),
    ("расчетный счет", "account"),
    ("корреспондентский счёт", "corr"),
    ("корреспондентский счет", "corr"),
    ("дата решения", "decision"),
    ("дата заявки", "submitted"),
    ("сумма заявки", "amount"),
    ("наименование", "name"),
    ("лимит", "limit"),
    ("срок", "until"),
    ("инн", "inn"),
    ("кпп", "kpp"),
    ("огрн", "ogrn"),
    ("фио", "director"),
    ("бик", "bik"),
)


def check_part3(
    text: str,
    *,
    nmck: float | None = None,
    statement: dict | None = None,
    registry=None,
    vat_table: list[dict[str, str]] | None = None,
    load_vat: bool = False,
    pdf_empty: bool = False,
) -> dict:
    registry = registry or DisabledRegistry()
    if load_vat and vat_table is None:
        vat_table = load_vat_table()
    blocks = _blocks(text or "")
    math = check_application(
        {
            "source_file": "часть 3",
            "body": text or "",
            "items": _math_items(text or ""),
        }
    )
    protocol: list[dict[str, str]] = []
    findings: list[str] = []
    extracted = {"decision_date": "", "until": "", "limit": "", "decision_fio": ""}
    readable = bool((text or "").strip()) and not pdf_empty
    if pdf_empty:
        findings.append(OCR_NEEDED)
        protocol.append({"status": NEEDS_REVIEW, "text": OCR_NEEDED})
    elif not (text or "").strip():
        findings.append("Текст части 3 не извлечён.")
        protocol.append({"status": NEEDS_REVIEW, "text": "Текст части 3 не извлечён."})
    if readable:
        _arithmetic(math, protocol, findings)
        _nmck(math, nmck, protocol, findings)
        _vat(text or "", vat_table, protocol, findings)
        extracted = _deal(blocks.get("крупная сделка") or "", protocol, findings)
        _declaration(blocks, protocol, findings)
        _requisites(blocks, statement or {}, extracted, protocol, findings)
        _bank(blocks, protocol, findings)
    registry_rows = _registries(registry, (statement or {}).get("inn") or "")
    critical = any(
        row["status"] in {ARITHMETIC, DEAL_EXPIRED, DEAL_LIMIT, DIRECTOR_MISMATCH, REJECTED}
        or NMCK_REJECT in row["text"]
        for row in protocol
    )
    registries_open = any(row["status"] == "not_checked" for row in registry_rows)
    if critical:
        verdict = REJECTED
    elif registries_open or pdf_empty or findings:
        verdict = NEEDS_REVIEW
    else:
        verdict = ADMITTED
    return {
        "verdict": verdict,
        "admitted": verdict == ADMITTED,
        "protocol": protocol,
        "findings": findings,
        "registry": registry_rows,
        "math": math,
        "extracted": extracted,
    }


def load_vat_table(path: Path | str | None = None) -> list[dict[str, str]] | None:
    raw = path if path is not None else os.environ.get(VAT_ENV)
    if not raw:
        return None
    with Path(raw).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _arithmetic(math: dict, protocol: list[dict], findings: list[str]) -> None:
    written = next((item["text"] for item in math["findings"] if item["code"] == "application-written"), None)
    substantive = math["status"] == "содержательная ошибка" or written
    if substantive:
        text = written or "Содержательная ошибка арифметики заявки."
        protocol.append({"status": ARITHMETIC, "text": text})
        findings.append(text)
    elif math.get("written_status") == "ок":
        protocol.append({"status": "Корректно", "text": "Сумма прописью совпадает с числовым итогом."})


def _nmck(math: dict, nmck: float | None, protocol: list[dict], findings: list[str]) -> None:
    total = math.get("declared_total")
    if total is None:
        total = math.get("forward_total")
    if total is None or nmck is None:
        return
    if float(total) > float(nmck):
        protocol.append({"status": REJECTED, "text": NMCK_REJECT})
        findings.append(NMCK_REJECT)


def _vat(text: str, table: list[dict[str, str]] | None, protocol: list[dict], findings: list[str]) -> None:
    for line in text.splitlines():
        if "окпд2" not in line.casefold() or "ндс" not in line.casefold():
            continue
        code = _field(line, "окпд2")
        rate = _field(line, "ндс")
        if not code or not rate:
            continue
        rule = _rate_rule(code, table)
        if rule is None:
            protocol.append({"status": NO_RATE_RULE, "text": f"{NO_RATE_RULE}: ОКПД2 {code}. Ставка {rate} не заменена."})
            continue
        allowed = {item.strip() for item in rule.replace("%", "").split(";") if item.strip()}
        actual = rate.replace("%", "").strip()
        if actual not in allowed:
            protocol.append(
                {
                    "status": VAT_REVIEW,
                    "text": f"{VAT_REVIEW}: ставка {actual}% при правиле {rule}. Ставка не заменена.",
                }
            )
            findings.append(VAT_REVIEW)


def _deal(text: str, protocol: list[dict], findings: list[str]) -> dict[str, str]:
    fields = _fields(text)
    extracted = {
        "decision_date": fields.get("decision") or "",
        "until": fields.get("until") or "",
        "limit": fields.get("limit") or "",
        "decision_fio": fields.get("director") or "",
    }
    if not text.strip():
        return extracted
    limit = _money(extracted["limit"])
    amount = _money(fields.get("amount") or "")
    until = extracted["until"]
    submitted = fields.get("submitted") or ""
    if limit is not None and amount is not None:
        if amount > limit:
            protocol.append({"status": DEAL_LIMIT, "text": f"{DEAL_LIMIT}: сумма {amount:g} больше лимита {limit:g}."})
            findings.append(DEAL_LIMIT)
        else:
            protocol.append({"status": "Корректно", "text": "Сумма заявки не превышает лимит крупной сделки."})
    if until and submitted and _iso(until) < _iso(submitted):
        protocol.append({"status": DEAL_EXPIRED, "text": f"{DEAL_EXPIRED}: срок {until} раньше даты заявки {submitted}."})
        findings.append(DEAL_EXPIRED)
    return extracted


def _declaration(blocks: dict[str, str], protocol: list[dict], findings: list[str]) -> None:
    text = blocks.get("декларация") or ""
    if not text.strip():
        text = "\n".join(blocks.values())
    folded = text.casefold()
    for token, title in DECLARATION_POINTS:
        if token in folded:
            protocol.append(
                {
                    "status": "абзац найден",
                    "text": f"Абзац «{title}» найден. Наличие абзаца не подтверждает факт.",
                }
            )
        else:
            note = f"Абзац «{title}» не найден."
            protocol.append({"status": "абзац не найден", "text": note})
            findings.append(note)


def _requisites(
    blocks: dict[str, str],
    statement: dict,
    extracted: dict[str, str],
    protocol: list[dict],
    findings: list[str],
) -> None:
    sections = {
        "анкете": _fields(blocks.get("анкета") or ""),
        "декларации": _fields(blocks.get("декларация") or ""),
        "приказе": _fields(blocks.get("приказ") or ""),
    }
    titles = {"inn": "ИНН", "kpp": "КПП", "ogrn": "ОГРН", "name": "наименование", "director": "ФИО директора"}
    for place, fields in sections.items():
        for key, title in titles.items():
            left = fields.get(key) or ""
            right = str(statement.get(key) or "")
            if not left or not right or _fold(left) == _fold(right):
                continue
            if key == "director":
                text = f"{DIRECTOR_MISMATCH}: в {place} «{left}», в выписке «{right}»."
                protocol.append({"status": DIRECTOR_MISMATCH, "text": text})
            else:
                text = f"Ошибка: {title} в {place} «{left}» не совпадает с выпиской «{right}»."
                protocol.append({"status": NEEDS_REVIEW, "text": text})
            findings.append(text)
    person = extracted.get("decision_fio") or ""
    director = str(statement.get("director") or "")
    if person and director and _fold(person) != _fold(director):
        text = f"{DIRECTOR_MISMATCH}: в решении «{person}», в выписке «{director}»."
        protocol.append({"status": DIRECTOR_MISMATCH, "text": text})
        findings.append(text)
    elif person and director:
        protocol.append({"status": "Корректно", "text": "ФИО решения совпадает с ФИО выписки."})


def _bank(blocks: dict[str, str], protocol: list[dict], findings: list[str]) -> None:
    fields = {}
    for block in blocks.values():
        fields.update({key: value for key, value in _fields(block).items() if value})
    expected = {"bik": 9, "account": 20, "corr": 20}
    names = {"bik": "БИК", "account": "Расчётный счёт", "corr": "Корреспондентский счёт"}
    for key, length in expected.items():
        raw = re.sub(r"\D", "", fields.get(key) or "")
        if not raw:
            continue
        if len(raw) != length:
            text = f"Ошибка формата: {names[key]} содержит {len(raw)} цифр, нужно {length}."
            protocol.append({"status": NEEDS_REVIEW, "text": text})
            findings.append(text)
        else:
            protocol.append({"status": "Корректно", "text": f"{names[key]} содержит {length} цифр."})


def _registries(registry, key: str) -> list[dict]:
    rows = []
    for kind in ("rnp_223", "rnp_44", "liquidation", "bankruptcy", "disqualification"):
        found = registry.lookup(kind, key)
        rows.append(
            {
                "kind": kind,
                "status": found.get("status") or "not_checked",
                "source": found.get("source_url") or "",
            }
        )
    return rows


def _rate_rule(code: str, table: list[dict[str, str]] | None) -> str | None:
    if not table:
        return None
    matches = [row for row in table if code.startswith(row.get("okpd2_prefix") or "")]
    if not matches:
        return None
    best = max(matches, key=lambda row: len(row.get("okpd2_prefix") or ""))
    return best.get("rates") or ""


def _math_items(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        folded = line.casefold()
        if "цена" not in folded or "количество" not in folded:
            continue
        items.append(
            {
                "no": _field(line, "№") or _field(line, "строка") or "1",
                "name": "Строка",
                "qty": _field(line, "количество"),
                "extra": {
                    "price": _field(line, "цена"),
                    "line_sum": _field(line, "сумма"),
                    "vat": _field(line, "ндс"),
                },
            }
        )
    return items


def _blocks(text: str) -> dict[str, str]:
    current = "текст"
    chunks: dict[str, list[str]] = {current: []}
    for line in text.splitlines():
        heading = line.strip().casefold().rstrip(":")
        if heading in _HEADINGS:
            current = heading
            chunks.setdefault(current, [])
            continue
        chunks.setdefault(current, []).append(line)
    return {key: "\n".join(value) for key, value in chunks.items()}


def _fields(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        for label, key in _LABELS:
            match = re.search(rf"{label}\s*[:\-]\s*(.+)", line, re.IGNORECASE)
            if match and key not in found:
                found[key] = match.group(1).strip()
    return found


def _field(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*[:\-]\s*([^|]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _money(value: str) -> float | None:
    digits = re.sub(r"[^\d,.-]", "", value or "").replace(" ", "").replace(",", ".")
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _iso(value: str) -> str:
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", value or "")
    if not match:
        return value or ""
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", value).casefold().strip()
