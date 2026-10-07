"""Jira Cloud source (agile REST API). Used when JIRA_* variables are set.

    JIRA_BASE_URL=https://your-site.atlassian.net
    JIRA_EMAIL=you@example.com
    JIRA_API_TOKEN=...
    JIRA_BOARDS=alpha=12,beta=15          # team name = board id
    JIRA_POINTS_FIELD=customfield_10016   # story points field (default shown)

Tested against recorded API responses (tests/fixtures), not a live site.
"""
import json
import os
from datetime import datetime

import httpx

from .models import DONE, IN_PROGRESS, IN_REVIEW, TODO, Issue, Sprint, StatusChange
from .sources import SourceError

DEFAULT_POINTS_FIELD = "customfield_10016"


def normalise_status(name: str) -> str:
    lowered = name.lower()
    if "review" in lowered:
        return IN_REVIEW
    if "progress" in lowered:
        return IN_PROGRESS
    if lowered in ("done", "closed", "resolved"):
        return DONE
    return TODO


def _when(value: str) -> datetime:
    # Jira sends 2026-09-07T10:00:00.000+0000
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")


def _text(description) -> str:
    if description is None:
        return ""
    return description if isinstance(description, str) else json.dumps(description)


class JiraSource:
    def __init__(self, base_url: str, email: str, token: str, boards: dict[str, int],
                 points_field: str = DEFAULT_POINTS_FIELD, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.boards = boards
        self.points_field = points_field
        self.http = client or httpx.Client(timeout=30)
        self.auth = (email, token)
        self._cache: dict[str, list[Sprint]] = {}

    def _get(self, path: str, params: dict) -> dict:
        try:
            response = self.http.get(self.base_url + path, params=params, auth=self.auth)
        except httpx.HTTPError as exc:
            raise SourceError(f"cannot reach Jira: {exc}") from exc
        if response.status_code == 401:
            raise SourceError("Jira rejected the credentials (401): check JIRA_EMAIL and JIRA_API_TOKEN")
        if response.status_code == 404:
            raise SourceError(f"Jira returned 404 for {path}: check the board id in JIRA_BOARDS")
        if response.status_code >= 400:
            raise SourceError(f"Jira returned {response.status_code} for {path}")
        return response.json()

    def _paged(self, path: str, key: str, params: dict) -> list[dict]:
        items, start = [], 0
        while True:
            page = self._get(path, {**params, "startAt": start, "maxResults": 50})
            batch = page.get(key, [])
            items += batch
            start += len(batch)
            done = page.get("isLast", start >= page.get("total", start))
            if done or not batch:
                return items

    def teams(self) -> list[str]:
        return sorted(self.boards)

    def sprints(self, team: str) -> list[Sprint]:
        if team not in self.boards:
            raise SourceError(f"unknown team '{team}'. Valid teams: {', '.join(self.teams())}")
        if team not in self._cache:
            raw = self._paged(f"/rest/agile/1.0/board/{self.boards[team]}/sprint", "values",
                              {"state": "active,closed"})
            sprints = [self._sprint(team, s) for s in raw if s.get("startDate") and s.get("endDate")]
            self._cache[team] = sorted(sprints, key=lambda s: s.start)
        return self._cache[team]

    def _sprint(self, team: str, raw: dict) -> Sprint:
        start, end = _when(raw["startDate"]), _when(raw.get("completeDate") or raw["endDate"])
        fields = f"summary,issuetype,assignee,description,{self.points_field}"
        issues = self._paged(f"/rest/agile/1.0/sprint/{raw['id']}/issue", "issues",
                             {"expand": "changelog", "fields": fields})
        return Sprint(id=raw["id"], team=team, name=raw["name"], start=start, end=end,
                      issues=[self._issue(i, raw["id"], start) for i in issues])

    def _issue(self, raw: dict, sprint_id: int, sprint_start: datetime) -> Issue:
        f = raw["fields"]
        history, added = [], False
        for entry in raw.get("changelog", {}).get("histories", []):
            at = _when(entry["created"])
            for item in entry.get("items", []):
                if item.get("field") == "status":
                    history.append(StatusChange(normalise_status(item.get("toString") or ""), at))
                elif item.get("field") == "Sprint" and at > sprint_start:
                    added = added or str(sprint_id) in str(item.get("to") or "").split(", ")
        points = f.get(self.points_field)
        return Issue(
            key=raw["key"], summary=f.get("summary", ""),
            type=(f.get("issuetype") or {}).get("name", "task").lower(),
            story_points=float(points) if points is not None else None,
            assignee=(f.get("assignee") or {}).get("displayName"),
            has_acceptance_criteria="acceptance criteria" in _text(f.get("description")).lower(),
            added_after_start=added, history=history)


def from_env() -> JiraSource | None:
    env = os.environ
    if not all(env.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_BOARDS")):
        return None
    try:
        boards = {name.strip(): int(board) for name, board in
                  (pair.split("=") for pair in env["JIRA_BOARDS"].split(",") if pair.strip())}
    except ValueError as exc:
        raise SourceError("JIRA_BOARDS must look like 'alpha=12,beta=15'") from exc
    return JiraSource(env["JIRA_BASE_URL"], env["JIRA_EMAIL"], env["JIRA_API_TOKEN"], boards,
                      env.get("JIRA_POINTS_FIELD", DEFAULT_POINTS_FIELD))
