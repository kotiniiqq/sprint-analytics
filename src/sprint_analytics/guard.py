"""Reject LLM prose that contains numbers the code did not compute.

The model writes the words; it never gets to introduce a figure. Every number
in its text must match a computed fact, a rounding of one, a percentage form of
a rate, the size of a list of issues, or a component of the sprint dates.

Known limits (measured by the guard eval suite):
- it checks values, not meaning: a real fact quoted in the wrong place passes;
- signs are dropped ("down 13%" quotes a trend of -13), so a reversed direction passes;
- numbers spelled out in words are not checked.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")
# collections whose size is itself a fact ("9 issues carried over")
ISSUE_LISTS = {"carry_over", "reopened", "stuck", "hygiene_issues", "cycle_time_hours"}
# strings whose embedded numbers are fair to quote ("Beta Sprint 6")
NAME_FIELDS = {"sprint", "sprints", "name", "team"}


@dataclass
class GuardResult:
    ok: bool
    invented: list[str] = field(default_factory=list)


def extract_numbers(text: str) -> list[float]:
    text = ISSUE_KEY.sub(" ", text)
    return [abs(float(m.group().replace(",", ""))) for m in NUMBER.finditer(text)]


def _round(value: float, places: int) -> float:
    """Round half up, the way people do: 22.5 -> 23, 21.45 -> 21.5 (not banker's rounding)."""
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def _variants(value: float, is_rate: bool) -> set[float]:
    value = abs(value)
    out = {value, _round(value, 0), _round(value, 1)}
    if is_rate:
        pct = value * 100
        out |= {_round(pct, 1), _round(pct, 0)}
    return out


def _walk(node, key: str, acc: set[float]) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        acc |= _variants(float(node), "rate" in key)
    elif isinstance(node, (dict, list, tuple)):
        if key in ISSUE_LISTS:
            acc.add(float(len(node)))
        for k, v in (node.items() if isinstance(node, dict) else ((key, v) for v in node)):
            _walk(v, str(k), acc)
    elif isinstance(node, str):
        if key in ("start", "end"):
            try:
                d = datetime.fromisoformat(node)
                acc |= {float(d.year), float(d.month), float(d.day)}
            except ValueError:
                pass
        elif key in NAME_FIELDS:
            acc |= {float(n) for n in re.findall(r"\d+", node)}


def allowed_numbers(facts: dict) -> set[float]:
    acc: set[float] = set()
    _walk(facts, "", acc)
    # a total a reader naturally states: scope = committed + added
    if {"committed_points", "added_points"} <= facts.keys():
        acc.add(float(facts["committed_points"] + facts["added_points"]))
    return acc


def check(text: str, facts: dict) -> GuardResult:
    allowed = allowed_numbers(facts)
    invented = [f"{n:g}" for n in extract_numbers(text) if not any(abs(n - a) < 1e-6 for a in allowed)]
    return GuardResult(ok=not invented, invented=invented)
