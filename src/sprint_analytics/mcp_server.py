"""MCP server: the same metrics and guarded report, exposed as tools for Claude Code
or any MCP client.

    claude mcp add sprint-analytics -- sprint-analytics serve-mcp
"""
import time
from functools import wraps

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import tracing
from .metrics import compare_sprints as _compare, sprint_metrics
from .report import build_facts, generate_report
from .sources import Source, SourceError, find_sprint, get_source

INSTRUCTIONS = (
    "Sprint analytics over Jira-style sprint data. Numbers come from deterministic code; "
    "use get_sprint_metrics or compare_sprints for figures and sprint_report for a written summary. "
    "Call list_sprints first if you do not know the team or sprint ids."
)

# Every tool only reads sprint data; traces go to a local log. The data tools stay inside the
# configured source; sprint_report also sends the computed facts to the LLM provider.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)
CALLS_LLM = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=True)


def _traced(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            tracing.trace(f"mcp.{fn.__name__}", input=kwargs or list(args), ok=True,
                          latency_ms=int((time.perf_counter() - started) * 1000))
            return result
        except SourceError as exc:
            tracing.trace(f"mcp.{fn.__name__}", input=kwargs or list(args), ok=False, error=str(exc))
            # ToolError reaches the client as is; any other exception would be masked
            raise ToolError(str(exc)) from exc
        except Exception as exc:
            tracing.trace(f"mcp.{fn.__name__}", input=kwargs or list(args), ok=False,
                          error=f"{type(exc).__name__}: {exc}")
            raise
    return wrapper


def build_server(source: Source | None = None) -> MCPServer:
    data = source or get_source()
    server = MCPServer(name="sprint-analytics", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY, description="List teams, or the sprints of one team with their ids and dates.")
    @_traced
    def list_sprints(team: str | None = None) -> dict:
        if not team:
            return {"teams": data.teams()}
        return {"team": team, "sprints": [
            {"id": s.id, "name": s.name, "start": s.start.isoformat(), "end": s.end.isoformat()}
            for s in data.sprints(team)]}

    @server.tool(annotations=READ_ONLY, description="Metrics for one sprint: velocity, completion rate, carry-over, cycle time "
                             "P50/P85, time in status, reopened issues, hygiene, stuck issues. "
                             "sprint is an id or a name; omit it for the latest sprint.")
    @_traced
    def get_sprint_metrics(team: str, sprint: str | int | None = None) -> dict:
        return sprint_metrics(find_sprint(data, team, sprint))

    @server.tool(annotations=READ_ONLY, description="Velocity and completion trend over the last N sprints of a team.")
    @_traced
    def compare_sprints(team: str, last_n: int = 3) -> dict:
        if last_n < 1:
            raise SourceError("last_n must be at least 1")
        return _compare(data.sprints(team), last_n=last_n)

    @server.tool(annotations=READ_ONLY, description="Issues sitting In Progress or In Review longer than threshold_hours "
                             "(working hours) at the end of the sprint.")
    @_traced
    def find_stuck_issues(team: str, sprint: str | int | None = None, threshold_hours: float = 16.0) -> dict:
        target = find_sprint(data, team, sprint)
        return {"sprint": target.name,
                "stuck": sprint_metrics(target, stuck_threshold_hours=threshold_hours)["stuck"]}

    @server.tool(annotations=CALLS_LLM, description="Written sprint report. The LLM writes from computed facts only; a guard "
                             "rejects any number the code did not produce and falls back to a template.")
    @_traced
    def sprint_report(team: str, sprint: str | int | None = None) -> dict:
        target = find_sprint(data, team, sprint)
        result = generate_report(build_facts(data.sprints(team), target))
        return {"sprint": target.name, "source": result.source, "fallback_reason": result.reason,
                "report": result.text}

    return server


def main() -> None:
    build_server().run("stdio")
