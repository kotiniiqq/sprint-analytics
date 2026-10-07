import json

import pytest

from sprint_analytics.cli import main


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SA_TRACE_DIR", str(tmp_path))
    for k in ("OPENROUTER_API_KEY", "JIRA_BASE_URL", "LANGFUSE_PUBLIC_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_metrics_json(capsys):
    assert main(["metrics", "--team", "beta", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["completed_points"] == 30


def test_metrics_text(capsys):
    assert main(["metrics", "--team", "gamma", "--sprint", "6"]) == 0
    out = capsys.readouterr().out
    assert "Gamma Sprint 6" in out and "GAMMA-62" in out


def test_unknown_team_exits_2_with_a_message(capsys):
    assert main(["metrics", "--team", "delta"]) == 2
    assert "Valid teams: alpha, beta, gamma" in capsys.readouterr().err


def test_unknown_sprint_exits_2(capsys):
    assert main(["stuck", "--team", "alpha", "--sprint", "99"]) == 2
    assert "Valid sprint ids" in capsys.readouterr().err


def test_report_without_key_uses_template(capsys):
    assert main(["report", "--team", "gamma"]) == 0
    assert "template, reason: no_key" in capsys.readouterr().out


def test_compare_rejects_zero_window(capsys):
    assert main(["compare", "--team", "alpha", "--last", "0"]) == 2


def test_report_suite_without_key_is_a_clear_error(capsys):
    assert main(["eval", "--suite", "report"]) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
