"""Реестры выключены, пока нет клиента. Обычный прогон сеть не вызывает."""

from __future__ import annotations

import os
from typing import Protocol


FLAGS = (
    "KP_REGISTRY_EGRUL",
    "KP_REGISTRY_RNP",
    "KP_REGISTRY_ECG",
    "KP_REGISTRY_MARKET",
)


class RegistryConfigError(RuntimeError):
    """Флаг реестра включён, а клиента для него нет."""


class RegistryLookup(Protocol):
    def lookup(self, kind: str, key: str) -> dict:
        """Вернуть status, value, source_url и checked_at."""


class DisabledRegistry:
    def lookup(self, kind: str, key: str) -> dict:
        return {
            "status": "not_checked",
            "value": None,
            "source_url": None,
            "checked_at": None,
            "kind": kind,
            "key": key,
        }


def flag_state() -> dict[str, bool]:
    return {name: _enabled(os.environ.get(name)) for name in FLAGS}


def build_registry(client: object | None = None) -> RegistryLookup:
    enabled = [name for name, on in flag_state().items() if on]
    if enabled and client is None:
        raise RegistryConfigError(
            "Включён реестр без клиента: " + ", ".join(enabled)
        )
    if client is not None and not enabled:
        return DisabledRegistry()
    if client is not None:
        return _ClientRegistry(client)
    return DisabledRegistry()


class _ClientRegistry:
    """Заготовка клиента. Сейчас ни один флаг не должен доходить сюда без явного клиента в тесте."""

    def __init__(self, client: object) -> None:
        self.client = client

    def lookup(self, kind: str, key: str) -> dict:
        response = self.client.get(kind, key)  # type: ignore[attr-defined]
        return {
            "status": response.get("status") or "not_checked",
            "value": response.get("value"),
            "source_url": response.get("source_url"),
            "checked_at": response.get("checked_at"),
            "kind": kind,
            "key": key,
        }


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}
