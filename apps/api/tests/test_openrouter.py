"""OpenRouter protocol/contract tests; no real external inference."""

import json
import httpx
import pytest
from app.config import Settings, settings
from app.llm import (
    OpenRouterProvider,
    ProviderError,
    Wording,
    provider,
    provider_configured,
    strict_json_schema,
)
from app.models import Interpretation, State, Decision
from app.retrieval import CORPUS


@pytest.fixture
def configured(monkeypatch):
    cfg = settings()
    for name, value in dict(
        provider="openrouter",
        allow_external_ai=True,
        openrouter_api_key="test-only-placeholder",
        openrouter_model="google/gemini-2.5-flash",
        approved_external_corpus_version=CORPUS,
    ).items():
        monkeypatch.setattr(cfg, name, value)
    return cfg


def completion(content):
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


def test_env_settings(tmp_path, monkeypatch):
    for name in ("PROVIDER", "OPENROUTER_API_KEY", "OPENROUTER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "PROVIDER=openrouter\nOPENROUTER_API_KEY=test-only-placeholder\nOPENROUTER_MODEL=test/model\n"
    )
    cfg = Settings(_env_file=path)
    assert cfg.provider == "openrouter" and cfg.openrouter_model == "test/model"
    assert cfg.openrouter_api_key == "test-only-placeholder"


@pytest.mark.parametrize(
    "field,value",
    [
        ("allow_external_ai", False),
        ("openrouter_api_key", ""),
        ("openrouter_model", ""),
        ("approved_external_corpus_version", "wrong-corpus"),
    ],
)
def test_gates_block_before_database_or_network(configured, monkeypatch, field, value):
    monkeypatch.setattr(configured, field, value)
    assert not provider_configured()
    with pytest.raises(ProviderError, match="not authorized/configured"):
        OpenRouterProvider().call("synthetic", Interpretation)


def test_strict_schema_preserves_nullable_unknowns_and_requires_nested_fields():
    schema = strict_json_schema(Interpretation)
    assert set(schema["required"]) == set(schema["properties"])
    details = schema["$defs"]["Details"]
    assert set(details["required"]) == set(details["properties"])
    assert details["additionalProperties"] is False
    assert {"type": "null"} in details["properties"]["os"]["anyOf"]
    assert "default" not in json.dumps(schema)
    # Transport normalization does not mutate local Pydantic defaults.
    assert Interpretation().details.os is None


def test_protocol_redaction_and_provider_selection(configured, monkeypatch):
    monkeypatch.setattr("app.llm.reserve_external_call", lambda *args: None)
    captured = []

    def transport(url, **kwargs):
        captured.append((url, kwargs))
        return httpx.Response(
            200,
            json=completion(Interpretation(category="email").model_dump_json()),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.llm.httpx.post", transport)
    adapter = provider()
    assert isinstance(adapter, OpenRouterProvider) and provider_configured()
    assert adapter.name == "openrouter/google/gemini-2.5-flash"
    result = adapter.interpret("My email failed jane@example.com password=secret123", State())
    assert result.category == "email"
    url, request = captured[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-only-placeholder"
    assert request["timeout"] == 8
    body = request["json"]
    assert "jane@example.com" not in json.dumps(body) and "secret123" not in json.dumps(body)
    assert body["model"] == configured.openrouter_model and body["max_tokens"] == 768
    assert body["provider"] == dict(require_parameters=True, allow_fallbacks=False, data_collection="deny")
    assert body["response_format"]["json_schema"]["strict"]
    assert body["stream"] is False and len(captured) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"error": {"message": "test-only-placeholder"}},
        completion("not JSON"),
        completion('{"details":{"os":"invented"}}'),
        completion(None),
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"refusal": "refused", "content": "{}"}}]},
    ],
)
def test_invalid_or_incomplete_responses_fail_safely(configured, monkeypatch, body):
    monkeypatch.setattr("app.llm.reserve_external_call", lambda *args: None)
    monkeypatch.setattr(
        "app.llm.httpx.post",
        lambda url, **kw: httpx.Response(200, json=body, request=httpx.Request("POST", url)),
    )
    with pytest.raises(ProviderError) as error:
        OpenRouterProvider().call("synthetic", Interpretation)
    assert str(error.value) == "Provider request or schema validation failed"
    assert error.value.__suppress_context__


@pytest.mark.parametrize("failure", ["timeout", "401", "429", "503"])
def test_transport_errors_do_not_retry_or_expose_remote_details(configured, monkeypatch, failure):
    monkeypatch.setattr("app.llm.reserve_external_call", lambda *args: None)
    calls = []

    def transport(url, **kwargs):
        calls.append(url)
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive remote error")
        return httpx.Response(int(failure), text="sensitive remote error", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.llm.httpx.post", transport)
    with pytest.raises(ProviderError, match="^Provider request or schema validation failed$"):
        OpenRouterProvider().call("synthetic", Interpretation)
    assert len(calls) == 1


def test_openrouter_wording_uses_shared_grounding_contract(configured, monkeypatch):
    monkeypatch.setattr(
        OpenRouterProvider, "call", lambda *args: Wording(question="Send me your password", step_indexes=[])
    )
    assert (
        OpenRouterProvider().word(Decision(action="ASK", rule="test", field="os"), None)
        == "Which operating system are you using?"
    )
