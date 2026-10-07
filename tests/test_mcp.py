import json

import anyio
import pytest
from mcp.client import Client

from sprint_analytics.mcp_server import build_server
from sprint_analytics.sources import SyntheticSource


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SA_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)


def run(coro_fn):
    return anyio.run(coro_fn)


def payload(result):
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


def call(name, args):
    async def go():
        async with Client(build_server(SyntheticSource())) as client:
            return await client.call_tool(name, args)
    return run(go)


def test_server_exposes_five_tools():
    async def go():
        async with Client(build_server(SyntheticSource())) as client:
            return await client.list_tools()
    tools = run(go)
    names = sorted(t.name for t in getattr(tools, "tools", tools))
    assert names == ["compare_sprints", "find_stuck_issues", "get_sprint_metrics",
                     "list_sprints", "sprint_report"]


def test_get_sprint_metrics_returns_computed_numbers():
    result = call("get_sprint_metrics", {"team": "beta", "sprint": "6"})
    assert not result.is_error
    data = payload(result)
    assert data["sprint"] == "Beta Sprint 6" and data["completed_points"] == 30


def test_unknown_team_is_a_readable_error():
    result = call("get_sprint_metrics", {"team": "delta"})
    assert result.is_error
    assert "alpha, beta, gamma" in result.content[0].text


def test_sprint_report_without_key_uses_the_template():
    data = payload(call("sprint_report", {"team": "gamma"}))
    assert data["source"] == "fallback" and data["fallback_reason"] == "no_key"
    assert "GAMMA-60" in data["report"]


def test_tool_calls_are_traced(tmp_path):
    call("list_sprints", {"team": "alpha"})
    lines = list((tmp_path / "traces").glob("*.jsonl"))[0].read_text(encoding="utf-8")
    assert "mcp.list_sprints" in lines
