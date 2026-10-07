# Eval results

Last run: 2026-10-07T15-07-02Z. Raw data: `evals/results/2026-10-07T15-07-02Z.json`.

## Guard suite (no LLM)

Hand-written reports with known verdicts. Can the guard catch invented numbers?

| cases | precision | recall | accuracy | missed (fn) | false alarms (fp) |
|---|---|---|---|---|---|
| 22 | 1.0 | 0.786 | 0.864 | 3 | 0 |

Misclassified: `alpha6-wrong-carry-count`, `beta6-swapped-numbers`, `gamma6-swapped-hours`
