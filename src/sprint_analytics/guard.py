"""Reject LLM prose that contains numbers the code did not compute.

The model writes the words; it never gets to introduce a figure. Every number
in its text must match a computed fact, a rounding of one, a percentage form of
a rate, the size of a listed collection, or a component of the sprint dates.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")
COLLECTIONS = {"cycle_time_hours", "hygiene_issues", "time_in_status_hours"}
NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")


@dataclass
class GuardResult:
    ok: bool
    invented: list[str] = field(default_factory=list)


def extract_numbers(text: str) -> list[float]:
    text = ISSUE_KEY.sub(" ", text)
    text = LIST_MARKER.sub(" ", text)
    return [abs(float(m.group().replace(",", ""))) for m in NUMBER.finditer(text)]


def _variants(value: float, is_rate: bool) -> set[float]:
    value = abs(value)
    out = {value, round(value), round(value, 1)}
    if is_rate:
        pct = value * 100
        out |= {round(pct, 1), round(pct)}
    return out


def _walk(node, key: str, acc: set[float]) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        acc |= _variants(float(node), "rate" in key)
    elif isinstance(node, dict):
        if key in COLLECTIONS:  # "3 issues missing data" is a fact; the size of the facts dict is not
            acc.add(float(len(node)))
        for k, v in node.items():
            _walk(v, str(k), acc)
    elif isinstance(node, (list, tuple)):
        acc.add(float(len(node)))
        for v in node:
            _walk(v, key, acc)
    elif isinstance(node, str):
        if key in ("start", "end"):
            try:
                d = datetime.fromisoformat(node)
                acc |= {float(d.year), float(d.month), float(d.day)}
            except ValueError:
                pass
        else:  # numbers inside names, e.g. "Beta Sprint 6"
            acc |= {float(n) for n in re.findall(r"\d+", node)}


def allowed_numbers(facts: dict) -> set[float]:
    acc: set[float] = set()
    _walk(facts, "", acc)
    # totals a reader naturally states: scope = committed + added
    if {"committed_points", "added_points"} <= facts.keys():
        acc.add(float(facts["committed_points"] + facts["added_points"]))
    return acc


def check(text: str, facts: dict) -> GuardResult:
    allowed = allowed_numbers(facts)
    invented = []
    for n in extract_numbers(text):
        if not any(abs(n - a) < 1e-6 for a in allowed):
            invented.append(f"{n:g}")
    return GuardResult(ok=not invented, invented=invented)
