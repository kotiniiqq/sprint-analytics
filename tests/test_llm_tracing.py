import json

import httpx
import pytest

from sprint_analytics import tracing
from sprint_analytics.llm import LLMError, complete


def client_returning(status, body):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)))


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("SA_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    yield
    tracing.set_http_client(None)


def test_complete_parses_text_usage_and_cost():
    body = {"model": "m", "choices": [{"message": {"content": " Report "}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40, "cost": 0.0012}}
    result = complete([{"role": "user", "content": "hi"}], model="m", client=client_returning(200, body))
    assert (result.text, result.prompt_tokens, result.completion_tokens, result.cost_usd) == \
        ("Report", 120, 40, 0.0012)


def test_http_error_raises_llm_error():
    with pytest.raises(LLMError):
        complete([], client=client_returning(500, {"error": "boom"}))


def test_empty_choices_raise_llm_error():
    with pytest.raises(LLMError):
        complete([], client=client_returning(200, {"choices": []}))


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(LLMError):
        complete([])


def test_trace_writes_a_jsonl_line(tmp_path):
    event = tracing.trace("report", model="m", prompt_tokens=10)
    files = list((tmp_path / "traces").glob("*.jsonl"))
    line = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert line["id"] == event["id"] and line["prompt_tokens"] == 10


def test_langfuse_failure_is_swallowed(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    tracing.set_http_client(client_returning(500, {}))
    tracing.trace("report", model="m")
    assert "Langfuse ingestion returned 500" in capsys.readouterr().err
    assert list((tmp_path / "traces").glob("*.jsonl"))  # the local trace is still written


def test_langfuse_receives_trace_and_generation(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(207, json={"successes": [], "errors": []})

    tracing.set_http_client(httpx.Client(transport=httpx.MockTransport(handler)))
    tracing.trace("report", model="m", prompt_tokens=5, completion_tokens=3)
    assert [e["type"] for e in seen[0]["batch"]] == ["trace-create", "generation-create"]
