"""The scoring rules.

These matter more than they look. The score is the number a salesperson acts on,
and the whole design argument is that a model never produces it — so the rule
engine has to be provably boring: same facts in, same number out, every point
traceable to a rule and a date.
"""

from datetime import date

import pytest

from app.rules.engine import load_rules, score_facts
from app.schemas.brief import VerifiedFact

TODAY = date(2026, 9, 18)


def fact(fact_type: str, event_date: str | None, statement: str = "x") -> VerifiedFact:
    return VerifiedFact(
        type=fact_type,
        statement=statement,
        event_date=event_date,
        source_url="https://example.test/a",
        quote=statement,
        support_score=1.0,
        supported=True,
    )


def test_recent_funding_fires_inside_the_window():
    result = score_facts([fact("funding", "2026-06-10")], today=TODAY)
    assert result.total == 30
    assert [line.rule for line in result.lines] == ["recent_funding"]


def test_old_funding_does_not_fire():
    """180-day window. A round from two years ago says nothing about budget now."""
    result = score_facts([fact("funding", "2024-06-10")], today=TODAY)
    assert result.total == 0
    assert result.lines == []


def test_undated_fact_cannot_fire_a_time_windowed_rule():
    """This is the failure that silently turned a High account into a Low one."""
    assert score_facts([fact("funding", None)], today=TODAY).total == 0


def test_undated_fact_still_fires_a_rule_with_no_window():
    """tech_overlap has within_days: null, so it does not need a date."""
    result = score_facts([fact("tech_stack", None)], today=TODAY)
    assert result.total == 10


def test_layoffs_subtract_and_can_cancel_a_positive_signal():
    """Hiring +20 against layoffs -20 nets to zero, and the floor is zero."""
    facts = [fact("hiring", "2026-07-01"), fact("layoffs", "2026-08-05")]
    result = score_facts(facts, today=TODAY)
    assert result.total == 0
    assert result.band == "Low"
    assert {line.rule for line in result.lines} == {"hiring_surge", "layoffs"}


def test_score_never_goes_negative():
    assert score_facts([fact("layoffs", "2026-08-05")], today=TODAY).total == 0


def test_a_rule_fires_at_most_once_however_many_facts_match():
    facts = [fact("funding", "2026-06-10", "a"), fact("funding", "2026-07-10", "b")]
    result = score_facts(facts, today=TODAY)
    assert result.total == 30
    assert len(result.lines) == 1


@pytest.mark.parametrize(
    "total_facts, expected_band",
    [
        ([("tech_stack", None)], "Low"),                                  # 10
        ([("funding", "2026-06-10"), ("hiring", "2026-07-15")], "Medium"),  # 50
        ([("funding", "2026-06-10"), ("hiring", "2026-07-15"),
          ("market_expansion", "2026-08-02"), ("partnership", "2026-05-20")], "High"),  # 75
    ],
)
def test_bands(total_facts, expected_band):
    facts = [fact(t, d) for t, d in total_facts]
    assert score_facts(facts, today=TODAY).band == expected_band


def test_every_line_carries_the_source_of_the_fact_that_fired_it():
    """Auditability: a point with no URL behind it is not defensible."""
    result = score_facts([fact("funding", "2026-06-10")], today=TODAY)
    assert all(line.source_url.startswith("https://") for line in result.lines)


def test_scoring_is_deterministic():
    facts = [fact("funding", "2026-06-10"), fact("partnership", "2026-05-20")]
    totals = {score_facts(facts, today=TODAY).total for _ in range(5)}
    assert len(totals) == 1


def test_rules_file_is_well_formed():
    rules = load_rules()
    assert set(rules) >= {"bands", "rules"}
    for rule in rules["rules"]:
        assert {"name", "fact_type", "points", "because"} <= set(rule)
        assert "within_days" in rule, f"{rule['name']} must state its window, even if null"
