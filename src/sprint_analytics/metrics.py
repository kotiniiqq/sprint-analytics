"""Sprint metrics as pure functions. No network, no LLM: every number in a report
comes from here, so this is the part that carries the tests."""
import math
from datetime import datetime

from .models import ACTIVE_STATUSES, DONE, IN_PROGRESS, Issue, Sprint
from .worktime import business_hours


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: always one of the observed values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def _points(issue: Issue) -> float:
    return issue.story_points or 0


def _until(issue: Issue, end: datetime) -> list:
    """History as it stood at the sprint end; later changes belong to later sprints."""
    return [c for c in issue.history if c.at <= end]


def _cycle_time(issue: Issue, end: datetime) -> float | None:
    """First In Progress to the last Done before the sprint end, in business hours."""
    history = _until(issue, end)
    started = next((c.at for c in history if c.status == IN_PROGRESS), None)
    finished = next((c.at for c in reversed(history) if c.status == DONE), None)
    if started is None or finished is None or finished <= started:
        return None
    return business_hours(started, finished)


def _time_in_status(issue: Issue, start: datetime, end: datetime) -> dict[str, float]:
    totals: dict[str, float] = {}
    changes = issue.history
    for i, change in enumerate(changes):
        leaves = changes[i + 1].at if i + 1 < len(changes) else end
        lo, hi = max(change.at, start), min(leaves, end)
        if change.status != DONE and hi > lo:
            totals[change.status] = totals.get(change.status, 0) + business_hours(lo, hi)
    return totals


def _was_reopened(issue: Issue, end: datetime) -> bool:
    seen_done = False
    for change in _until(issue, end):
        if change.status == DONE:
            seen_done = True
        elif seen_done:
            return True
    return False


def _missing(issue: Issue) -> list[str]:
    missing = []
    if issue.story_points is None:
        missing.append("story points")
    if not issue.assignee:
        missing.append("assignee")
    if not issue.has_acceptance_criteria:
        missing.append("acceptance criteria")
    return missing


def sprint_metrics(sprint: Sprint, stuck_threshold_hours: float = 16.0) -> dict:
    end = sprint.end
    done = [i for i in sprint.issues if i.status_at(end) == DONE]
    committed = sum(_points(i) for i in sprint.issues if not i.added_after_start)
    added = sum(_points(i) for i in sprint.issues if i.added_after_start)
    completed = sum(_points(i) for i in done)
    scope = committed + added

    cycle = {i.key: ct for i in done if (ct := _cycle_time(i, end)) is not None}

    status_hours: dict[str, float] = {}
    for issue in sprint.issues:
        for status, hours in _time_in_status(issue, sprint.start, end).items():
            status_hours[status] = round(status_hours.get(status, 0) + hours, 2)

    hygiene_issues = {i.key: m for i in sprint.issues if (m := _missing(i))}
    checks_failed = sum(len(m) for m in hygiene_issues.values())
    checks_total = 3 * len(sprint.issues)
    hygiene = 100.0 if checks_total == 0 else round(100 * (1 - checks_failed / checks_total), 1)

    stuck = []
    for issue in sprint.issues:
        status = issue.status_at(end)
        if status not in ACTIVE_STATUSES:
            continue
        entered = max(c.at for c in issue.history if c.at <= end and c.status == status)
        hours = business_hours(entered, end)
        if hours > stuck_threshold_hours:
            stuck.append({"key": issue.key, "status": status, "hours": hours})
    stuck.sort(key=lambda s: -s["hours"])

    return {
        "team": sprint.team,
        "sprint": sprint.name,
        "sprint_id": sprint.id,
        "start": sprint.start.isoformat(),
        "end": end.isoformat(),
        "committed_points": committed,
        "added_points": added,
        "completed_points": completed,
        "completion_rate": round(completed / scope, 2) if scope else 0.0,
        "issues_total": len(sprint.issues),
        "issues_done": len(done),
        "carry_over": [i.key for i in sprint.issues if i not in done],
        "cycle_time_hours": cycle,
        "cycle_time_p50": percentile(list(cycle.values()), 50),
        "cycle_time_p85": percentile(list(cycle.values()), 85),
        "time_in_status_hours": status_hours,
        "reopened": [i.key for i in sprint.issues if _was_reopened(i, end)],
        "hygiene_score": hygiene,
        "hygiene_issues": hygiene_issues,
        "stuck": stuck,
    }


def compare_sprints(sprints: list[Sprint], last_n: int = 3) -> dict:
    """Velocity trend: the latest sprint against the average of the ones before it."""
    window = sprints[-last_n:] if last_n > 0 else sprints
    metrics = [sprint_metrics(s) for s in window]
    velocity = [m["completed_points"] for m in metrics]
    previous = velocity[:-1]
    baseline = sum(previous) / len(previous) if previous else None
    trend = round((velocity[-1] - baseline) / baseline * 100, 1) if baseline else None
    return {
        "team": window[0].team if window else None,
        "sprints": [m["sprint"] for m in metrics],
        "velocity": velocity,
        "baseline_velocity": round(baseline, 1) if baseline is not None else None,  # mean of the earlier sprints
        "trend_pct": trend,  # latest sprint vs baseline_velocity
        "completion_rates": [m["completion_rate"] for m in metrics],
        "carry_over_counts": [len(m["carry_over"]) for m in metrics],
    }
