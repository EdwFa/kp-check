from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from kp_tz_check.dates import date_from_filename, find_dates, parse_date_string
from kp_tz_check.extract import ExtractedDoc, extract_document
from kp_tz_check.models import (
    ROW_INSUFFICIENT,
    ApplicationRecord,
    Item,
    KpRecord,
    NmckRecord,
    RequestRecord,
    SecurityDocument,
    TzRecord,
)

OUTGOING_RE = re.compile(
    r"исх\.?\s*№?\s*([0-9]+)\s*от\s+(.+)",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
PREP_HINTS = ("дата", "подготов", "составлен", "исх", "г.", "москва", "от ")
DOC_EXTS = {".doc", ".docx", ".docm", ".dotx", ".pdf"}
FILENAME_OUTGOING = re.compile(r"^(\d{3,})")
KP_TITLE_DATE = re.compile(
    r"коммерческ\w*\s+предложен\w*\s*№?\s*\S*\s*от\s+(.+)",
    re.IGNORECASE,
)

NAME_HEADERS = ("наименование", "товар", "позиция", "номенклатура", "название")
SPEC_HEADERS = ("характерист", "функц", "параметр", "требован")
UNIT_HEADERS = ("ед", "единица")
QTY_HEADERS = ("кол", "количество", "кол-во")


def load_incoming(
    root: Path,
) -> tuple[list[RequestRecord], list[KpRecord], list[TzRecord], list[ApplicationRecord]]:
    requests = _load_requests(root / "requests")
    kps = _load_kps(root / "kp")
    tzs = _load_tzs(root / "tz")
    applications = _load_applications(root / "applications")
    return requests, kps, tzs, applications


def load_bids(root: Path):
    """Пакеты incoming/bids/<участник>/part1. Не входит в четвёрку load_incoming."""
    from kp_tz_check.bids import load_bid_packages

    return load_bid_packages(root)


def load_protocols(root: Path):
    """Протоколы incoming/protocols. Не входит в четвёрку load_incoming."""
    from kp_tz_check.protocols import load_protocols as _load

    return _load(root)


def _iter_docs(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in DOC_EXTS and not path.name.startswith("~$")
    ]
    return sorted(files, key=lambda path: path.name.lower())


def _load_requests(folder: Path) -> list[RequestRecord]:
    records: list[RequestRecord] = []
    for path in _iter_docs(folder):
        extracted = extract_document(path)
        records.extend(parse_requests(extracted))
    return records


def _load_kps(folder: Path) -> list[KpRecord]:
    return [parse_kp(extract_document(path)) for path in _iter_docs(folder)]


def _load_tzs(folder: Path) -> list[TzRecord]:
    return [parse_tz(extract_document(path)) for path in _iter_docs(folder)]


def _load_applications(folder: Path) -> list[ApplicationRecord]:
    return [parse_application(extract_document(path)) for path in _iter_docs(folder)]


def load_nmck(root: Path) -> list[NmckRecord]:
    """Прочитать incoming/nmck. Нет папки — пустой список."""
    return [parse_nmck(extract_document(path)) for path in _iter_docs(root / "nmck")]


def load_security_documents(root: Path) -> list[SecurityDocument]:
    """Отдельные документы обеспечения. Нет папки — пустой список."""
    return [
        SecurityDocument(source_file=path, body=extract_document(path).text)
        for path in _iter_docs(root / "security")
    ]


_FORMULA_RE = re.compile(r".{0,40}(?:НМЦК|НМЦД|коэффициент\s+вариации|V\s*=).{0,80}", re.IGNORECASE)


def parse_nmck(extracted: ExtractedDoc) -> NmckRecord:
    """Разобрать обоснование. Строка без количества сохраняется: сверка идёт по поставщику и позиции."""
    from kp_tz_check.calculations import extract_declared_total

    items: list[Item] = []
    for table in extracted.tables:
        if len(table) < 2:
            continue
        mapping = [
            "price_unit" if kind == "price_ambiguous" else kind
            for kind in (_header_kind(cell) for cell in table[0])
        ]
        if "name" not in mapping and "supplier" not in mapping:
            continue
        for row in table[1:]:
            joined = " ".join(row).lower()
            if joined.startswith("итого") or not any(cell.strip() for cell in row):
                continue
            values = {kind: (row[idx] if idx < len(row) else "") for idx, kind in enumerate(mapping) if kind}
            name = values.get("name", "").strip()
            supplier = values.get("supplier", "").strip()
            if not name and not supplier:
                continue
            extra: dict[str, str] = {}
            if supplier:
                extra["supplier"] = supplier
            price = values.get("price_unit", "").strip() or values.get("price_total", "").strip()
            if price:
                extra["price"] = price
                extra["price_raw"] = price
            items.append(
                Item(
                    no=values.get("no", "").strip(),
                    name=name,
                    specs=values.get("specs", "").strip(),
                    unit=values.get("unit", "").strip(),
                    qty=values.get("qty", "").strip(),
                    extra=extra,
                )
            )
    declared = extract_declared_total(extracted.text)
    formula_match = _FORMULA_RE.search(extracted.text)
    return NmckRecord(
        source_file=extracted.path,
        body=extracted.text,
        items=items,
        declared_total=declared.get("raw"),
        formula=formula_match.group(0).strip() if formula_match else "",
        notes=list(extracted.notes),
    )


def parse_application(extracted: ExtractedDoc) -> ApplicationRecord:
    """Разобрать заявку. Пустая цена или код ОКПД2 не заполняются из других колонок."""
    items = _items_from_tables(extracted.tables)
    for item in items:
        price = item.extra.get("price", "").strip()
        okpd2 = item.extra.get("okpd2", "").strip()
        item.extra["price"] = price
        item.extra["okpd2"] = okpd2
        if not price or not okpd2:
            item.extra["row_status"] = ROW_INSUFFICIENT
    return ApplicationRecord(
        source_file=extracted.path,
        body=extracted.text,
        items=items,
        notes=list(extracted.notes),
    )


def parse_requests(extracted: ExtractedDoc) -> list[RequestRecord]:
    letters: list[dict] = []
    body_start: int | None = None
    paragraphs = extracted.paragraphs
    i = 0
    while i < len(paragraphs):
        line = paragraphs[i]
        match = OUTGOING_RE.search(line)
        if match and body_start is None:
            sent_raw = match.group(2).strip()
            supplier = None
            email = None
            if i + 1 < len(paragraphs) and "@" not in paragraphs[i + 1] and not OUTGOING_RE.search(paragraphs[i + 1]):
                supplier = _clean_org_name(paragraphs[i + 1])
            if i + 2 < len(paragraphs) and EMAIL_RE.search(paragraphs[i + 2]):
                email = EMAIL_RE.search(paragraphs[i + 2]).group(0)
            letters.append(
                {
                    "outgoing_no": match.group(1),
                    "sent_on": parse_date_string(sent_raw),
                    "sent_on_raw": sent_raw,
                    "supplier": supplier,
                    "email": email,
                }
            )
            i += 1
            continue
        if line.upper().startswith("ЗАПРОС") and body_start is None:
            body_start = i
        i += 1

    items = _items_from_tables(extracted.tables)
    body = "\n".join(paragraphs[body_start:] if body_start is not None else paragraphs)
    notes = list(extracted.notes)
    if not letters:
        sent = None
        sent_raw = None
        dates = find_dates("\n".join(paragraphs[:20]))
        if dates:
            sent, sent_raw, _ = dates[0]
        else:
            notes.append("Дата отправки запроса не прочитана, требует ручной проверки")
        return [
            RequestRecord(
                source_file=extracted.path,
                outgoing_no=None,
                sent_on=sent,
                sent_on_raw=sent_raw,
                supplier=_guess_supplier(extracted.text),
                email=_first_email(extracted.text),
                body=body,
                items=items,
                notes=notes,
            )
        ]

    records = []
    for letter in letters:
        record_notes = list(notes)
        if letter["sent_on"] is None:
            record_notes.append("Дата отправки запроса не прочитана, требует ручной проверки")
        records.append(
            RequestRecord(
                source_file=extracted.path,
                outgoing_no=letter["outgoing_no"],
                sent_on=letter["sent_on"],
                sent_on_raw=letter["sent_on_raw"],
                supplier=letter["supplier"],
                email=letter["email"],
                body=body,
                items=items,
                notes=record_notes,
            )
        )
    return records


def parse_kp(extracted: ExtractedDoc) -> KpRecord:
    registered, registered_raw = date_from_filename(extracted.path.name)
    notes = list(extracted.notes)
    if registered is None:
        notes.append("Дата регистрации КП в названии файла не прочитана, требует ручной проверки")

    prepared, prepared_raw = _kp_prepared_date(extracted)
    if prepared is None:
        notes.append("Дата подготовки КП не указана или не прочитана, требует ручной проверки")

    outgoing = None
    match = FILENAME_OUTGOING.match(extracted.path.stem)
    if match:
        outgoing = match.group(1)

    items = _apply_origin_labels(_enrich_items_from_text(_items_from_tables(extracted.tables), extracted.text), extracted.text)
    return KpRecord(
        source_file=extracted.path,
        prepared_on=prepared,
        prepared_on_raw=prepared_raw,
        registered_on=registered,
        registered_on_raw=registered_raw,
        supplier=_guess_supplier(extracted.text) or _supplier_from_filename(extracted.path.stem),
        outgoing_no=outgoing,
        body=extracted.text,
        items=items,
        notes=notes,
    )


def parse_tz(extracted: ExtractedDoc) -> TzRecord:
    notes = list(extracted.notes)
    items = _items_from_tables(extracted.tables)
    if not items:
        notes.append("Таблица позиций ТЗ не прочитана, требует ручной проверки")
    title = next((line for line in extracted.paragraphs if "техническ" in line.lower()), extracted.path.stem)
    return TzRecord(source_file=extracted.path, title=title, items=items, notes=notes)


def _kp_prepared_date(extracted: ExtractedDoc) -> tuple[date | None, str | None]:
    for paragraph in extracted.paragraphs[:20]:
        titled = KP_TITLE_DATE.search(paragraph)
        if titled:
            parsed = parse_date_string(titled.group(1))
            if parsed:
                return parsed, titled.group(1).strip()
    header = "\n".join(extracted.paragraphs[:25])
    dates = find_dates(header) or find_dates(extracted.text[:1500])
    if not dates:
        return None, None
    scored: list[tuple[int, date, str]] = []
    text_lower = extracted.text.lower()
    for value, raw, index in dates:
        window = text_lower[max(0, index - 80) : index + 80]
        score = 0
        if any(hint in window for hint in PREP_HINTS):
            score += 2
        if index < 400:
            score += 1
        if any(token in window for token in ("поставк", "срок действия", "31 декабря", "30.11")):
            score -= 3
        scored.append((score, value, raw))
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, value, raw = scored[0]
    if best_score < 0:
        return None, None
    return value, raw


def _clean_org_name(value: str) -> str:
    return re.sub(r"[«»\"']", "", value or "").strip()


def _guess_supplier(text: str) -> str | None:
    match = re.search(r"(ООО|АО|ПАО|ИП)\s+[«\"']?[\wЁёА-Яа-я0-9.\- ]{2,80}", text)
    if match:
        return _clean_org_name(re.sub(r"\s+", " ", match.group(0)))
    return None


def _first_email(text: str) -> str | None:
    match = EMAIL_RE.search(text)
    return match.group(0) if match else None


def _supplier_from_filename(stem: str) -> str | None:
    cleaned = re.sub(r"\d{1,2}[.\-_]\d{1,2}[.\-_]\d{2,4}", " ", stem)
    cleaned = re.sub(r"(?i)\b(кп|коммерческое|предложение|исх|от)\b", " ", cleaned)
    cleaned = re.sub(r"[_]+", " ", cleaned).strip(" -_")
    return cleaned or None


def _norm_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("ё", "е"))


