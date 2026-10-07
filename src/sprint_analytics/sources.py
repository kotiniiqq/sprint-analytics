"""Where sprints come from. Everything downstream only sees `Sprint` objects."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import Issue, Sprint, StatusChange

DEFAULT_DATA = Path(__file__).resolve().parent / "data"  # shipped inside the package


class SourceError(Exception):
    """A request the source cannot serve; the message is meant for a person."""


class Source(Protocol):
    def teams(self) -> list[str]: ...
    def sprints(self, team: str) -> list[Sprint]: ...


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SourceError(f"timestamp without timezone in data: {value}")
    return parsed


def sprint_from_dict(doc: dict) -> Sprint:
    issues = [
        Issue(key=i["key"], summary=i["summary"], type=i["type"], story_points=i["story_points"],
              assignee=i["assignee"], has_acceptance_criteria=i["has_acceptance_criteria"],
              added_after_start=i["added_after_start"],
              history=[StatusChange(h["status"], _aware(h["at"])) for h in i["history"]])
        for i in doc["issues"]
    ]
    return Sprint(id=doc["id"], team=doc["team"], name=doc["name"],
                  start=_aware(doc["start"]), end=_aware(doc["end"]), issues=issues)


class SyntheticSource:
    """Bundled synthetic sprints: data/<team>.json."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path(os.environ.get("SA_DATA_DIR", DEFAULT_DATA))
        self._cache: dict[str, list[Sprint]] = {}

    def teams(self) -> list[str]:
        return sorted(p.stem for p in self.data_dir.glob("*.json"))

    def sprints(self, team: str) -> list[Sprint]:
        if team not in self._cache:
            path = self.data_dir / f"{team}.json"
            if not path.exists():
                raise SourceError(f"unknown team '{team}'. Valid teams: {', '.join(self.teams())}")
            docs = json.loads(path.read_text(encoding="utf-8"))
            self._cache[team] = sorted((sprint_from_dict(d) for d in docs), key=lambda s: s.start)
        return self._cache[team]


def find_sprint(source: Source, team: str, sprint: str | int | None) -> Sprint:
    """Latest sprint when `sprint` is None; otherwise match by id or by name."""
    sprints = source.sprints(team)
    if not sprints:
        raise SourceError(f"team '{team}' has no sprints")
    if sprint is None or sprint == "":
        return sprints[-1]
    wanted = str(sprint).strip().lower()
    for s in sprints:
        if wanted in (str(s.id), s.name.lower()):
            return s
    valid = ", ".join(str(s.id) for s in sprints)
    raise SourceError(f"unknown sprint '{sprint}' for team '{team}'. Valid sprint ids: {valid}")


def get_source() -> Source:
    """Jira Cloud when JIRA_* is configured, the bundled synthetic data otherwise."""
    from .jira import from_env

    return from_env() or SyntheticSource()
