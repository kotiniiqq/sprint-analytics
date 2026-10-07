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


def test_more_workflow_names_are_understood():
    assert [normalise_status(s) for s in ["QA", "Testing", "In Development", "Blocked", "Released"]] == \
        ["In Review", "In Review", "In Progress", "In Progress", "Done"]
    assert normalise_status("Ready to ship", {"Ready to ship": "In Review"}) == "In Review"


def test_active_sprint_is_measured_up_to_now():
    from datetime import datetime, timezone

    board = json.loads((FIX / "jira_board_sprints.json").read_text())
    board["values"][0]["state"] = "active"
    del board["values"][0]["completeDate"]

    def handler(request):
        if request.url.path.endswith("/board/7/sprint"):
            return httpx.Response(200, json=board)
        return recorded(request)

    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)  # mid-sprint
    src = JiraSource("https://x", "e", "t", {"platform": 7}, now=now,
                     client=httpx.Client(transport=httpx.MockTransport(handler)))
    sprint = src.sprints("platform")[0]
    assert sprint.end == now
    stuck = sprint_metrics(sprint, stuck_threshold_hours=0)["stuck"]
    assert {s["key"]: s["hours"] for s in stuck}["PLAT-2"] == 1.0  # Thu 11:00 -> 12:00, not to the planned end


def test_issue_pages_are_followed():
    pages = {0: [f"P-{i}" for i in range(50)], 50: [f"P-{i}" for i in range(50, 100)], 100: ["P-100"]}

    def handler(request):
        if request.url.path.endswith("/board/7/sprint"):
            return httpx.Response(200, json=json.loads((FIX / "jira_board_sprints.json").read_text()))
        start = int(request.url.params["startAt"])
        issues = [{"key": k, "fields": {"summary": k}, "changelog": {"histories": []}} for k in pages[start]]
        return httpx.Response(200, json={"startAt": start, "total": 101, "issues": issues})

    src = JiraSource("https://x", "e", "t", {"platform": 7},
                     client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(src.sprints("platform")[0].issues) == 101


def test_truncated_changelog_is_fetched_in_full():
    def handler(request):
        path = request.url.path
        if path.endswith("/board/7/sprint"):
            return httpx.Response(200, json=json.loads((FIX / "jira_board_sprints.json").read_text()))
        if path.endswith("/issue/PLAT-9/changelog"):
            return httpx.Response(200, json={"isLast": True, "values": [
                {"created": "2026-09-07T10:00:00.000+0000", "items": [{"field": "status", "toString": "In Progress"}]},
                {"created": "2026-09-08T10:00:00.000+0000", "items": [{"field": "status", "toString": "Done"}]}]})
        return httpx.Response(200, json={"total": 1, "issues": [
            {"key": "PLAT-9", "fields": {"summary": "x", "customfield_10016": 3},
             "changelog": {"total": 2, "histories": []}}]})

    src = JiraSource("https://x", "e", "t", {"platform": 7},
                     client=httpx.Client(transport=httpx.MockTransport(handler)))
    issue = src.sprints("platform")[0].issues[0]
    assert [c.status for c in issue.history] == ["In Progress", "Done"]


def test_partial_config_warns_and_falls_back(monkeypatch, capsys):
    for k in ("JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_BOARDS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("JIRA_BASE_URL", "https://x.atlassian.net")
    assert from_env() is None
    assert "partly configured" in capsys.readouterr().err
