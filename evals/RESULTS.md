# Eval results

Last run: 2026-10-07T15-19-18Z. Raw per-case data is written to `evals/results/` (not committed).

## Guard suite (no LLM)

Hand-written reports with known verdicts. Can the guard catch invented numbers?

| cases | precision | recall | accuracy | missed (fn) | false alarms (fp) |
|---|---|---|---|---|---|
| 22 | 1.0 | 0.786 | 0.864 | 3 | 0 |

Misclassified: `beta6-derived-arithmetic`, `beta6-swapped-numbers`, `gamma6-swapped-hours`