def _header_kind(value: str) -> str | None:
    header = _norm_header(value)
    if "окпд" in header:
        return "okpd2"
    if "скид" in header and "сумм" in header:
        return "discount_sum"
    if "скид" in header:
        return "discount_percent" if ("%" in header or "процент" in header) else "discount"
    if "поставщик" in header or "источник цен" in header:
        return "supplier"
    if "производител" in header:
        return "manufacturer"
    if "страна" in header and "поставщик" not in header:
        return "country"
    if "реестр" in header:
        return "registry"
    if "ст-1" in header or "ст1" in header:
        return "st1"
    if "артикул" in header:
        return "article"
    if any(token in header for token in NAME_HEADERS):
        return "name"
    if any(token in header for token in SPEC_HEADERS):
        return "specs"
    if any(token in header for token in UNIT_HEADERS) and "кол" not in header and "цен" not in header and "сумм" not in header:
        return "unit"
    if any(token in header for token in QTY_HEADERS):
        return "qty"
    if "сумм" in header or "стоимость" in header:
        return "price_total"
    if "цена за" in header or "цена (с" in header:
        return "price_unit"
    if header == "цена":
        return "price_ambiguous"
    if "ндс" in header:
        return "vat"
    if header.startswith("№") or "п/п" in header or "п.п" in header:
        return "no"
    return None


