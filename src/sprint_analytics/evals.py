"""Evals: measure the guard and the reports instead of eyeballing them.

guard suite  - hand-written reports with known verdicts; precision/recall of catching
               invented numbers. No LLM, runs anywhere.
report suite - real model output for known sprints; invented-number rate (guard),
               required-facts recall, forbidden phrases, LLM-judge scores, cost, latency.
"""
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from .guard import check
from .llm import LLMError, LLMResult, complete, default_model
from .report import build_facts, build_prompt
from .sources import Source, SyntheticSource, find_sprint

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"

JUDGE_PROMPT = """You grade a sprint report written for an engineering manager.
You get FACTS (computed by code, always correct) and REPORT.
Score each 1-5:
- accuracy: every claim matches FACTS; 1 if anything contradicts them.
- usefulness: the most important signals in FACTS are surfaced (risks first).
- actionability: actions are concrete and follow from the facts.
Answer with JSON only: {"accuracy": n, "usefulness": n, "actionability": n, "comment": "one sentence"}"""


def _load(name: str) -> list[dict]:
    return yaml.safe_load((EVALS_DIR / name).read_text(encoding="utf-8"))


def _facts(source: Source, team: str, sprint) -> dict:
    sprints = source.sprints(team)
    return build_facts(sprints, find_sprint(source, team, sprint))


# ---------- guard suite ----------

def run_guard_suite(source: Source | None = None, cases: list[dict] | None = None) -> dict:
    source = source or SyntheticSource()
    cases = cases or _load("guard_cases.yaml")
    tp = fp = tn = fn = 0
    rows = []
    for case in cases:
        verdict = check(case["text"], _facts(source, case["team"], case["sprint"]))
        rejected, should_reject = not verdict.ok, case["expect"] == "reject"
        tp += rejected and should_reject
        fp += rejected and not should_reject
        tn += not rejected and not should_reject
        fn += not rejected and should_reject
        rows.append({"id": case["id"], "expect": case["expect"],
                     "got": "reject" if rejected else "pass", "invented": verdict.invented,
                     "correct": rejected == should_reject})
    return {
        "suite": "guard", "cases": len(cases), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "accuracy": round((tp + tn) / len(cases), 3) if cases else None,
        "rows": rows,
    }


# ---------- report suite ----------

def _required(name: str, facts: dict, text: str) -> float | None:
    """Share of the required items present in the text; None when the fact is empty."""
    numbers = {f"{float(n):g}" for n in re.findall(r"\d+(?:\.\d+)?", text)}
    if name == "velocity":
        return float(f"{facts['completed_points']:g}" in numbers)
    if name == "scope_added":
        return float(f"{facts['added_points']:g}" in numbers) if facts["added_points"] else None
    if name == "hygiene":
        return float(f"{facts['hygiene_score']:g}" in numbers or f"{round(facts['hygiene_score']):g}" in numbers)
    keys = {"carry_over": facts["carry_over"], "reopened": facts["reopened"],
            "stuck": [s["key"] for s in facts["stuck"]]}[name]
    if not keys:
        return None
    return sum(k in text for k in keys) / len(keys)


def parse_judge(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group())
        scores = {k: int(data[k]) for k in ("accuracy", "usefulness", "actionability")}
    except (ValueError, KeyError, TypeError):
        return None
    if not all(1 <= v <= 5 for v in scores.values()):
        return None
    return {**scores, "comment": str(data.get("comment", ""))}


