"""Адаптеры private LLM к существующим proposer-протоколам.

Адаптеры не устанавливаются автоматически: приложение должно явно передать их
через существующие ContextVar. Поэтому стандартный проход остаётся без LLM.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any

from kp_tz_check.critic import (
    CriticProposer,
    reset_critic_proposer,
    set_critic_proposer,
)
from kp_tz_check.llm import PrivateLLMClient
from kp_tz_check.nomenclature import (
    NomenclatureProposer,
    reset_nomenclature_proposer,
    set_nomenclature_proposer,
)
from kp_tz_check.structure import (
    StructureProposer,
    reset_proposer,
    set_proposer,
)
from kp_tz_check.tracing import JsonlTracer


def _list(result: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = result.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"LLM-контракт должен содержать список объектов: {key}")
    return value


@contextmanager
def private_llm_context(client: PrivateLLMClient | None = None):
    """Временно включить proposer-адаптеры для одного прогона."""

    client = client or PrivateLLMClient()
    if not client.available:
        yield False
        return
    if client.trace is None and os.getenv("KP_LLM_TRACE"):
        client.trace = JsonlTracer(os.environ["KP_LLM_TRACE"])
    structure_token = set_proposer(PrivateStructureProposer(client))
    nomenclature_token = set_nomenclature_proposer(PrivateNomenclatureProposer(client))
    critic_token = set_critic_proposer(PrivateCriticProposer(client))
    try:
        yield True
    finally:
        reset_proposer(structure_token)
        reset_nomenclature_proposer(nomenclature_token)
        reset_critic_proposer(critic_token)


class PrivateStructureProposer(StructureProposer):
    def __init__(self, client: PrivateLLMClient):
        self.client = client

    def propose_requests(self, *, text: str, tables: list, baseline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self.client.invoke_json(
            operation="structure.requests",
            system="Предложи структуру исходящих писем. Не выдумывай даты. Верни JSON.",
            user=f"BASELINE={baseline}\nTEXT={text}\nTABLES={tables}",
        )
        return _list(result, "requests")

    def propose_kp(self, *, text: str, filename: str, tables: list, baseline: dict[str, Any]) -> dict[str, Any]:
        result = self.client.invoke_json(
            operation="structure.kp",
            system="Предложи структуру КП. Дату регистрации бери только из имени файла. Верни JSON.",
            user=f"FILENAME={filename}\nBASELINE={baseline}\nTEXT={text}\nTABLES={tables}",
        )
        return result

    def propose_tz(self, *, text: str, tables: list, baseline: dict[str, Any]) -> dict[str, Any]:
        return self.client.invoke_json(
            operation="structure.tz",
            system="Предложи позиции ТЗ только из текста и таблиц. Верни JSON.",
            user=f"BASELINE={baseline}\nTEXT={text}\nTABLES={tables}",
        )


class PrivateNomenclatureProposer(NomenclatureProposer):
    def __init__(self, client: PrivateLLMClient):
        self.client = client

    def propose_item_links(
        self,
        *,
        tz_items: list[dict[str, Any]],
        kp_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = self.client.invoke_json(
            operation="nomenclature.links",
            system=(
                "Предложи связи позиций ТЗ и КП. Не связывай конфликтующие циклы/Гб. "
                "Верни JSON-массив ссылок."
            ),
            user=f"TZ={tz_items}\nKP={kp_items}",
        )
        return _list(result, "links")


class PrivateCriticProposer(CriticProposer):
    def __init__(self, client: PrivateLLMClient):
        self.client = client

    def critique(
        self,
        *,
        gray_pairs: list[dict[str, Any]],
        gray_links: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = self.client.invoke_json(
            operation="critic.review",
            system=(
                "Проверь только серые пары и связи. Разрешены reject_pair, reject_item, "
                "downgrade. upgrade запрещён. Верни JSON-массив действий."
            ),
            user=f"PAIRS={gray_pairs}\nLINKS={gray_links}",
        )
        return _list(result, "actions")
