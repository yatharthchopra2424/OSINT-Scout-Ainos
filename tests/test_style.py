"""The outreach style checker.

It has one job that actually matters: catching an email that could have been sent
to anyone, and catching a number that traces to no verified fact. The second check
exists because a real bug let a competitor's funding round into an email addressed
to a different company.
"""

from app.outreach import style

FACTS = [
    {
        "type": "hiring",
        "statement": "Solent Maritime is hiring for 6 open roles in vessel operations.",
        "quote": "Solent Maritime is hiring for 6 open roles in vessel operations.",
        "event_date": "2026-06-20",
        "source_url": "https://solentmaritime.example/careers",
    },
    {
        "type": "company_profile",
        "statement": "The business employs 410 people across four UK ports.",
        "quote": "The business employs 410 people across four UK ports.",
        "event_date": None,
        "source_url": "https://solentmaritime.example/about",
    },
]

GROUNDED = (
    "Solent Maritime is hiring for 6 open roles in vessel operations. "
    "With 410 people across four ports, scheduling gets fiddly fast. "
    "Worth 20 minutes on Tuesday at 10 am?"
)

SLOP = (
    "I hope this email finds you well. In today's fast-paced landscape we can "
    "leverage robust synergies to unlock seamless value. Furthermore, our "
    "cutting-edge platform empowers teams to streamline operations holistically."
)

GENERIC = "Hi there. We help companies like yours do better. Interested in learning more?"


def checks(text, facts=None):
    return {flag["check"] for flag in style.check(text, facts or [])["flags"]}


def test_grounded_email_scores_well_and_is_clean():
    result = style.check(GROUNDED, FACTS)
    assert result["score"] >= 80
    assert result["verdict"] == "ready"
    assert "unverified_claim" not in checks(GROUNDED, FACTS)


def test_stock_phrasing_is_scored_badly():
    result = style.check(SLOP, FACTS)
    assert result["score"] <= 25
    assert result["verdict"] == "rewrite it"
    assert {"opener", "filler", "tics"} <= checks(SLOP, FACTS)


def test_grammatical_but_generic_email_still_fails():
    """No filler and no stock opener, but it could go to anyone. That is the
    actual problem with most cold email, so it carries the heaviest penalty."""
    result = style.check(GENERIC, FACTS)
    assert result["score"] < 80
    assert "specificity" in checks(GENERIC, FACTS)


def test_number_with_no_supporting_fact_is_flagged():
    leaked = (
        "Calder Shipping raised 60 million euro in a Series C round on 2026-07-14. "
        "Can we talk Tuesday?"
    )
    assert "unverified_claim" in checks(leaked, FACTS)


def test_meeting_times_and_durations_are_not_treated_as_claims():
    """'Tuesday at 10 am' and '20 minutes' are the writer's own words, not
    assertions about the company."""
    text = (
        "Solent Maritime is hiring for 6 open roles in vessel operations. "
        "Could we find 20 minutes, Tuesday at 10 am or Thursday at 2 pm?"
    )
    assert "unverified_claim" not in checks(text, FACTS)


def test_an_email_with_no_question_is_flagged():
    assert "ask" in checks("Solent Maritime is hiring for 6 open roles.", FACTS)


def test_quick_fix_removes_the_stock_opener_and_filler():
    fixed = style.quick_fix(SLOP)
    lowered = fixed.lower()
    assert "i hope this email finds you well" not in lowered
    assert "leverage" not in lowered
    assert style.check(fixed, FACTS)["score"] > style.check(SLOP, FACTS)["score"]


def test_quick_fix_does_not_leave_doubled_punctuation():
    """Deleting a hedge mid-sentence used to produce 'quick chat??'."""
    assert "??" not in style.quick_fix("I just wanted to ask, would you be open to a quick chat?")


def test_scoring_is_deterministic():
    scores = {style.check(GROUNDED, FACTS)["score"] for _ in range(5)}
    assert len(scores) == 1


def test_stats_are_reported_for_every_check():
    stats = style.check(GROUNDED, FACTS)["stats"]
    assert {"words", "sentences", "questions", "facts_referenced"} <= set(stats)
    assert stats["words"] > 0
