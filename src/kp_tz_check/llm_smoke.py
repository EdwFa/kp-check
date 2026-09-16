"""Минимальный smoke-test private LLM без документов и персональных данных."""

from __future__ import annotations

import argparse
import json

from kp_tz_check.llm import LLMConfig, PrivateLLMClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test OpenAI-compatible local LLM")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    config = LLMConfig.from_env()
    if args.base_url:
        config = LLMConfig(
            enabled=True,
            base_url=args.base_url.rstrip("/"),
            api_key=config.api_key,
            model=args.model or config.model,
            timeout=config.timeout,
        )
    client = PrivateLLMClient(config)
    if not client.available:
        print("LLM недоступен: задайте KP_LLM_ENABLED=true, BASE_URL и MODEL")
        return 2
    result = client.invoke_json(
        operation="smoke.test",
        system="Верни JSON ровно с полем ok=true.",
        user="Проверка локального endpoint. Документов нет.",
        schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    )
    if result.get("ok") is not True:
        print(json.dumps(result, ensure_ascii=False))
        return 1
    print(f"PASS: model={config.model}, endpoint={config.base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