def _unit_from_qty_header(header: str) -> str:
    text = _norm_header(header)
    for token in ("шт", "набор", "упак", "комплект", "фл"):
        if token in text:
            return token
    return ""


def _items_from_tables(tables: list[list[list[str]]]) -> list[Item]:
    items: list[Item] = []
    for table in tables:
        if len(table) < 2:
            continue
        mapping = [_header_kind(cell) for cell in table[0]]
        if "price_ambiguous" in mapping and "price_unit" in mapping:
            mapping = [
                "price_total" if kind == "price_ambiguous" else kind
                for kind in mapping
            ]
        else:
            mapping = [
                "price_unit" if kind == "price_ambiguous" else kind
                for kind in mapping
            ]
        if mapping.count(None) == len(mapping):
            continue
        implied_unit = ""
        for idx, kind in enumerate(mapping):
            if kind == "qty" and idx < len(table[0]):
                implied_unit = _unit_from_qty_header(table[0][idx])
        for row in table[1:]:
            joined = " ".join(row).lower()
            if joined.startswith("итого") or not any(cell.strip() for cell in row):
                continue
            values = {kind: (row[idx] if idx < len(row) else "") for idx, kind in enumerate(mapping) if kind}
            name = values.get("name", "").strip()
            specs = values.get("specs", "").strip()
            article = values.get("article", "").strip()
            if article:
                specs = f"{article}. {specs}".strip()
            if not name and not specs:
                continue
            if not specs and "\n" in name:
                head, tail = name.split("\n", 1)
                name, specs = head.strip(), tail.strip()
            qty = values.get("qty", "").strip()
            if not re.search(r"\d", qty):
                continue
            extra = {"article": article} if article else {}
            unit_price = values.get("price_unit", "").strip()
            line_sum = values.get("price_total", "").strip()
            if unit_price:
                extra["price"] = unit_price
                extra["price_kind"] = "price_unit"
            elif line_sum:
                extra["price"] = line_sum
                extra["price_kind"] = "price_total"
            if line_sum:
                extra["line_sum"] = line_sum
            if values.get("discount", "").strip():
                extra["discount"] = values["discount"].strip()
            if values.get("discount_percent", "").strip():
                extra["discount_percent"] = values["discount_percent"].strip()
            if values.get("discount_sum", "").strip():
                extra["discount_sum"] = values["discount_sum"].strip()
            if values.get("supplier", "").strip():
                extra["supplier"] = values["supplier"].strip()
            for key in ("manufacturer", "country", "registry", "st1"):
                raw = values.get(key, "").strip()
                if raw:
                    extra[key] = raw
            if values.get("vat", "").strip():
                extra["vat"] = values["vat"].strip()
            if values.get("okpd2", "").strip():
                extra["okpd2"] = values["okpd2"].strip()
            items.append(
                Item(
                    no=values.get("no", "").strip(),
                    name=name,
                    specs=specs,
                    unit=values.get("unit", "").strip() or implied_unit,
                    qty=qty,
                    extra=extra,
                )
            )
    return items


