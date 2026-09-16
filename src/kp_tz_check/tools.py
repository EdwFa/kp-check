"""JSON-schema tools wrapping extract / parse / match / checks.

CLI and Streamlit keep calling the original functions. Agents call `invoke`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from kp_tz_check.checks import audit, summarize
from kp_tz_check.extract import ExtractedDoc, extract_document
from kp_tz_check.match import PairLink, match_items, pair_requests_and_kps_detailed
from kp_tz_check.models import Item, KpRecord, RequestRecord, TzRecord
from kp_tz_check.parse import load_incoming, parse_kp, parse_requests, parse_tz
from kp_tz_check.serde import from_jsonable, to_jsonable
from kp_tz_check.structure import structure_incoming, structure_kp, structure_requests, structure_tz
from kp_tz_check.nomenclature import match_pack_nomenclature
from kp_tz_check.critic import apply_critic
from kp_tz_check.calculations import calculate_market_statistics, check_spec_constraint
from kp_tz_check.compliance import apply_compliance
from kp_tz_check.knowledge import get_concepts

Handler = Callable[..., dict[str, Any]]

ITEM_SCHEMA = {
    "type": "object",
    "description": "Товарная позиция из таблицы ТЗ или КП.",
    "properties": {
        "no": {"type": "string"},
        "name": {"type": "string"},
        "specs": {"type": "string"},
        "unit": {"type": "string"},
        "qty": {"type": "string"},
        "extra": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["no", "name", "specs", "unit", "qty"],
}

EXTRACTED_SCHEMA = {
    "type": "object",
    "description": "Результат extract_document: абзацы и таблицы без додумывания.",
    "properties": {
        "path": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}},
        "tables": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
        "text": {"type": "string", "description": "Производный полный текст, только в ответе."},
    },
    "required": ["path"],
}

REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "source_file": {"type": "string"},
        "outgoing_no": {"type": ["string", "null"]},
        "sent_on": {"type": ["string", "null"], "description": "ISO YYYY-MM-DD"},
        "sent_on_raw": {"type": ["string", "null"]},
        "supplier": {"type": ["string", "null"]},
        "email": {"type": ["string", "null"]},
        "body": {"type": "string"},
        "items": {"type": "array", "items": ITEM_SCHEMA},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["source_file"],
}

KP_SCHEMA = {
    "type": "object",
    "properties": {
        "source_file": {"type": "string"},
        "prepared_on": {"type": ["string", "null"], "description": "ISO YYYY-MM-DD"},
        "prepared_on_raw": {"type": ["string", "null"]},
        "registered_on": {"type": ["string", "null"], "description": "ISO YYYY-MM-DD из имени файла"},
        "registered_on_raw": {"type": ["string", "null"]},
        "supplier": {"type": ["string", "null"]},
        "outgoing_no": {"type": ["string", "null"]},
        "body": {"type": "string"},
        "items": {"type": "array", "items": ITEM_SCHEMA},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["source_file"],
}

TZ_SCHEMA = {
    "type": "object",
    "properties": {
        "source_file": {"type": "string"},
        "title": {"type": ["string", "null"]},
        "items": {"type": "array", "items": ITEM_SCHEMA},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["source_file"],
}

MISMATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string"},
        "tz_item": {"anyOf": [ITEM_SCHEMA, {"type": "null"}]},
        "kp_item": {"anyOf": [ITEM_SCHEMA, {"type": "null"}]},
        "detail": {"type": "string"},
    },
    "required": ["kind", "detail"],
}

PAIR_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "request": {"anyOf": [REQUEST_SCHEMA, {"type": "null"}]},
        "kp": {"anyOf": [KP_SCHEMA, {"type": "null"}]},
        "tz": {"anyOf": [TZ_SCHEMA, {"type": "null"}]},
        "date_mark": {"type": "string"},
        "product_mark": {"type": "string"},
        "status": {"type": "string"},
        "comments": {"type": "array", "items": {"type": "string"}},
        "item_mismatches": {"type": "array", "items": MISMATCH_SCHEMA},
    },
    "required": ["date_mark", "product_mark", "status", "comments"],
}


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    returns: dict[str, Any]

    def openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _extracted_payload(doc: ExtractedDoc) -> dict[str, Any]:
    payload = to_jsonable(doc)
    payload["text"] = doc.text
    return payload


def tool_extract_document(path: str) -> dict[str, Any]:
    doc = extract_document(Path(path))
    return {"document": _extracted_payload(doc)}


def tool_parse_requests(extracted: dict[str, Any]) -> dict[str, Any]:
    doc = from_jsonable(ExtractedDoc, extracted)
    return {"requests": to_jsonable(parse_requests(doc))}


def tool_parse_kp(extracted: dict[str, Any]) -> dict[str, Any]:
    doc = from_jsonable(ExtractedDoc, extracted)
    return {"kp": to_jsonable(parse_kp(doc))}


def tool_parse_tz(extracted: dict[str, Any]) -> dict[str, Any]:
    doc = from_jsonable(ExtractedDoc, extracted)
    return {"tz": to_jsonable(parse_tz(doc))}


def tool_load_incoming(incoming: str) -> dict[str, Any]:
    requests, kps, tzs = load_incoming(Path(incoming))
    return {
        "requests": to_jsonable(requests),
        "kps": to_jsonable(kps),
        "tzs": to_jsonable(tzs),
    }


def tool_structure_requests(extracted: dict[str, Any]) -> dict[str, Any]:
    doc = from_jsonable(ExtractedDoc, extracted)
    return {"requests": to_jsonable(structure_requests(doc))}


def tool_structure_kp(extracted: dict[str, Any]) -> dict[str, Any]:
    doc = from_jsonable(ExtractedDoc, extracted)
    return {"kp": to_jsonable(structure_kp(doc))}


def tool_structure_tz(extracted: dict[str, Any]) -> dict[str, Any]:
    doc = from_jsonable(ExtractedDoc, extracted)
    return {"tz": to_jsonable(structure_tz(doc))}


def tool_structure_incoming(incoming: str) -> dict[str, Any]:
    requests, kps, tzs = structure_incoming(Path(incoming))
    return {
        "requests": to_jsonable(requests),
        "kps": to_jsonable(kps),
        "tzs": to_jsonable(tzs),
    }


def tool_pair_requests_and_kps(
    requests: list[dict[str, Any]],
    kps: list[dict[str, Any]],
) -> dict[str, Any]:
    req_models = [from_jsonable(RequestRecord, item) for item in requests]
    kp_models = [from_jsonable(KpRecord, item) for item in kps]
    links, unmatched_requests, unmatched_kps = pair_requests_and_kps_detailed(req_models, kp_models)
    return {
        "pairs": [
            {
                "request": to_jsonable(item.request),
                "kp": to_jsonable(item.kp),
                "reason": item.reason,
                "score": item.score,
            }
            for item in links
        ],
        "unmatched_requests": to_jsonable(unmatched_requests),
        "unmatched_kps": to_jsonable(unmatched_kps),
    }


def tool_match_items(
    tz_items: list[dict[str, Any]],
    kp_items: list[dict[str, Any]],
) -> dict[str, Any]:
    mismatches = match_items(
        [from_jsonable(Item, item) for item in tz_items],
        [from_jsonable(Item, item) for item in kp_items],
    )
    return {"mismatches": to_jsonable(mismatches)}


def tool_match_nomenclature(
    tzs: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    tz_models = [from_jsonable(TzRecord, item) for item in tzs]
    links = [
        PairLink(
            request=from_jsonable(RequestRecord, item["request"]),
            kp=from_jsonable(KpRecord, item["kp"]),
            reason=str(item.get("reason") or "unknown"),
            score=float(item.get("score") or 0),
        )
        for item in pairs
    ]
    return {"nomenclature": match_pack_nomenclature(links, tz_models)}


def tool_audit(
    requests: list[dict[str, Any]],
    kps: list[dict[str, Any]],
    tzs: list[dict[str, Any]],
    pairs: list[dict[str, Any]] | None = None,
    nomenclature: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pair_links = None
    if pairs is not None:
        pair_links = [
            PairLink(
                request=from_jsonable(RequestRecord, item["request"]),
                kp=from_jsonable(KpRecord, item["kp"]),
                reason=str(item.get("reason") or "unknown"),
                score=float(item.get("score") or 0),
            )
            for item in pairs
        ]
    results = audit(
        [from_jsonable(RequestRecord, item) for item in requests],
        [from_jsonable(KpRecord, item) for item in kps],
        [from_jsonable(TzRecord, item) for item in tzs],
        pair_links=pair_links,
        nomenclature=nomenclature,
    )
    return {"results": to_jsonable(results), "summary": to_jsonable(summarize(results))}


def tool_critique_pack(
    results: list[dict[str, Any]],
    pairs: list[dict[str, Any]] | None = None,
    nomenclature: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return apply_critic(results, pairs or [], nomenclature or [])


def tool_audit_incoming(incoming: str) -> dict[str, Any]:
    loaded = tool_load_incoming(incoming)
    return tool_audit(loaded["requests"], loaded["kps"], loaded["tzs"])


def tool_load_concepts(
    ids: list[str] | None = None,
    tags: list[str] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    concepts = get_concepts(ids=ids, tags=tags, root=root)
    return {
        "concepts": [
            {
                "id": item.concept_id,
                "type": item.type,
                "metadata": item.metadata,
                "body": item.body,
                "path": str(item.path),
            }
            for item in concepts
        ]
    }


def tool_calculate_market_statistics(
    values: list[float | int],
    threshold: float = 33.0,
) -> dict[str, Any]:
    return calculate_market_statistics(values, threshold=threshold)


def tool_check_spec_constraint(tz_specs: str, kp_specs: str) -> dict[str, Any]:
    return check_spec_constraint(tz_specs, kp_specs)


def tool_comply_pack(
    results: list[dict[str, Any]],
    kps: list[dict[str, Any]] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    return apply_compliance(results, kps=kps, root=root)


TOOLS: dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> None:
    TOOLS[spec.name] = spec


_register(
    ToolSpec(
        name="extract_document",
        description="Извлечь абзацы и таблицы из .docx/.doc/.pdf. Значения не додумываются.",
        parameters=_object(
            {"path": {"type": "string", "description": "Путь к файлу документа."}},
            ["path"],
        ),
        handler=tool_extract_document,
        returns=_object({"document": EXTRACTED_SCHEMA}, ["document"]),
    )
)
_register(
    ToolSpec(
        name="parse_requests",
        description="Разобрать исходящие письма запроса. Один файл может дать несколько записей.",
        parameters=_object({"extracted": EXTRACTED_SCHEMA}, ["extracted"]),
        handler=tool_parse_requests,
        returns=_object(
            {"requests": {"type": "array", "items": REQUEST_SCHEMA}},
            ["requests"],
        ),
    )
)
_register(
    ToolSpec(
        name="parse_kp",
        description="Разобрать коммерческое предложение: даты, поставщик, позиции.",
        parameters=_object({"extracted": EXTRACTED_SCHEMA}, ["extracted"]),
        handler=tool_parse_kp,
        returns=_object({"kp": KP_SCHEMA}, ["kp"]),
    )
)
_register(
    ToolSpec(
        name="parse_tz",
        description="Разобрать ТЗ: эталон номенклатуры из таблицы позиций.",
        parameters=_object({"extracted": EXTRACTED_SCHEMA}, ["extracted"]),
        handler=tool_parse_tz,
        returns=_object({"tz": TZ_SCHEMA}, ["tz"]),
    )
)
_register(
    ToolSpec(
        name="load_incoming",
        description="Прочитать папки incoming/requests, incoming/kp, incoming/tz.",
        parameters=_object(
            {"incoming": {"type": "string", "description": "Корень с подпапками requests, kp, tz."}},
            ["incoming"],
        ),
        handler=tool_load_incoming,
        returns=_object(
            {
                "requests": {"type": "array", "items": REQUEST_SCHEMA},
                "kps": {"type": "array", "items": KP_SCHEMA},
                "tzs": {"type": "array", "items": TZ_SCHEMA},
            },
            ["requests", "kps", "tzs"],
        ),
    )
)
_register(
    ToolSpec(
        name="structure_incoming",
        description=(
            "Разобрать комплект: парсер + Structure-агент. "
            "LLM-предложения принимаются только после regex/dates.py. Даты не додумываются."
        ),
        parameters=_object(
            {"incoming": {"type": "string", "description": "Корень с подпапками requests, kp, tz."}},
            ["incoming"],
        ),
        handler=tool_structure_incoming,
        returns=_object(
            {
                "requests": {"type": "array", "items": REQUEST_SCHEMA},
                "kps": {"type": "array", "items": KP_SCHEMA},
                "tzs": {"type": "array", "items": TZ_SCHEMA},
            },
            ["requests", "kps", "tzs"],
        ),
    )
)
_register(
    ToolSpec(
        name="structure_requests",
        description="Парсер запроса + подтверждённые предложения Structure-агента.",
        parameters=_object({"extracted": EXTRACTED_SCHEMA}, ["extracted"]),
        handler=tool_structure_requests,
        returns=_object(
            {"requests": {"type": "array", "items": REQUEST_SCHEMA}},
            ["requests"],
        ),
    )
)
_register(
    ToolSpec(
        name="structure_kp",
        description="Парсер КП + подтверждённые предложения. Дата регистрации — только из имени файла.",
        parameters=_object({"extracted": EXTRACTED_SCHEMA}, ["extracted"]),
        handler=tool_structure_kp,
        returns=_object({"kp": KP_SCHEMA}, ["kp"]),
    )
)
_register(
    ToolSpec(
        name="structure_tz",
        description="Парсер ТЗ + подтверждённые позиции, если таблица не прочитана.",
        parameters=_object({"extracted": EXTRACTED_SCHEMA}, ["extracted"]),
        handler=tool_structure_tz,
        returns=_object({"tz": TZ_SCHEMA}, ["tz"]),
    )
)
_register(
    ToolSpec(
        name="pair_requests_and_kps",
        description="Сопоставить запросы и КП по исх. №, затем по поставщику/email.",
        parameters=_object(
            {
                "requests": {"type": "array", "items": REQUEST_SCHEMA},
                "kps": {"type": "array", "items": KP_SCHEMA},
            },
            ["requests", "kps"],
        ),
        handler=tool_pair_requests_and_kps,
        returns=_object(
            {
                "pairs": {
                    "type": "array",
                    "items": _object(
                        {
                            "request": REQUEST_SCHEMA,
                            "kp": KP_SCHEMA,
                            "reason": {"type": "string"},
                            "score": {"type": "number"},
                        },
                        ["request", "kp"],
                    ),
                },
                "unmatched_requests": {"type": "array", "items": REQUEST_SCHEMA},
                "unmatched_kps": {"type": "array", "items": KP_SCHEMA},
            },
            ["pairs", "unmatched_requests", "unmatched_kps"],
        ),
    )
)
_register(
    ToolSpec(
        name="match_items",
        description="Сверить позиции ТЗ с КП. missing/extra — жёсткие расхождения.",
        parameters=_object(
            {
                "tz_items": {"type": "array", "items": ITEM_SCHEMA},
                "kp_items": {"type": "array", "items": ITEM_SCHEMA},
            },
            ["tz_items", "kp_items"],
        ),
        handler=tool_match_items,
        returns=_object({"mismatches": {"type": "array", "items": MISMATCH_SCHEMA}}, ["mismatches"]),
    )
)
_register(
    ToolSpec(
        name="match_nomenclature",
        description=(
            "Сверить позиции ТЗ↔КП по парам. Fingerprints запрещают склеить 300 и 150 циклов. "
            "LLM-предложение принимается только с артикулом/якорем в обеих строках."
        ),
        parameters=_object(
            {
                "tzs": {"type": "array", "items": TZ_SCHEMA},
                "pairs": {"type": "array"},
            },
            ["tzs", "pairs"],
        ),
        handler=tool_match_nomenclature,
        returns=_object({"nomenclature": {"type": "array"}}, ["nomenclature"]),
    )
)
_register(
    ToolSpec(
        name="audit",
        description="Полная сверка комплекта. Статусы считает rule-engine, не модель.",
        parameters=_object(
            {
                "requests": {"type": "array", "items": REQUEST_SCHEMA},
                "kps": {"type": "array", "items": KP_SCHEMA},
                "tzs": {"type": "array", "items": TZ_SCHEMA},
                "pairs": {"type": "array", "description": "Готовые пары из pair_requests_and_kps."},
                "nomenclature": {"type": "array", "description": "Результат match_nomenclature."},
            },
            ["requests", "kps", "tzs"],
        ),
        handler=tool_audit,
        returns=_object(
            {
                "results": {"type": "array", "items": PAIR_RESULT_SCHEMA},
                "summary": {"type": "object"},
            },
            ["results", "summary"],
        ),
    )
)
_register(
    ToolSpec(
        name="critique_pack",
        description=(
            "Critic по серой зоне score 0.45–0.70. Может понизить статус или отклонить сомнительную пару. "
            "Повысить до «Соответствует» нельзя."
        ),
        parameters=_object(
            {
                "results": {"type": "array", "items": PAIR_RESULT_SCHEMA},
                "pairs": {"type": "array"},
                "nomenclature": {"type": "array"},
            },
            ["results"],
        ),
        handler=tool_critique_pack,
        returns=_object(
            {
                "results": {"type": "array", "items": PAIR_RESULT_SCHEMA},
                "critic_log": {"type": "array", "items": {"type": "string"}},
            },
            ["results"],
        ),
    )
)
_register(
    ToolSpec(
        name="load_concepts",
        description="Загрузить OKF-концепции по точным id или tags, без векторного поиска.",
        parameters=_object(
            {
                "ids": {"type": ["array", "null"], "items": {"type": "string"}},
                "tags": {"type": ["array", "null"], "items": {"type": "string"}},
                "root": {"type": ["string", "null"]},
            },
            [],
        ),
        handler=tool_load_concepts,
        returns=_object({"concepts": {"type": "array"}}, ["concepts"]),
    )
)
_register(
    ToolSpec(
        name="calculate_market_statistics",
        description="Рассчитать среднее, стандартное отклонение и коэффициент вариации цен.",
        parameters=_object(
            {
                "values": {"type": "array", "items": {"type": "number"}},
                "threshold": {"type": "number"},
            },
            ["values"],
        ),
        handler=tool_calculate_market_statistics,
        returns=_object({"status": {"type": "string"}}, ["status"]),
    )
)
_register(
    ToolSpec(
        name="check_spec_constraint",
        description="Проверить конкретное значение КП относительно порога в ТЗ.",
        parameters=_object(
            {
                "tz_specs": {"type": "string"},
                "kp_specs": {"type": "string"},
            },
            ["tz_specs", "kp_specs"],
        ),
        handler=tool_check_spec_constraint,
        returns=_object({"status": {"type": "string"}}, ["status"]),
    )
)
_register(
    ToolSpec(
        name="comply_pack",
        description="Проверить неявные нормативные правила через OKF-концепции.",
        parameters=_object(
            {
                "results": {"type": "array", "items": PAIR_RESULT_SCHEMA},
                "kps": {"type": "array", "items": KP_SCHEMA},
                "root": {"type": ["string", "null"]},
            },
            ["results"],
        ),
        handler=tool_comply_pack,
        returns=_object(
            {
                "results": {"type": "array", "items": PAIR_RESULT_SCHEMA},
                "compliance_log": {"type": "array"},
            },
            ["results", "compliance_log"],
        ),
    )
)
_register(
    ToolSpec(
        name="audit_incoming",
        description="load_incoming + audit по папке комплекта. Тот же путь, что CLI.",
        parameters=_object(
            {"incoming": {"type": "string", "description": "Корень с подпапками requests, kp, tz."}},
            ["incoming"],
        ),
        handler=tool_audit_incoming,
        returns=_object(
            {
                "results": {"type": "array", "items": PAIR_RESULT_SCHEMA},
                "summary": {"type": "object"},
            },
            ["results", "summary"],
        ),
    )
)


def list_tools() -> list[dict[str, Any]]:
    return [spec.openai_tool() for spec in TOOLS.values()]


def invoke(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in TOOLS:
        known = ", ".join(sorted(TOOLS))
        raise KeyError(f"Unknown tool {name!r}. Known: {known}")
    spec = TOOLS[name]
    payload = arguments or {}
    if not isinstance(payload, dict):
        raise TypeError("Tool arguments must be an object")
    missing = [key for key in spec.parameters.get("required", []) if key not in payload]
    if missing:
        raise ValueError(f"Tool {name} missing required fields: {', '.join(missing)}")
    allowed = set(spec.parameters.get("properties", {}))
    filtered = {key: value for key, value in payload.items() if key in allowed}
    return spec.handler(**filtered)
