from datetime import datetime, timezone

import pytest

from sprint_analytics.metrics import compare_sprints, percentile, sprint_metrics
from sprint_analytics.models import Issue, Sprint, StatusChange
from sprint_analytics.sources import SyntheticSource

UTC = timezone.utc
START = datetime(2026, 9, 7, 9, tzinfo=UTC)   # Monday
END = datetime(2026, 9, 18, 18, tzinfo=UTC)   # second Friday


def at(day, hour=10):
    return datetime(2026, 9, day, hour, tzinfo=UTC)


def issue(key, points=3, history=(), added=False, assignee="ann", criteria=True):
    return Issue(key=key, summary=key, type="story", story_points=points, assignee=assignee,
                 has_acceptance_criteria=criteria, added_after_start=added,
                 history=[StatusChange(s, t) for s, t in history])


def sprint(*issues, sprint_id=1):
    return Sprint(id=sprint_id, team="t", name=f"T Sprint {sprint_id}", start=START, end=END,
                  issues=list(issues))


DONE_FAST = [("In Progress", at(7, 10)), ("In Review", at(7, 14)), ("Done", at(8, 10))]


def test_velocity_commitment_and_added_scope():
    m = sprint_metrics(sprint(
        issue("T-1", 5, DONE_FAST),
        issue("T-2", 3, [("In Progress", at(8))]),
        issue("T-3", 2, DONE_FAST, added=True),
    ))
    assert m["committed_points"] == 8
    assert m["added_points"] == 2
    assert m["completed_points"] == 7
    assert m["completion_rate"] == 0.7
    assert m["carry_over"] == ["T-2"]
    assert m["issues_total"] == 3 and m["issues_done"] == 2


def test_cycle_time_and_percentiles():
    m = sprint_metrics(sprint(
        issue("T-1", 1, DONE_FAST),                                            # 9h
        issue("T-2", 1, [("In Progress", at(7, 10)), ("Done", at(7, 12))]),      # 2h
        issue("T-3", 1, [("In Progress", at(7, 10)), ("Done", at(9, 10))]),      # 18h
    ))
    assert m["cycle_time_hours"] == {"T-1": 9.0, "T-2": 2.0, "T-3": 18.0}
    assert m["cycle_time_p50"] == 9.0
    assert m["cycle_time_p85"] == 18.0


def test_done_without_in_progress():
    m = sprint_metrics(sprint(issue("T-1", 5, [("Done", at(8))])))
    assert m["completed_points"] == 5
    assert m["cycle_time_hours"] == {}
    assert m["cycle_time_p50"] is None


def test_time_in_status_is_clipped_to_the_sprint():
    early = datetime(2026, 9, 4, 10, tzinfo=UTC)  # Friday before the sprint
    m = sprint_metrics(sprint(issue("T-1", 1, [("In Progress", early), ("Done", at(7, 12))])))
    assert m["time_in_status_hours"]["In Progress"] == 3.0  # Mon 09:00–12:00 only
    assert "Done" not in m["time_in_status_hours"]  # time after Done is not work time


def test_reopened_issue_is_reported():
    m = sprint_metrics(sprint(issue("T-1", 3, [
        ("In Progress", at(7)), ("Done", at(8)), ("In Progress", at(9)), ("Done", at(10)),
    ])))
    assert m["reopened"] == ["T-1"]
    assert m["completed_points"] == 3


def test_hygiene_score_and_missing_fields():
    m = sprint_metrics(sprint(
        issue("T-1", 3, DONE_FAST),
        issue("T-2", None, DONE_FAST, assignee=None, criteria=False),
    ))
    assert m["hygiene_score"] == 50.0
    assert m["hygiene_issues"] == {"T-2": ["story points", "assignee", "acceptance criteria"]}


def test_stuck_threshold():
    m = sprint_metrics(sprint(
        issue("T-1", 3, [("In Progress", at(10)), ("In Review", at(14, 10))]),  # In Review from Mon 14 10:00 to the sprint end
        issue("T-2", 3, [("In Progress", at(18, 15))]),                         # 3h, not stuck
    ))
    assert m["stuck"] == [{"key": "T-1", "status": "In Review", "hours": 44.0}]


def test_history_after_the_sprint_end_is_ignored():
    later = datetime(2026, 9, 29, 10, tzinfo=UTC)  # in the next sprint
    m = sprint_metrics(sprint(issue("T-1", 3, DONE_FAST + [("In Progress", at(25)), ("Done", later)])))
    assert m["cycle_time_hours"] == {"T-1": 9.0}  # not stretched to the second Done
    assert m["reopened"] == []                     # reopened later, not in this sprint


def test_empty_and_unestimated_sprint():
    empty = sprint_metrics(sprint())
    assert empty["completed_points"] == 0 and empty["completion_rate"] == 0.0
    assert empty["hygiene_score"] == 100.0 and empty["cycle_time_p85"] is None
    none_estimated = sprint_metrics(sprint(issue("T-1", None, DONE_FAST)))
    assert none_estimated["completion_rate"] == 0.0
    assert none_estimated["issues_done"] == 1


def test_percentile_nearest_rank():
    assert percentile([], 50) is None
    assert percentile([4.0], 85) == 4.0
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 85) == 9


def test_compare_sprints_trend():
    s1 = sprint(issue("T-1", 10, DONE_FAST), sprint_id=1)
    s2 = sprint(issue("T-2", 10, DONE_FAST), sprint_id=2)
    s3 = sprint(issue("T-3", 4, DONE_FAST), issue("T-4", 6, [("In Progress", at(8))]), sprint_id=3)
    c = compare_sprints([s1, s2, s3], last_n=3)
    assert c["velocity"] == [10, 10, 4]
    assert c["baseline_velocity"] == 10.0
    assert c["trend_pct"] == -60.0  # last vs the average of the earlier sprints
    assert c["completion_rates"] == [1.0, 1.0, 0.4]


# --- planted scenarios in the bundled synthetic data ---

@pytest.fixture(scope="module")
def data():
    return SyntheticSource()


def test_beta_carry_over_grows(data):
    carry = [len(sprint_metrics(s)["carry_over"]) for s in data.sprints("beta")]
    assert carry[-1] > carry[0] and carry[3:] == sorted(carry[3:])


def test_gamma_last_sprint_has_stuck_and_reopened(data):
    m = sprint_metrics(data.sprints("gamma")[-1])
    assert len(m["stuck"]) == 2
    assert {s["hours"] for s in m["stuck"]} == {34.0, 22.0}
    assert len(m["reopened"]) == 1
    assert m["hygiene_score"] < 90


def test_alpha_is_stable(data):
    rates = [sprint_metrics(s)["completion_rate"] for s in data.sprints("alpha")]
    assert min(rates) > 0.75
