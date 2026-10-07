import pytest

from sprint_analytics.guard import check
from sprint_analytics.llm import LLMError, LLMResult
from sprint_analytics.report import build_facts, deterministic_report, generate_report
from sprint_analytics.sources import SyntheticSource


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SA_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)


@pytest.fixture(scope="module")
def facts():
    sprints = SyntheticSource().sprints("beta")
    return build_facts(sprints, sprints[-1])


def fake_llm(text):
    def call(messages, model=None):
        return LLMResult(text=text, model=model or "fake", prompt_tokens=1, completion_tokens=1,
                         cost_usd=0.0, latency_ms=1)
    return call


def test_deterministic_report_passes_its_own_guard(facts):
    text = deterministic_report(facts)
    assert check(text, facts).ok, check(text, facts).invented
    assert f"{facts['completed_points']:g}" in text
    assert facts["carry_over"][0] in text


@pytest.mark.parametrize("team", ["alpha", "beta", "gamma"])
def test_deterministic_report_passes_guard_for_every_sprint(team):
    sprints = SyntheticSource().sprints(team)
    for s in sprints:
        f = build_facts(sprints, s)
        assert check(deterministic_report(f), f).ok


def test_good_llm_text_is_used(facts):
    text = f"{facts['sprint']} delivered {facts['completed_points']} points."
    result = generate_report(facts, llm=fake_llm(text))
    assert result.source == "llm" and result.text == text


def test_invented_number_falls_back(facts):
    result = generate_report(facts, llm=fake_llm("The team delivered 999 points."))
    assert (result.source, result.reason) == ("fallback", "guard")
    assert result.guard.invented == ["999"]


def test_llm_error_falls_back(facts):
    def broken(messages, model=None):
        raise LLMError("timeout")
    result = generate_report(facts, llm=broken)
    assert (result.source, result.reason) == ("fallback", "llm_error")


def test_no_key_falls_back(facts, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = generate_report(facts)
    assert (result.source, result.reason) == ("fallback", "no_key")
