"""Command line: `sprint-analytics <command>`. Run with --help for the list."""
import argparse
import json
import sys

from .metrics import compare_sprints, sprint_metrics
from .report import build_facts, generate_report
from .sources import SourceError, find_sprint, get_source


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _metrics_text(m: dict) -> str:
    rows = [
        ("Sprint", m["sprint"]),
        ("Completed / scope", f"{m['completed_points']:g} / {m['committed_points'] + m['added_points']:g} points "
                              f"({round(m['completion_rate'] * 100):g}%)"),
        ("Added after start", f"{m['added_points']:g} points"),
        ("Carry-over", ", ".join(m["carry_over"]) or "none"),
        ("Cycle time P50 / P85", f"{m['cycle_time_p50']} / {m['cycle_time_p85']} working hours"),
        ("Reopened", ", ".join(m["reopened"]) or "none"),
        ("Hygiene score", f"{m['hygiene_score']:g}"),
        ("Stuck", ", ".join(f"{s['key']} ({s['status']}, {s['hours']:g} h)" for s in m["stuck"]) or "none"),
    ]
    width = max(len(k) for k, _ in rows)
    return "\n".join(f"{k.ljust(width)}  {v}" for k, v in rows)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sprint-analytics",
                                description="Sprint metrics by code, reports by an LLM, numbers guarded.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("teams", help="list teams")
    for name, help_text in [("metrics", "metrics for a sprint"), ("stuck", "issues stuck at sprint end"),
                            ("report", "written sprint report (LLM with guard, or template)")]:
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--team", required=True)
        cmd.add_argument("--sprint", help="sprint id or name; latest when omitted")
        cmd.add_argument("--json", action="store_true", help="machine-readable output")
    cmp_ = sub.add_parser("compare", help="velocity trend over the last sprints")
    cmp_.add_argument("--team", required=True)
    cmp_.add_argument("--last", type=int, default=3)
    ev = sub.add_parser("eval", help="run evals and write evals/RESULTS.md")
    ev.add_argument("--suite", choices=["guard", "report", "all"], default="all")
    ev.add_argument("--models", help="comma-separated OpenRouter model ids for the report suite")
    sub.add_parser("serve-mcp", help="run the MCP server over stdio")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run(args) -> int:
    if args.command == "serve-mcp":
        from .mcp_server import main as serve
        serve()
        return 0
    if args.command == "eval":
        return _eval(args)

    source = get_source()
    if args.command == "teams":
        print("\n".join(source.teams()))
        return 0
    if args.command == "compare":
        if args.last < 1:
            raise SourceError("--last must be at least 1")
        _print_json(compare_sprints(source.sprints(args.team), last_n=args.last))
        return 0

    sprint = find_sprint(source, args.team, args.sprint)
    if args.command == "metrics":
        m = sprint_metrics(sprint)
        _print_json(m) if args.json else print(_metrics_text(m))
    elif args.command == "stuck":
        stuck = sprint_metrics(sprint)["stuck"]
        if args.json:
            _print_json(stuck)
        else:
            print("\n".join(f"{s['key']}  {s['status']}  {s['hours']:g} h" for s in stuck) or "nothing stuck")
    elif args.command == "report":
        result = generate_report(build_facts(source.sprints(args.team), sprint))
        if args.json:
            _print_json({"source": result.source, "fallback_reason": result.reason, "report": result.text})
        else:
            label = "LLM, guard passed" if result.source == "llm" else f"template, reason: {result.reason}"
            print(f"[{label}]\n\n{result.text}")
    return 0


def _eval(args) -> int:
    from .evals import run_guard_suite, run_report_suite, write_results
    from .llm import llm_configured

    results = []
    if args.suite in ("guard", "all"):
        results.append(run_guard_suite())
    if args.suite in ("report", "all"):
        if llm_configured():
            models = [m.strip() for m in args.models.split(",")] if args.models else None
            results.append(run_report_suite(models=models))
        elif args.suite == "report":
            raise SourceError("the report suite needs OPENROUTER_API_KEY")
        else:
            print("report suite skipped: OPENROUTER_API_KEY is not set", file=sys.stderr)
    path = write_results(results)
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
