# sprint-analytics

[![M8ven Score](https://m8ven.ai/badge/mcp/kotiniiqq-sprint-analytics-1fegwz?v=5ba779835dea5a9fba7c25810f0b1945)](https://m8ven.ai/mcp/kotiniiqq-sprint-analytics-1fegwz?s=readme)

Jira sprint metrics computed by code, written up by an LLM, with a guard that rejects
any number the model did not get from the code. Ships as a CLI and as an **MCP server**,
with **evals** that measure the guard and the reports, and **tracing** of every LLM and
tool call (local JSONL, optionally Langfuse).

> Reference implementation of the sprint agents I built for a client's engineering team,
> where eight team leads used them for nine departments. The client's code is private; this
> repo rebuilds the core ideas from scratch on **synthetic data**, so anyone can run it.

## Run it in one minute

```bash
git clone https://github.com/kotiniiqq/sprint-analytics && cd sprint-analytics
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                           # or: pip install git+https://github.com/kotiniiqq/sprint-analytics

sprint-analytics report --team gamma
```

No keys needed. Without an LLM key you get the deterministic report:

```
[template, reason: no_key]

Gamma Sprint 6: completed 19 of 25 points (76%), down 33.3% against the previous sprints' average of 28.5 points. Cycle time P50 14.79 h, P85 21.8 h.

Risks:
- 2 issues carried over: GAMMA-60, GAMMA-61.
- GAMMA-60 has been In Review for 34 working hours.
- GAMMA-61 has been In Review for 22 working hours.
- Reopened after Done: GAMMA-62.
- Hygiene score 88.9: 4 issues are missing estimates, owners or acceptance criteria.
```

Set `OPENROUTER_API_KEY` (and optionally `SA_MODEL`, default `anthropic/claude-sonnet-5`) and the
same command asks the model to write the report; the guard then decides whether it is used.

Other commands: `teams`, `metrics`, `compare`, `stuck`, `eval`, `serve-mcp` (`--help` on each).

## Code computes, the model writes

```
data source ──► metrics.py ──► facts (JSON) ──► LLM writes prose ──► guard.py ──► report
(synthetic       pure, tested                                         │ a number that is
 or Jira)                                                             │ not in the facts?
                                                                      └──► deterministic template
```

- **Every number comes from `metrics.py`**: velocity, completion rate, scope added after start,
  carry-over, cycle time P50/P85 and time in status in *working* hours, reopened issues,
  hygiene score, issues stuck in progress or review, all as of the sprint end.
- **The model only writes words.** The prompt forbids arithmetic; `guard.py` extracts every
  number from the answer (handles `1,700`, `46%`, `~16`, skips issue keys like `BETA-12`) and
  checks it against the computed facts and their half-up roundings.
- **If the model invents a number, fails, returns garbage, or no key is set**, a deterministic
  template built from the same facts is used, and the output says which path produced it.

What the guard does **not** catch, by design and measured below: a real fact quoted in the wrong
place, a reversed direction ("up 13%" for a trend of -13), and numbers spelled out in words.

## Use it from Claude Code (MCP)

```bash
claude mcp add sprint-analytics -- /absolute/path/to/.venv/bin/sprint-analytics serve-mcp
```

(Use the absolute path to the script in your virtualenv; Claude Code starts the server itself and
may not have the venv on its `PATH`. On Windows: `...\.venv\Scripts\sprint-analytics.exe`.)

Then ask Claude Code things like *"which gamma issues are stuck and for how long?"* or
*"compare beta's last three sprints"*. Tools, all read-only:

| tool | what it returns |
|---|---|
| `list_sprints` | teams, or a team's sprints with ids and dates |
| `get_sprint_metrics` | the full metrics for one sprint (id as number or string, or name) |
| `compare_sprints` | velocity, baseline and trend over the last N sprints |
| `find_stuck_issues` | issues past a working-hours threshold at sprint end |
| `sprint_report` | the guarded written report |

Bad input comes back as a readable tool error (`unknown team 'delta'. Valid teams: alpha, beta, gamma`),
not a stack trace. Built on the official MCP Python SDK (`mcp` 2.x, `MCPServer`); the tests drive it
through an in-memory MCP client and through a real stdio subprocess.

## Evals

```bash
sprint-analytics eval              # guard suite always; report suite when OPENROUTER_API_KEY is set
sprint-analytics eval --suite report --models anthropic/claude-sonnet-5,google/gemini-2.5-flash
```

Results go to `evals/RESULTS.md` in the current directory.

**Guard suite.** 22 hand-written reports for known sprints, each labelled pass or reject
(`src/sprint_analytics/eval_cases/guard_cases.yaml`). Latest run ([evals/RESULTS.md](evals/RESULTS.md)):

| cases | precision | recall | false alarms | missed |
|---|---|---|---|---|
| 22 | 1.0 | 0.786 | 0 | 3 |

No correct report was blocked. The three misses are the blind spot named above: the wrong number
equals a real fact elsewhere (44 is the committed figure, not the completed one; 22 hours belong to
another issue; "35 points left" matches the 34.5-point baseline after rounding). The guard checks
values, not their meaning; that is what the LLM judge in the report suite is for. CI fails if a
correct report is ever blocked or recall drops below 0.75.

**Report suite.** For each case in `eval_cases/report_cases.yaml` the model writes a report and is
scored on: invented-number rate (guard), recall of the facts that must be mentioned (velocity,
carry-over keys, stuck keys, reopened keys, scope added, hygiene), forbidden claims, and an LLM judge
(accuracy, usefulness, actionability 1–5, fixed rubric, JSON output; the judge model is set separately
with `SA_JUDGE_MODEL`). Several models can be compared in one run; cost and latency come from
OpenRouter usage data. The repo does not ship report-suite numbers yet: they need a paid API key.

## Tracing

Every LLM call (reports and eval runs, judge included) and every MCP tool call, successful or not,
appends a line to `.traces/YYYY-MM-DD.jsonl` (or `SA_TRACE_DIR`): model, tokens, cost, latency, guard
verdict and any invented numbers. Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (and `LANGFUSE_HOST`
for self-hosted) to send the same events to Langfuse. A failing exporter is logged and ignored, with a
3-second timeout: tracing never breaks the request it observes.

## Real Jira

```bash
export JIRA_BASE_URL=https://your-site.atlassian.net JIRA_EMAIL=you@example.com JIRA_API_TOKEN=...
export JIRA_BOARDS="platform=12,payments=15"           # team name = board id
export JIRA_POINTS_FIELD=customfield_10016              # your story points field
export JIRA_STATUS_MAP='{"Ready to ship": "In Review"}' # optional, for unusual workflow names
sprint-analytics metrics --team platform
```

Uses the Jira Cloud agile API (`board/{id}/sprint`, `sprint/{id}/issue?expand=changelog`), follows
pagination, fetches the full changelog when Jira truncates it, maps common workflow names (QA,
Testing, In Development, Blocked, Released…) to four statuses, and measures an active sprint up to
now rather than its planned end. If the Jira variables are only partly set, it warns and uses the
synthetic data. **Tested against hand-written fixtures modelled on the documented response shapes**
(`tests/fixtures/`), not against a live site.

## Synthetic data

`scripts/generate_data.py` (seeded) creates three teams × six sprints with planted scenarios that the
tests and evals check for:

- **alpha**: healthy: steady velocity, no scope added mid-sprint, nothing stuck;
- **beta**: scope creep and growing carry-over in the last sprints;
- **gamma**: missing estimates and acceptance criteria, work stuck in review, a ticket reopened after Done.

## Project layout

```
src/sprint_analytics/
  models.py  worktime.py  metrics.py      core: data, working hours, metrics (pure)
  sources.py  jira.py                     synthetic data or Jira Cloud
  guard.py  report.py  llm.py             facts -> prose -> guard -> fallback
  tracing.py                              JSONL + Langfuse
  mcp_server.py  cli.py  evals.py         interfaces and evaluation
  data/  eval_cases/                      bundled sprints and eval cases (ship with the package)
evals/RESULTS.md                          latest eval results
tests/                                    89 tests, no network
```

## How this was built

A written design spec and implementation plan first, then task-by-task test-first implementation
with every diff reviewed before commit, then an independent review of the whole repository. That
review found real bugs which are fixed and pinned by tests: the guard accepted numbers hidden
inside issue keys (`BETA-66` made "66 points" pass) and rejected correct roundings (Python's
banker's rounding); cycle time read changelog entries from after the sprint ended (144 h instead
of 9 h); a regular non-editable install could not find the bundled data.

## License

MIT
