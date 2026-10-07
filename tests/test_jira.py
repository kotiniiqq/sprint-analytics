import json
from pathlib import Path

import httpx
import pytest

from sprint_analytics.jira import JiraSource, from_env, normalise_status
from sprint_analytics.metrics import sprint_metrics
from sprint_analytics.sources import SourceError

FIX = Path(__file__).parent / "fixtures"


def recorded(request):
    if request.url.path.endswith("/board/7/sprint"):
        return httpx.Response(200, json=json.loads((FIX / "jira_board_sprints.json").read_text()))
    if request.url.path.endswith("/sprint/41/issue"):
        assert request.url.params["expand"] == "changelog"
        return httpx.Response(200, json=json.loads((FIX / "jira_sprint_issues.json").read_text()))
    return httpx.Response(404)


def source(handler=recorded):
    return JiraSource("https://example.atlassian.net", "me@example.com", "token", {"platform": 7},
                      client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_maps_sprints_and_skips_ones_without_dates():
    sprints = source().sprints("platform")
    assert [s.name for s in sprints] == ["Platform Sprint 41"]
    assert sprints[0].end.hour == 17  # completeDate wins over endDate


def test_maps_issues_history_points_and_flags():
    issues = {i.key: i for i in source().sprints("platform")[0].issues}
    assert [c.status for c in issues["PLAT-1"].history] == ["In Progress", "In Review", "Done"]
    assert issues["PLAT-1"].story_points == 5.0 and issues["PLAT-1"].has_acceptance_criteria
    assert issues["PLAT-2"].story_points is None and issues["PLAT-2"].assignee is None
    assert issues["PLAT-3"].added_after_start and issues["PLAT-3"].history[-1].status == "Done"


def test_metrics_work_on_jira_data():
    m = sprint_metrics(source().sprints("platform")[0])
    assert m["completed_points"] == 7 and m["added_points"] == 2 and m["carry_over"] == ["PLAT-2"]


def test_401_is_a_readable_error():
    with pytest.raises(SourceError, match="401"):
        source(lambda r: httpx.Response(401)).sprints("platform")


def test_unknown_team():
    with pytest.raises(SourceError, match="platform"):
        source().sprints("alpha")


def test_status_names_are_normalised():
    assert [normalise_status(s) for s in ["Code Review", "In progress", "Closed", "Backlog"]] == \
        ["In Review", "In Progress", "Done", "To Do"]


def test_from_env_requires_all_variables(monkeypatch):
    for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_BOARDS"):
        monkeypatch.delenv(k, raising=False)
    assert from_env() is None
    monkeypatch.setenv("JIRA_BASE_URL", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "a@b.c")
    monkeypatch.setenv("JIRA_API_TOKEN", "t")
    monkeypatch.setenv("JIRA_BOARDS", "alpha=12, beta=15")
    assert from_env().boards == {"alpha": 12, "beta": 15}
    monkeypatch.setenv("JIRA_BOARDS", "alpha")
    with pytest.raises(SourceError):
        from_env()
