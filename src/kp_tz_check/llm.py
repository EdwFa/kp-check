"""Опциональный private LLM-клиент с JSON-only контрактом.

Клиент выключен по умолчанию. Он совместим с внутренними OpenAI-compatible
endpoint'ами, но не требует SDK и не вызывается rule-engine напрямую.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen


Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: float = 30.0

    @classmethod
    def from_env(cls, provider: str | None = None) -> "LLMConfig":
        _load_dotenv()
        provider_key = {
            "unsloth": "UNSLOTH_API_KEY",
            "ollama": "OLLAMA_API_KEY",
            "together": "TOGETHER_API_KEY",
        }.get((provider or "").lower())
        model_key = {
            "unsloth": "UNSLOTH_MODEL",
            "ollama": "OLLAMA_MODEL",
            "together": "TOGETHER_MODEL",
        }.get((provider or "").lower())
        return cls(
            enabled=os.getenv("KP_LLM_ENABLED", "").lower() in {"1", "true", "yes"},
            base_url=os.getenv("KP_LLM_BASE_URL", "").rstrip("/"),
            api_key=os.getenv(provider_key, "") if provider_key else os.getenv("KP_LLM_API_KEY", ""),
            model=os.getenv(model_key, "") if model_key else os.getenv("KP_LLM_MODEL", ""),
            timeout=float(os.getenv("KP_LLM_TIMEOUT", "30")),
        )


def _load_dotenv() -> None:
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("'\"")
            os.environ.setdefault(key, value)
        break


def _http_transport(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class PrivateLLMClient:
    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        transport: Transport | None = None,
        trace: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.config = config or LLMConfig.from_env()
        self.transport = transport or _http_transport
        self.trace = trace

    @property
    def available(self) -> bool:
        return bool(
            self.config.enabled
            and self.config.base_url
            and self.config.model
        )

    def invoke_json(
        self,
        *,
        system: str,
        user: str,
        operation: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("Private LLM выключен или не сконфигурирован")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": (
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": operation.replace(".", "_"),
                        "schema": schema,
                    },
                }
                if schema is not None
                else {"type": "json_object"}
            ),
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        response = self.transport(
            f"{self.config.base_url}/v1/chat/completions",
            payload,
            headers,
            self.config.timeout,
        )
        content = response["choices"][0]["message"]["content"]
        result = json.loads(content) if isinstance(content, str) else content
        if not isinstance(result, dict):
            raise ValueError("Private LLM вернул JSON не-объект")
        if self.trace:
            self.trace(
                {
                    "operation": operation,
                    "model": self.config.model,
                    "request_chars": len(system) + len(user),
                    "response_keys": sorted(result),
                }
            )
        return result
