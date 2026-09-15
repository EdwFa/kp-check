from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

WORD_EXTS = {".docx", ".docm", ".dotx"}
LEGACY_WORD_EXTS = {".doc"}
PDF_EXTS = {".pdf"}


@dataclass
class ExtractedDoc:
    path: Path
    paragraphs: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        blocks = list(self.paragraphs)
        for table in self.tables:
            for row in table:
                blocks.append(" | ".join(cell for cell in row if cell))
        return "\n".join(blocks)


def extract_document(path: Path) -> ExtractedDoc:
    suffix = path.suffix.lower()
    if suffix in WORD_EXTS:
        return _extract_docx(path)
    if suffix in LEGACY_WORD_EXTS:
        binary = _extract_doc_binary(path)
        if binary.tables:
            return binary
        worded = _extract_doc_win32(path)
        if worded.tables:
            return worded
        notes = binary.notes + worded.notes
        if not notes:
            notes = ["Не удалось прочитать .doc, требует ручной проверки"]
        return ExtractedDoc(path=path, paragraphs=binary.paragraphs or worded.paragraphs, notes=notes)
    if suffix in PDF_EXTS:
        return _extract_pdf(path)
    return ExtractedDoc(path=path, notes=[f"Формат {suffix} не поддержан для разбора"])


def iter_block_items(doc: Document):
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _cell_text(cell) -> str:
    lines = []
    for paragraph in cell.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def _table_matrix(table: Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        rows.append([_cell_text(cell) for cell in row.cells])
    return rows


def _extract_docx(path: Path) -> ExtractedDoc:
    doc = Document(str(path))
    paragraphs: list[str] = []
    tables: list[list[list[str]]] = []
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                paragraphs.append(re.sub(r"[ \t]+", " ", text))
        else:
            tables.append(_table_matrix(block))
    return ExtractedDoc(path=path, paragraphs=paragraphs, tables=tables)


def _extract_doc_win32(path: Path) -> ExtractedDoc:
    cache_dir = path.parent / ".extracts"
    cached = cache_dir / f"{path.stem}.docx"
    if cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime:
        extracted = _extract_docx(cached)
        extracted.path = path
        return extracted

    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            cache_dir.mkdir(exist_ok=True)
            _word_convert_to_docx(path, cached)
            extracted = _extract_docx(cached)
            extracted.path = path
            return extracted
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2)
    return ExtractedDoc(
        path=path,
        notes=[f"Не удалось прочитать .doc: {last_error}, требует ручной проверки"],
    )


def _word_convert_to_docx(src: Path, dest: Path) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = None
    document = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(str(src.resolve()), ReadOnly=True)
        document.SaveAs(str(dest.resolve()), FileFormat=16)
    finally:
        if document is not None:
            document.Close(False)
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()


def _extract_doc_binary(path: Path) -> ExtractedDoc:
    """Fallback for .doc when Word COM is unavailable: UTF-16 strings inside OLE."""
    data = path.read_bytes()
    raw = data.decode("utf-16le", errors="ignore")
    fragments: list[str] = []
    for match in re.finditer(r"[ЁёА-Яа-яA-Z0-9«»№/.,;:()%\- ]+", raw):
        token = match.group(0).strip()
        if not token:
            continue
        if re.fullmatch(r"\d+", token) and len(token) > 4:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        fragments.append(token)
    paragraphs = fragments
    tables = _table_from_tz_fragments(fragments)
    notes = []
    if not tables:
        notes.append("Таблица .doc собрана не полностью, требует ручной проверки")
    return ExtractedDoc(path=path, paragraphs=paragraphs, tables=tables, notes=notes)


def _table_from_tz_fragments(fragments: list[str]) -> list[list[list[str]]]:
    text = "\n".join(fragments)
    if "наименование товара" not in text.lower():
        return []
    pieces = re.split(r"(?=Набор реагентов для)", text)
    rows = [["№ п.п.", "Наименование товара, назначение", "Характеристики", "Единица измерения", "Кол-во"]]
    index = 1
    for piece in pieces:
        if not re.search(r"Набор реагентов для", piece):
            continue
        unit_match = re.search(r"\bшт\.?\b", piece, re.I)
        if not unit_match:
            continue
        after = piece[unit_match.end() :]
        qty_match = re.search(r"\b(\d{1,4})\b", after)
        qty = qty_match.group(1) if qty_match else ""
        name_match = re.search(r"Набор реагентов для[^\n]*", piece)
        name = name_match.group(0).strip() if name_match else "Набор реагентов"
        specs = piece[: unit_match.start()]
        specs = re.sub(r"Набор реагентов для[^\n]*", "", specs, count=1).strip()
        if not specs or not qty:
            continue
        rows.append([str(index), name, specs, unit_match.group(0), qty])
        index += 1
    return [rows] if len(rows) > 1 else []


def _extract_pdf(path: Path) -> ExtractedDoc:
    try:
        import fitz
    except ImportError:
        return ExtractedDoc(path=path, notes=["Для PDF нужен пакет pymupdf"])

    try:
        document = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        return ExtractedDoc(path=path, notes=[f"Не удалось открыть PDF: {exc}"])

    paragraphs: list[str] = []
    tables: list[list[list[str]]] = []
    notes: list[str] = []
    try:
        for page in document:
            text = page.get_text("text") or ""
            for line in text.splitlines():
                cleaned = re.sub(r"[ \t]+", " ", line).strip()
                if cleaned:
                    paragraphs.append(cleaned)
            try:
                found = page.find_tables()
            except Exception:
                found = None
            if not found:
                continue
            for table in found.tables:
                matrix = []
                for row in table.extract():
                    matrix.append([re.sub(r"\s+", " ", (cell or "")).strip() for cell in row])
                if matrix:
                    tables.append(matrix)
        if not paragraphs:
            notes.append("Текст PDF не извлечён, требует ручной проверки")
        return ExtractedDoc(path=path, paragraphs=paragraphs, tables=tables, notes=notes)
    finally:
        document.close()
