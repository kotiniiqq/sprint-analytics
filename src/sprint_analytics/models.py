"""Plain data the rest of the package works on. Sources produce it, metrics read it."""
from dataclasses import dataclass, field
from datetime import datetime

TODO, IN_PROGRESS, IN_REVIEW, DONE = "To Do", "In Progress", "In Review", "Done"
ACTIVE_STATUSES = (IN_PROGRESS, IN_REVIEW)


@dataclass(frozen=True)
class StatusChange:
    status: str
    at: datetime


@dataclass
class Issue:
    key: str
    summary: str
    type: str
    story_points: float | None
    assignee: str | None
    has_acceptance_criteria: bool
    added_after_start: bool
    history: list[StatusChange] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.history = sorted(self.history, key=lambda c: c.at)

    def status_at(self, moment: datetime) -> str:
        status = TODO
        for change in self.history:
            if change.at > moment:
                break
            status = change.status
        return status


@dataclass
class Sprint:
    id: int
    team: str
    name: str
    start: datetime
    end: datetime
    issues: list[Issue] = field(default_factory=list)
