"""Загрузка курируемых OKF-концепций для compliance-проверок.

OKF здесь используется как версионируемый каталог знаний, а не как
поисковый или векторный индекс. Выбор концепций выполняется по id и tags.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


DEFAULT_KNOWLEDGE_ROOT = Path(__file__).with_name("knowledge")
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Concept:
    concept_id: str
    metadata: dict[str, Any]
    body: str
    path: Path

    @property
    def type(self) -> str:
        return str(self.metadata.get("type") or "")

    @property
    def tags(self) -> tuple[str, ...]:
        value = self.metadata.get("tags") or ()
        return tuple(value) if isinstance(value, (list, tuple)) else (str(value),)


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        return [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value.strip("'\"")


def _parse_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError(f"OKF-файл без YAML frontmatter: {path}")
    metadata: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Некорректный frontmatter в {path}: {line}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = _parse_scalar(value)
    if not metadata.get("type"):
        raise ValueError(f"OKF-концепция без type: {path}")
    return metadata, match.group(2).strip()


def load_bundle(root: Path | str | None = None) -> dict[str, Concept]:
    root = Path(root) if root is not None else DEFAULT_KNOWLEDGE_ROOT
    if not root.exists():
        raise FileNotFoundError(f"OKF-бандл не найден: {root}")
    concepts: dict[str, Concept] = {}
    for path in sorted(root.rglob("*.md")):
        if path.name == "index.md" and path.parent == root:
            continue
        concept_id = path.relative_to(root).with_suffix("").as_posix()
        metadata, body = _parse_frontmatter(path.read_text(encoding="utf-8"), path)
        concepts[concept_id] = Concept(concept_id, metadata, body, path)
    if not concepts:
        raise ValueError(f"OKF-бандл не содержит концепций: {root}")
    return concepts


def get_concepts(
    *,
    ids: list[str] | None = None,
    tags: list[str] | None = None,
    root: Path | str | None = None,
) -> list[Concept]:
    concepts = load_bundle(root)
    if ids is not None:
        missing = sorted(set(ids) - set(concepts))
        if missing:
            raise KeyError(f"OKF-концепции не найдены: {', '.join(missing)}")
        return [concepts[item] for item in ids]
    if tags:
        wanted = set(tags)
        return [concept for concept in concepts.values() if wanted.intersection(concept.tags)]
    return list(concepts.values())