def run_report_suite(models: list[str] | None = None, llm: Callable[..., LLMResult] = complete,
                     judge: Callable[..., LLMResult] = complete, judge_model: str | None = None,
                     source: Source | None = None, cases: list[dict] | None = None) -> dict:
    source = source or SyntheticSource()
    cases = cases or _load("cases.yaml")
    models = models or [default_model()]
    judge_model = judge_model or default_model()
    per_model = {}
    for model in models:
        rows = []
        for case in cases:
            facts = _facts(source, case["team"], case["sprint"])
            row = {"id": case["id"], "model": model}
            try:
                answer = llm(build_prompt(facts), model=model)
            except LLMError as exc:
                rows.append({**row, "error": str(exc)})
                continue
            verdict = check(answer.text, facts)
            recall = [r for name in case["required"] if (r := _required(name, facts, answer.text)) is not None]
            lowered = answer.text.lower()
            row.update(guard_ok=verdict.ok, invented=verdict.invented,
                       facts_recall=round(sum(recall) / len(recall), 3) if recall else None,
                       forbidden_hits=[p for p in case.get("forbidden", []) if p.lower() in lowered],
                       cost_usd=answer.cost_usd, latency_ms=answer.latency_ms, text=answer.text)
            try:
                graded = judge([{"role": "system", "content": JUDGE_PROMPT},
                                {"role": "user", "content": f"FACTS:\n{json.dumps(facts)}\n\nREPORT:\n{answer.text}"}],
                               model=judge_model)
                row["judge"] = parse_judge(graded.text)
            except LLMError as exc:
                row["judge"], row["judge_error"] = None, str(exc)
            rows.append(row)
        per_model[model] = {"summary": _summarise(rows), "rows": rows}
    return {"suite": "report", "judge_model": judge_model, "models": per_model}


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 3) if values else None


def _summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    judged = [r["judge"] for r in ok if r.get("judge")]
    return {
        "cases": len(rows), "errors": len(rows) - len(ok),
        "guard_pass_rate": _mean([float(r["guard_ok"]) for r in ok]),
        "facts_recall": _mean([r["facts_recall"] for r in ok]),
        "forbidden_hits": sum(len(r["forbidden_hits"]) for r in ok),
        "judge_accuracy": _mean([j["accuracy"] for j in judged]),
        "judge_usefulness": _mean([j["usefulness"] for j in judged]),
        "judge_actionability": _mean([j["actionability"] for j in judged]),
        "cost_usd": round(sum(r["cost_usd"] or 0 for r in ok), 5),
        "avg_latency_ms": _mean([r["latency_ms"] for r in ok]),
    }


# ---------- output ----------

def write_results(results: list[dict], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or EVALS_DIR
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    raw_dir = out_dir / "results"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{stamp}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                           encoding="utf-8", newline="\n")
    lines = ["# Eval results", "", f"Last run: {stamp}. Raw data: `evals/results/{stamp}.json`.", ""]
    for res in results:
        if res["suite"] == "guard":
            lines += ["## Guard suite (no LLM)", "",
                      "Hand-written reports with known verdicts. Can the guard catch invented numbers?", "",
                      "| cases | precision | recall | accuracy | missed (fn) | false alarms (fp) |",
                      "|---|---|---|---|---|---|",
                      f"| {res['cases']} | {res['precision']} | {res['recall']} | {res['accuracy']} "
                      f"| {res['fn']} | {res['fp']} |", ""]
            missed = [r["id"] for r in res["rows"] if not r["correct"]]
            if missed:
                lines += ["Misclassified: " + ", ".join(f"`{m}`" for m in missed), ""]
        else:
            lines += ["## Report suite (LLM)", "", f"Judge model: `{res['judge_model']}`.", "",
                      "| model | guard pass | facts recall | forbidden hits | accuracy | usefulness "
                      "| actionability | cost $ | avg latency ms |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for model, data in res["models"].items():
                s = data["summary"]
                lines.append(f"| `{model}` | {s['guard_pass_rate']} | {s['facts_recall']} | {s['forbidden_hits']} "
                             f"| {s['judge_accuracy']} | {s['judge_usefulness']} | {s['judge_actionability']} "
                             f"| {s['cost_usd']} | {s['avg_latency_ms']} |")
            lines.append("")
    path = out_dir / "RESULTS.md"
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path
