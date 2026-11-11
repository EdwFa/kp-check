"""Черновик запроса КП из локального примера. Почта не отправляется, дата сама не ставится."""

from __future__ import annotations

from pathlib import Path
import uuid

from docx import Document


def build_request(
    template: Path | str,
    target_dir: Path | str,
    *,
    outgoing: str,
    supplier: str,
    email: str,
    items: list[dict],
    sent_on: str = "",
) -> dict:
    document = Document(str(template))
    sent = (sent_on or "").strip()
    mapping = {
        "outgoing": outgoing,
        "sent_clause": f" от {sent}" if sent else "",
        "sent_on": sent,
        "supplier": supplier,
        "email": email,
    }
    for paragraph in document.paragraphs:
        _replace(paragraph, mapping)
    table = document.tables[0]
    for item in items:
        cells = table.add_row().cells
        cells[0].text = str(item.get("name") or "")
        cells[1].text = str(item.get("specs") or "")
        cells[2].text = str(item.get("unit") or "")
        cells[3].text = str(item.get("qty") or "")
    directory = Path(target_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"request-{uuid.uuid4().hex[:12]}.docx"
    document.save(path)
    return {"path": path, "sent_on": sent, "mailed": False}


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
