"""Code computes, the model writes.

Facts come from `metrics`. The LLM only turns them into prose; `guard` rejects
prose with numbers the code did not produce, and a deterministic template takes
over whenever the model is unavailable, fails, or is caught inventing.
"""
import json
from dataclasses import dataclass
from typing import Callable

from . import tracing
from .guard import GuardResult, check
from .llm import LLMError, LLMResult, complete, default_model, llm_configured
from .metrics import compare_sprints, sprint_metrics
from .models import Sprint

SYSTEM_PROMPT = """You write sprint reports for an engineering manager.
Rules:
- Use only the numbers that appear in FACTS. Do not add, subtract, average or estimate.
- Refer to issues by their keys exactly as given.
- Structure: a 2-3 sentence summary, then "Risks:" with up to 3 bullets, then "Actions:" with up to 3 bullets.
- Bullets start with "- ". No numbered lists, no tables, no headings. Under 180 words.
- If the sprint looks healthy, say so plainly instead of inventing problems."""


@dataclass
class ReportResult:
    text: str
    source: str            # "llm" or "fallback"
    reason: str | None     # why the fallback was used: no_key | llm_error | guard
    guard: GuardResult | None
    llm: LLMResult | None = None


def build_facts(sprints: list[Sprint], sprint: Sprint, last_n: int = 3) -> dict:
    """Metrics for one sprint plus the trend over the sprints up to it."""
    facts = sprint_metrics(sprint)
    facts.pop("cycle_time_hours")  # per-issue detail the report does not need
    facts["scope_points"] = facts["committed_points"] + facts["added_points"]
    history = [s for s in sprints if s.start <= sprint.start]
    facts["comparison"] = compare_sprints(history, last_n=last_n)
    return facts


def build_prompt(facts: dict) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "FACTS:\n" + json.dumps(facts, indent=2)}]


def _hours(value) -> str:
    return "n/a" if value is None else f"{value:g}"


def deterministic_report(facts: dict) -> str:
    c = facts["comparison"]
    trend = c["trend_pct"]
    trend_line = ("first sprint in the window" if trend is None
                  else f"{'down' if trend < 0 else 'up'} {abs(trend):g}% against the previous sprints")
    lines = [
        f"{facts['sprint']}: completed {facts['completed_points']:g} of {facts['scope_points']:g} points "
        f"({round(facts['completion_rate'] * 100):g}%), {trend_line}. "
        f"Cycle time P50 {_hours(facts['cycle_time_p50'])} h, P85 {_hours(facts['cycle_time_p85'])} h.",
        "",
        "Risks:",
    ]
    risks = []
    if facts["added_points"]:
        risks.append(f"- {facts['added_points']:g} points were added after the sprint started.")
    if facts["carry_over"]:
        risks.append(f"- {len(facts['carry_over'])} issues carried over: {', '.join(facts['carry_over'])}.")
    for item in facts["stuck"]:
        risks.append(f"- {item['key']} has been {item['status']} for {item['hours']:g} working hours.")
    if facts["reopened"]:
        risks.append(f"- Reopened after Done: {', '.join(facts['reopened'])}.")
    if facts["hygiene_issues"]:
        risks.append(f"- Hygiene score {facts['hygiene_score']:g}: "
                     f"{len(facts['hygiene_issues'])} issues are missing estimates, owners or acceptance criteria.")
    lines += risks or ["- No significant risks in the data."]
    return "\n".join(lines)


def generate_report(facts: dict, llm: Callable[..., LLMResult] = complete,
                    model: str | None = None) -> ReportResult:
    model = model or default_model()
    if llm is complete and not llm_configured():
        result = ReportResult(deterministic_report(facts), "fallback", "no_key", None)
    else:
        try:
            answer = llm(build_prompt(facts), model=model)
        except LLMError as exc:
            tracing.trace("sprint_report", model=model, error=str(exc), source="fallback")
            return ReportResult(deterministic_report(facts), "fallback", "llm_error", None)
        verdict = check(answer.text, facts)
        tracing.trace("sprint_report", model=answer.model, input=facts["sprint"], output=answer.text,
                      prompt_tokens=answer.prompt_tokens, completion_tokens=answer.completion_tokens,
                      cost_usd=answer.cost_usd, latency_ms=answer.latency_ms,
                      metadata={"guard_ok": verdict.ok, "invented": verdict.invented})
        if verdict.ok:
            return ReportResult(answer.text, "llm", None, verdict, answer)
        result = ReportResult(deterministic_report(facts), "fallback", "guard", verdict, answer)
    return result
