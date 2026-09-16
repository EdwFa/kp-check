import json

import pytest

from kp_tz_check.llm import LLMConfig, PrivateLLMClient
from kp_tz_check.llm_proposers import PrivateCriticProposer
from kp_tz_check.tracing import JsonlTracer


def test_private_llm_is_disabled_by_default():
    client = PrivateLLMClient(LLMConfig())
    assert not client.available
    with pytest.raises(RuntimeError):
        client.invoke_json(system="x", user="y", operation="test")


def test_llm_config_reads_provider_key_from_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "KP_LLM_ENABLED=true\nTOGETHER_API_KEY=together-secret\nTOGETHER_MODEL=test/model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KP_LLM_ENABLED", raising=False)
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    monkeypatch.delenv("TOGETHER_MODEL", raising=False)
    config = LLMConfig.from_env("together")
    assert config.enabled
    assert config.api_key == "together-secret"
    assert config.model == "test/model"


def test_private_llm_requires_json_object_and_traces_metadata(tmp_path):
    events = []

    def transport(url, payload, headers, timeout):
        assert url.endswith("/v1/chat/completions")
        assert payload["temperature"] == 0
        return {"choices": [{"message": {"content": '{"actions": []}'}}]}

    client = PrivateLLMClient(
        LLMConfig(enabled=True, base_url="http://private", model="local-model"),
        transport=transport,
        trace=events.append,
    )
    result = PrivateCriticProposer(client).critique(gray_pairs=[], gray_links=[])
    assert result == []
    assert events == [
        {
            "operation": "critic.review",
            "model": "local-model",
            "request_chars": events[0]["request_chars"],
            "response_keys": ["actions"],
        }
    ]


def test_private_llm_uses_openai_json_schema_when_schema_is_given():
    payloads = []

    def transport(url, payload, headers, timeout):
        payloads.append(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    client = PrivateLLMClient(
        LLMConfig(enabled=True, base_url="http://private", model="local-model"),
        transport=transport,
    )
    client.invoke_json(
        system="x",
        user="y",
        operation="test.schema",
        schema={"type": "object", "properties": {}},
    )
    assert payloads[0]["response_format"]["type"] == "json_schema"
    assert payloads[0]["response_format"]["json_schema"]["schema"]["type"] == "object"


def test_jsonl_tracer_does_not_need_raw_document_text(tmp_path):
    path = tmp_path / "trace.jsonl"
    JsonlTracer(path)({"operation": "test", "request_chars": 12})
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["operation"] == "test"
    assert "document text" not in record
