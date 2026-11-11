"""Черновик договора из локального шаблона. Файл пишется только после подтверждения."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from docx import Document

from kp_tz_check.journal import append_contract_record


REQUIRED = ("name", "qty", "price", "sum")
PLACEHOLDERS = ("name", "qty", "price", "sum", "specs", "shelf", "delivery")


def render_contract(
    template: Path | str,
    target_dir: Path | str,
    fields: dict,
    *,
    confirmed: bool,
    operator: str,
    reason: str,
    journal_path: Path | str | None = None,
    fingerprint: str = "",
    winner: str = "",
) -> dict:
    if not confirmed:
        return {"written": False, "path": None, "reason": "нет подтверждения оператора"}
    missing = [key for key in REQUIRED if not str(fields.get(key) or "").strip()]
    if missing:
        return {"written": False, "path": None, "reason": "не заполнен обязательный плейсхолдер: " + ", ".join(missing)}
    template_path = Path(template)
    if not template_path.is_file():
        return {"written": False, "path": None, "reason": "файл шаблона не найден"}
    document = Document(str(template_path))
    template_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    absent = [key for key in REQUIRED if "{{" + key + "}}" not in template_text and not _table_has(document, "{{" + key + "}}")]
    if absent:
        return {"written": False, "path": None, "reason": "в шаблоне нет плейсхолдера: " + ", ".join(absent)}
    mapping = {key: str(fields.get(key) or "") for key in PLACEHOLDERS}
    for paragraph in document.paragraphs:
        _replace(paragraph, mapping)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _replace(paragraph, mapping)
    directory = Path(target_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = _unique(directory)
    document.save(path)
    if journal_path is not None:
        append_contract_record(
            journal_path,
            fingerprint=fingerprint,
            operator=operator,
            reason=reason,
            filename=path.name,
            winner=winner,
        )
    return {"written": True, "path": path, "reason": ""}


def _replace(paragraph, mapping: dict[str, str]) -> None:
    text = paragraph.text
    updated = text
    for key, value in mapping.items():
        updated = updated.replace("{{" + key + "}}", value)
    if updated == text:
        return
    if paragraph.runs:
        paragraph.runs[0].text = updated
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(updated)


def _table_has(document: Document, token: str) -> bool:
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if token in cell.text:
                    return True
    return False


def _unique(directory: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return directory / f"contract-{stamp}-{uuid.uuid4().hex[:8]}.docx"