def _apply_origin_labels(items: list[Item], text: str) -> list[Item]:
    """Брать страну и производителя только из явной подписи, не из адреса."""
    patterns = {
        "manufacturer": re.compile(r"производител[ьяю]\s*[:\-]\s*([^\n,;]+)", re.IGNORECASE),
        "country": re.compile(r"страна\s+происхождения\s*[:\-]\s*([^\n,;]+)", re.IGNORECASE),
        "registry": re.compile(r"реестров\w*\s+номер\s*[:\-]\s*([^\n,;]+)", re.IGNORECASE),
    }
    for item in items:
        window = text or ""
        if item.name and item.name in window:
            start = window.find(item.name)
            window = window[max(0, start - 180) : start + 240]
        for key, pattern in patterns.items():
            if item.extra.get(key):
                continue
            match = pattern.search(window) or pattern.search(text or "")
            if match:
                item.extra[key] = match.group(1).strip()
        if not item.extra.get("st1") and re.search(r"\bСТ\s*[-–]?\s*1\b", window, re.IGNORECASE):
            item.extra["st1"] = "СТ-1"
    return items


def _enrich_items_from_text(items: list[Item], text: str) -> list[Item]:
    blob = re.sub(r"\s+", " ", text)
    for item in items:
        haystack = f"{item.extra.get('article', '')} {item.specs} {item.name}"
        sku = re.search(r"(FCH\s*3700/\d+)", haystack, re.I)
        if not sku:
            continue
        pattern = re.compile(re.escape(sku.group(1)).replace(r"\ ", r"\s*"), re.I)
        window = pattern.search(blob)
        if window:
            snippet = blob[max(0, window.start() - 40) : window.end() + 240]
            if len(snippet) > len(item.specs):
                item.specs = snippet.strip()
        if sku.group(1).lower() not in item.specs.lower():
            item.specs = f"{sku.group(1)}. {item.specs}".strip()
    return items
