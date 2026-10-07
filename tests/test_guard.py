from sprint_analytics.guard import allowed_numbers, check, extract_numbers

FACTS = {
    "sprint": "Beta Sprint 6", "sprint_id": 6,
    "start": "2026-08-10T09:00:00+00:00", "end": "2026-08-21T18:00:00+00:00",
    "committed_points": 44, "added_points": 21, "completed_points": 30,
    "completion_rate": 0.46, "issues_total": 17, "issues_done": 8,
    "carry_over": ["BETA-66", "BETA-67", "BETA-68"],
    "cycle_time_p50": 15.55, "cycle_time_p85": 21.46,
    "stuck": [{"key": "BETA-71", "status": "In Progress", "hours": 86.32}],
    "comparison": {"sprints": ["Beta Sprint 4", "Beta Sprint 5", "Beta Sprint 6"],
                   "velocity": [33, 36, 30], "trend_pct": -13.0, "baseline_velocity": 34.5},
}


def test_extract_handles_formats_and_skips_issue_keys():
    text = "Velocity 1,700 points, 46% done, ~20 hours, 21.0 added; BETA-66 and GAMMA-12 slipped."
    assert extract_numbers(text) == [1700.0, 46.0, 20.0, 21.0]


def test_numbers_inside_issue_keys_are_not_facts():
    # BETA-66 is in the facts, but 66 is not a number the code computed
    assert not check("Beta Sprint 6 completed 66 points.", FACTS).ok
    assert not check("The board shows 71 points left.", FACTS).ok


def test_length_of_the_comparison_window_is_not_a_fact():
    # three sprints in the window does not make "3 issues" true
    assert not check("Only 2 issues carried over.", FACTS).ok
    assert check("3 issues carried over.", FACTS).ok  # carry_over really has 3 items here


def test_half_up_rounding_is_accepted():
    facts = {"cycle_time_p50": 22.5, "cycle_time_p85": 21.45, "completion_rate": 0.125}
    assert check("P50 about 23 hours, P85 about 21.5 hours, 13% done.", facts).ok


def test_correct_report_passes():
    text = ("Beta Sprint 6 (Aug 10–21): the team completed 30 of 65 points (46%). "
            "21 points were added mid-sprint and 3 issues carried over: BETA-66, BETA-67, BETA-68. "
            "Velocity is down 13% against the 34.5-point baseline. Cycle time P85 is 21.5 hours; "
            "BETA-71 has been in progress for 86 hours.")
    result = check(text, FACTS)
    assert result.ok, result.invented


def test_invented_number_is_rejected():
    result = check("The team completed 32 points and velocity rose 15%.", FACTS)
    assert not result.ok
    assert result.invented == ["32", "15"]


def test_rounding_and_percent_forms_are_allowed():
    allowed = allowed_numbers(FACTS)
    for n in (15.55, 15.6, 16, 46, 0.46, 13, 86, 86.3):
        assert n in allowed, n


def test_text_without_numbers_passes():
    assert check("The sprint went fine.", FACTS).ok


def test_time_of_day_in_dates_is_not_a_free_pass():
    # 18 appears only as the hour in the sprint end timestamp
    assert not check("Average cycle time was 18 hours.", FACTS).ok


def test_size_of_the_facts_dict_is_not_a_free_pass():
    assert not check(f"There were {len(FACTS)} blockers.", FACTS).ok
