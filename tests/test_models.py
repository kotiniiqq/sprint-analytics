from datetime import datetime, timezone

from sprint_analytics.models import Issue, StatusChange

UTC = timezone.utc


def t(day, hour=10):
    return datetime(2026, 9, day, hour, tzinfo=UTC)


def make_issue(history):
    return Issue(key="A-1", summary="x", type="story", story_points=3, assignee="ann",
                 has_acceptance_criteria=True, added_after_start=False,
                 history=[StatusChange(s, at) for s, at in history])


def test_status_at_returns_last_change_before_time():
    issue = make_issue([("In Progress", t(8)), ("Done", t(10))])
    assert issue.status_at(t(7)) == "To Do"
    assert issue.status_at(t(9)) == "In Progress"
    assert issue.status_at(t(11)) == "Done"


def test_history_is_sorted_on_creation():
    issue = make_issue([("Done", t(10)), ("In Progress", t(8))])
    assert [c.status for c in issue.history] == ["In Progress", "Done"]
