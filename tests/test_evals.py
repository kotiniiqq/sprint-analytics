import json

from sprint_analytics.evals import parse_judge, run_guard_suite, run_report_suite, write_results
from sprint_analytics.llm import LLMError, LLMResult


def result(text):
    return LLMResult(text=text, model="fake", prompt_tokens=10, completion_tokens=5,
                     cost_usd=0.001, latency_ms=100)


def test_guard_suite_reports_precision_and_recall():
    res = run_guard_suite()
    assert res["cases"] == len(res["rows"]) > 10
    assert res["tp"] + res["fp"] + res["tn"] + res["fn"] == res["cases"]
    assert 0 <= res["precision"] <= 1 and 0 <= res["recall"] <= 1
    # every hand-written correct report must pass: a guard that blocks good reports is useless
    assert res["fp"] == 0, [r for r in res["rows"] if r["expect"] == "pass" and r["got"] == "reject"]


CASES = [{"id": "beta6", "team": "beta", "sprint": 6, "required": ["velocity", "carry_over"],
          "forbidden": ["no risks"]}]


def test_report_suite_scores_a_fake_model(monkeypatch, tmp_path):
    monkeypatch.setenv("SA_TRACE_DIR", str(tmp_path))
    good = "Beta Sprint 6 completed 30 points. Carried over: BETA-66, BETA-67. No risks."
    judge_json = json.dumps({"accuracy": 4, "usefulness": 3, "actionability": 2, "comment": "ok"})
    res = run_report_suite(models=["fake"], llm=lambda m, model=None: result(good),
                           judge=lambda m, model=None: result(judge_json), cases=CASES)
    s = res["models"]["fake"]["summary"]
    assert s["guard_pass_rate"] == 1.0
    assert 0 < s["facts_recall"] < 1          # velocity found, carry-over only partly
    assert s["forbidden_hits"] == 1
    assert (s["judge_accuracy"], s["judge_usefulness"], s["judge_actionability"]) == (4, 3, 2)


def test_unparseable_judge_is_none_not_a_crash():
    assert parse_judge("I think it is good") is None
    assert parse_judge('{"accuracy": 9, "usefulness": 1, "actionability": 1}') is None
    assert parse_judge('Sure! {"accuracy": 5, "usefulness": 4, "actionability": 3}')["accuracy"] == 5


def test_llm_errors_are_counted(monkeypatch):
    def broken(messages, model=None):
        raise LLMError("429")
    res = run_report_suite(models=["fake"], llm=broken, judge=broken, cases=CASES)
    assert res["models"]["fake"]["summary"]["errors"] == 1


def test_write_results_creates_markdown(tmp_path):
    path = write_results([run_guard_suite()], out_dir=tmp_path)
    assert "Guard suite" in path.read_text(encoding="utf-8")
    assert list((tmp_path / "results").glob("*.json"))


def test_required_facts_use_word_boundaries_and_number_parsing():
    from sprint_analytics.evals import _required
    facts = {"completed_points": 1700, "added_points": 0, "hygiene_score": 88.9,
             "carry_over": ["BETA-66"], "reopened": [], "stuck": []}
    assert _required("velocity", facts, "Delivered 1,700 points.") == 1.0
    assert _required("carry_over", facts, "BETA-6 slipped.") == 0.0
    assert _required("carry_over", facts, "BETA-66 slipped.") == 1.0
    assert _required("hygiene", facts, "Hygiene is 89.") == 1.0
