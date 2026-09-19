"""Change detection between runs.

The Pipeline and Briefs screens both answer one question: what moved since last
time. Phantom change is therefore the worst bug this system can have — worse than
missing a fact, because it actively wastes a rep's attention.

The control extractor emits the source sentence verbatim, so a literal fingerprint
looked fine. A model rewords the same event between runs, and the eval caught it:
two accounts reported changes on an identical re-run.
"""

from app.nodes.diff import fingerprint, same_event, signature


def sig(fact_type: str, statement: str):
    return signature({"type": fact_type, "statement": statement})


def test_the_same_event_reworded_is_not_a_change():
    a = sig("funding", "Northwind Logistics raised 42 million euro in a Series B round.")
    b = sig("funding", "Northwind closed a Series B round of 42 million euro.")
    assert same_event(a, b)


def test_rewording_without_figures_is_still_matched():
    a = sig("tech_stack", "Helio Airways runs on an Amadeus passenger service system.")
    b = sig("tech_stack", "Helio Airways uses Amadeus as its passenger service system.")
    assert same_event(a, b)


def test_different_amounts_are_different_events():
    """Company name and generic verbs alone clear any sensible overlap threshold,
    so the figures have to be decisive."""
    a = sig("funding", "Northwind Logistics raised 42 million euro in a Series B round.")
    b = sig("funding", "Northwind Logistics raised 8 million in a seed round.")
    assert not same_event(a, b)


def test_same_words_different_fact_type_is_not_a_match():
    a = sig("funding", "Northwind raised 42 million in a Series B.")
    b = sig("hiring", "Northwind raised 42 million in a Series B.")
    assert not same_event(a, b)


def test_unrelated_facts_of_the_same_type_do_not_match():
    a = sig("funding", "Northwind Logistics raised 42 million euro.")
    b = sig("funding", "Northwind Logistics expands into South East Asia with a Singapore office.")
    assert not same_event(a, b)


def test_a_fact_always_matches_itself():
    a = sig("hiring", "Castor Telecom is hiring for 12 open roles in data and analytics.")
    assert same_event(a, a)


def test_empty_statement_never_matches():
    assert not same_event(sig("funding", ""), sig("funding", "Acme raised 10 million."))


def test_fingerprint_is_stable_under_word_order():
    a = fingerprint({"type": "funding", "statement": "Acme raised 42 million euro."})
    b = fingerprint({"type": "funding", "statement": "42 million euro was raised by Acme."})
    assert a == b
