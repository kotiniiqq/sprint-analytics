import pytest

from sprint_analytics.sources import SourceError, SyntheticSource, find_sprint


@pytest.fixture
def source():
    return SyntheticSource()


def test_loads_all_teams(source):
    assert source.teams() == ["alpha", "beta", "gamma"]


def test_sprints_are_chronological_and_aware(source):
    sprints = source.sprints("beta")
    assert len(sprints) == 6
    assert [s.start for s in sprints] == sorted(s.start for s in sprints)
    assert sprints[0].start.tzinfo is not None
    assert all(c.at.tzinfo is not None for s in sprints for i in s.issues for c in i.history)


def test_find_sprint_latest_by_default(source):
    assert find_sprint(source, "gamma", None).id == 6


def test_find_sprint_by_id_or_name(source):
    assert find_sprint(source, "alpha", 2).id == 2
    assert find_sprint(source, "alpha", "2").id == 2
    assert find_sprint(source, "alpha", "Alpha Sprint 3").id == 3


def test_unknown_team_lists_valid_teams(source):
    with pytest.raises(SourceError) as err:
        source.sprints("delta")
    assert "alpha, beta, gamma" in str(err.value)


def test_unknown_sprint_lists_valid_sprints(source):
    with pytest.raises(SourceError) as err:
        find_sprint(source, "alpha", 42)
    assert "1, 2, 3, 4, 5, 6" in str(err.value)
