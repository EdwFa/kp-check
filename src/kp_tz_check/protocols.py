"""Текстовый протокол комиссии. Письмо остаётся черновиком и не отправляется."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import re

from kp_tz_check.calculations import parse_money


STATUS_OK = "Корректно"
STATUS_ATTENTION = "Требует внимания"
STATUS_CRITICAL = "Критическая ошибка"
PROCEDURE_CRITICAL = "Критическая ошибка: нарушение процедуры"
SIGNING_REVIEW = "Требует ручной проверки перед подписанием"
PRICE_ADVICE = (
    "Рекомендуется направить участнику предложение о добровольном снижении "
    "цены договора в целях экономии бюджетных средств"
)
OCR_NEEDED = "нужен OCR"
QUORUM_UNCHECKED = "кворум не проверен"
MEMBERS_ENV = "KP_COMMISSION_MEMBERS"
_TEXT_EXTS = {".txt", ".docx", ".doc", ".docm", ".dotx"}


def check_protocol(
    text: str,
    *,
    nmck: float | None = None,
    bid: dict | None = None,
    members: list[str] | None = None,
    pdf_empty: bool = False,
) -> dict:
    fields = _fields(text or "")
    findings: list[str] = []
    notes: list[str] = []
    if pdf_empty:
        findings.append(OCR_NEEDED)
    elif not (text or "").strip():
        findings.append("Текст протокола не извлечён.")
    else:
        _procedure(text or "", fields, findings)
        _price(fields, nmck, findings, notes)
        _bid(fields, bid, findings)
    quorum = _quorum(fields["commission"], members, findings if (text or "").strip() and not pdf_empty else None)
    if findings and findings[0] == OCR_NEEDED or (findings and findings[0] == "Текст протокола не извлечён."):
        quorum = QUORUM_UNCHECKED
    draft = _draft(text or "", fields, findings)
    critical = any(item.startswith(STATUS_CRITICAL) or PROCEDURE_CRITICAL in item for item in findings)
    if critical:
        status = STATUS_CRITICAL
    elif findings:
        status = STATUS_ATTENTION
    else:
        status = STATUS_OK
    winner = None
    if fields["participant"] and _admitted(fields["decision"]) and not pdf_empty:
        winner = {"name": fields["participant"], "inn": fields["inn"], "price": fields["price"]}
    return {
        "status": status,
        "fields": fields,
        "decision_text": _decision_text(fields),
        "findings": findings,
        "notes": notes,
        "quorum": quorum,
        "draft_letter": draft,
        "letter_sent": False,
        "winner": winner,
        "contract_allowed": status != STATUS_CRITICAL and not pdf_empty and winner is not None,
    }


def load_members(path: Path | str | None = None) -> list[str] | None:
    raw = path if path is not None else os.environ.get(MEMBERS_ENV)
    if not raw:
        return None
    with Path(raw).open(encoding="utf-8", newline="") as stream:
        return [row["name"].strip() for row in csv.DictReader(stream) if row.get("name", "").strip()]


def load_protocols(root: Path, *, members: list[str] | None = None) -> list[dict]:
    folder = Path(root) / "protocols"
    if not folder.exists():
        return []
    reports = []
    for path in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.name.startswith("."):
            continue
        suffix = path.suffix.lower()
        if suffix in _TEXT_EXTS:
            text = _read(path)
            report = check_protocol(text, members=members)
        elif suffix == ".pdf":
            text = _pdf_layer(path)
            report = check_protocol(text, members=members, pdf_empty=not text.strip())
        else:
            continue
        report["source_file"] = path.name
        reports.append(report)
    return reports


def _procedure(text: str, fields: dict, findings: list[str]) -> None:
    folded = text.casefold()
    if "аукцион" not in folded or not _admitted(fields["decision"]):
        return
    failed = re.search(r"не\s*состоял", folded) is not None
    held = re.search(r"(?<!не)(?<!не\s)состоял", folded) is not None
    if held and not failed:
        findings.append(PROCEDURE_CRITICAL)
        return
    if failed and "проект договора" not in folded:
        findings.append("Нет решения о передаче проекта договора единственному участнику.")


def _price(fields: dict, nmck: float | None, findings: list[str], notes: list[str]) -> None:
    price = parse_money(fields["price"])
    notice = nmck if nmck is not None else parse_money(fields["nmck"])
    if price is None or notice is None:
        return
    gap = round(notice - price, 2)
    if abs(gap) <= 0.01:
        findings.append(PRICE_ADVICE)
    elif gap > 0:
        notes.append(f"Цена снижена, экономия составляет {_money(gap)} руб.")
    else:
        findings.append("Цена выше НМЦК.")


def _bid(fields: dict, bid: dict | None, findings: list[str]) -> None:
    if not bid:
        return
    pairs = (
        ("наименование", fields["participant"], bid.get("name")),
        ("ИНН", fields["inn"], bid.get("inn")),
        ("сумма", fields["price"], bid.get("total")),
    )
    for title, left, right in pairs:
        if left in (None, "") or right in (None, ""):
            continue
        if title == "сумма":
            if parse_money(str(left)) is None or parse_money(str(right)) is None:
                continue
            if abs(parse_money(str(left)) - parse_money(str(right))) <= 0.01:
                continue
        elif _fold(str(left)) == _fold(str(right)):
            continue
        findings.append(f"{SIGNING_REVIEW}: {title} протокола «{left}» не совпадает с заявкой «{right}».")


def _quorum(present: list[str], members: list[str] | None, findings: list[str] | None) -> str:
    if members is None:
        if findings is not None:
            findings.append(QUORUM_UNCHECKED)
        return QUORUM_UNCHECKED
    roster = {_fold(item.split()[0]) for item in members if item.split()}
    unknown = [item for item in present if item.split() and _fold(item.split()[0]) not in roster]
    if unknown:
        if findings is not None:
            findings.append("Фамилия не входит в утверждённый состав: " + ", ".join(unknown) + ".")
        return "фамилия не входит в утверждённый состав"
    if len(present) * 2 <= len(members):
        if findings is not None:
            findings.append("Кворум не собран.")
        return "кворум не собран"
    return "кворум есть"


def _draft(text: str, fields: dict, findings: list[str]) -> str:
    if PROCEDURE_CRITICAL in findings:
        return ""
    name = fields["participant"] or "участник"
    if PRICE_ADVICE in findings:
        return f"{name}: {PRICE_ADVICE}"
    if "проект договора" in text.casefold() and _admitted(fields["decision"]):
        return (
            f"Уведомление для {name}: проект договора передаётся этому участнику. "
            "Черновик не отправлен."
        )
    return ""


def _fields(text: str) -> dict:
    number = _search(r"протокол\s*№\s*(\S+)", text) or _search(r"номер\s*[:\-]\s*(\S+)", text)
    application = re.search(
        r"заявка\s*№\s*(\S+)(?:\s*от\s*(\d{2}\.\d{2}\.\d{4}))?",
        text or "",
        re.IGNORECASE,
    )
    commission = _search(r"состав\s*[:\-]\s*(.+)", text)
    return {
        "number": number,
        "date": _search(r"дата(?:\s+протокола)?\s*[:\-]\s*(\d{2}\.\d{2}\.\d{4})", text),
        "subject": _search(r"предмет\s*[:\-]\s*(.+)", text),
        "nmck": _search(r"нмцк\s*[:\-]\s*([\d\s.,]+)", text),
        "commission": [item.strip() for item in commission.split(",") if item.strip()] if commission else [],
        "participant": _search(r"участник\s*[:\-]\s*(.+)", text),
        "inn": _search(r"инн\s*[:\-]\s*(\d+)", text),
        "application_no": application.group(1) if application else "",
        "application_date": application.group(2) or "" if application else "",
        "decision": _search(r"решение\s*[:\-]\s*(.+)", text),
        "basis": _search(r"основание\s*[:\-]\s*(.+)", text),
        "price": _search(r"цена\s*[:\-]\s*([\d\s.,]+)", text),
    }


def _decision_text(fields: dict) -> str:
    decision = fields["decision"]
    basis = fields["basis"]
    if decision and basis:
        return f"{decision}. Основание: {basis}"
    return decision or basis


def _admitted(decision: str) -> bool:
    folded = decision.casefold()
    if "отклон" in folded or "не допущен" in folded:
        return False
    return "допущен" in folded


def _search(pattern: str, text: str) -> str:
    match = re.search(pattern, text or "", re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _money(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", value).casefold().strip()


def _read(path: Path) -> str:
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
