"""Generate the bundled synthetic sprints (seeded, reproducible).

    python scripts/generate_data.py

Three teams, six two-week sprints each, with planted scenarios the metrics and
evals are expected to surface:

- alpha: healthy and stable.
- beta:  scope creep and growing carry-over in the last three sprints.
- gamma: missing estimates and acceptance criteria, work stuck in review,
         one ticket reopened after Done.
"""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "src" / "sprint_analytics" / "data"
FIRST_SPRINT = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)  # a Monday
POINTS = [1, 2, 3, 3, 5, 5, 8]
PEOPLE = ["ann", "bohdan", "carla", "dmytro", "eva", "farid"]
SUMMARIES = [
    "Payment retry for declined cards", "Server restart from the panel", "Invoice PDF layout",
    "Rate-limit the public API", "Audit log export", "Migrate cron jobs to the queue",
    "Two-factor login for staff", "Ticket auto-assignment rules", "Billing webhook idempotency",
    "Dashboard load time", "Backup restore drill", "Plan upgrade flow", "Search by server IP",
    "Refund approval step", "Status page incident sync", "Locale for Polish customers",
]


def add_business_hours(start: datetime, hours: float) -> datetime:
    """Move forward by working hours (Mon–Fri 09–18 UTC)."""
    current, left = start, hours
    while left > 0:
        if current.weekday() >= 5 or current.hour >= 18:
            current = (current + timedelta(days=1)).replace(hour=9, minute=0)
            continue
        if current.hour < 9:
            current = current.replace(hour=9, minute=0)
        day_end = current.replace(hour=18, minute=0)
        available = (day_end - current).total_seconds() / 3600
        step = min(available, left)
        current += timedelta(hours=step)
        left -= step
    return current


def iso(value: datetime) -> str:
    return value.isoformat()


class Team:
    def __init__(self, name: str, prefix: str, seed: int):
        self.name, self.prefix = name, prefix
        self.rng = random.Random(seed)
        self.counter = 0

    def key(self) -> str:
        self.counter += 1
        return f"{self.prefix}-{self.counter}"

    def issue(self, start, end, *, done=True, final_status=None, added=False,
              points=True, criteria=True, assignee=True, reopened=False, review_hours=None,
              start_after_hours=None):
        rng = self.rng
        if start_after_hours is None:
            start_after_hours = rng.uniform(1, 30) if not added else rng.uniform(25, 45)
        begin = add_business_hours(start, start_after_hours)
        history = [{"status": "In Progress", "at": iso(begin)}]
        review_at = add_business_hours(begin, rng.uniform(4, 22))
        if done:
            history.append({"status": "In Review", "at": iso(review_at)})
            done_at = add_business_hours(review_at, rng.uniform(1, 6))
            if done_at >= end:
                done_at = end - timedelta(hours=2)
            history.append({"status": "Done", "at": iso(done_at)})
            if reopened:
                back = add_business_hours(done_at, 3)
                history.append({"status": "In Progress", "at": iso(back)})
                history.append({"status": "Done", "at": iso(add_business_hours(back, 5))})
        elif final_status == "In Review":
            at = end - timedelta(hours=1) if review_hours is None else None
            if review_hours is not None:
                # walk back from the sprint end so the time in review is exact
                at = end
                left = review_hours
                while left > 0:
                    at -= timedelta(hours=1)
                    if at.weekday() < 5 and 9 <= at.hour < 18:
                        left -= 1
            history.append({"status": "In Review", "at": iso(at)})
        elif final_status == "To Do":
            history = []
        return {
            "key": self.key(),
            "summary": rng.choice(SUMMARIES),
            "type": rng.choice(["story", "story", "task", "bug"]),
            "story_points": rng.choice(POINTS) if points else None,
            "assignee": rng.choice(PEOPLE) if assignee else None,
            "has_acceptance_criteria": criteria,
            "added_after_start": added,
            "history": history,
        }


def sprint_window(index: int):
    start = FIRST_SPRINT + timedelta(weeks=2 * index)
    end = start + timedelta(days=11, hours=9)  # second Friday, 18:00
    return start, end


def alpha() -> list[dict]:
    team, sprints = Team("alpha", "ALPHA", 235), []  # seed picked for a steady velocity
    for i in range(6):
        start, end = sprint_window(i)
        issues = [team.issue(start, end) for _ in range(11)]
        # one small item picked up on the last day: normal carry-over, not a stuck ticket
        issues.append(team.issue(start, end, done=False, final_status="In Progress", start_after_hours=84))
        sprints.append(sprint_doc(i, "alpha", start, end, issues))
    return sprints


def beta() -> list[dict]:
    team, sprints = Team("beta", "BETA", 202), []
    added_per_sprint = [1, 1, 1, 3, 5, 7]
    carry_per_sprint = [1, 1, 1, 3, 5, 6]
    for i in range(6):
        start, end = sprint_window(i)
        committed_done = 10 - carry_per_sprint[i]
        issues = [team.issue(start, end) for _ in range(committed_done)]
        issues += [team.issue(start, end, done=False, final_status="In Progress")
                   for _ in range(carry_per_sprint[i])]
        issues += [team.issue(start, end, added=True, done=(j % 2 == 0),
                              final_status=None if j % 2 == 0 else "To Do")
                   for j in range(added_per_sprint[i])]
        sprints.append(sprint_doc(i, "beta", start, end, issues))
    return sprints


def gamma() -> list[dict]:
    team, sprints = Team("gamma", "GAMMA", 303), []
    for i in range(6):
        start, end = sprint_window(i)
        rng = team.rng
        issues = [team.issue(start, end, points=rng.random() > 0.25,
                             criteria=rng.random() > 0.3, assignee=rng.random() > 0.1)
                  for _ in range(9)]
        if i == 5:
            issues.append(team.issue(start, end, done=False, final_status="In Review", review_hours=34))
            issues.append(team.issue(start, end, done=False, final_status="In Review", review_hours=22))
            issues.append(team.issue(start, end, reopened=True))
        else:
            issues.append(team.issue(start, end, done=False, final_status="In Progress"))
        sprints.append(sprint_doc(i, "gamma", start, end, issues))
    return sprints


def sprint_doc(index, team, start, end, issues):
    return {"id": index + 1, "team": team, "name": f"{team.title()} Sprint {index + 1}",
            "start": iso(start), "end": iso(end), "issues": issues}


def main() -> None:
    DATA.mkdir(exist_ok=True)
    for name, build in [("alpha", alpha), ("beta", beta), ("gamma", gamma)]:
        path = DATA / f"{name}.json"
        path.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
        print("wrote", path)


if __name__ == "__main__":
    main()
