"""Date back-fill on extracted facts.

The model is asked for an event_date and frequently returns null anyway. A fact
with no date cannot fire a time-windowed rule, which once turned an account with
five correct facts from High (75) into Low (0) — silently, with nothing in the
output looking wrong.

The date is not a judgement call: it is either written in the sentence or it is
the publication date of the page the fact was read from. So the code takes it.
"""

from app.nodes.extract import _backfill_dates, _date_in

CHUNKS = [
    {"url": "https://a.test/about", "published": "2026-01-12"},
    {"url": "https://b.test/news", "published": ""},
]


def make(statement, source_url, event_date=None, quote=""):
    return {"type": "funding", "statement": statement, "quote": quote,
            "source_url": source_url, "event_date": event_date}


def test_iso_date_is_read_out_of_the_sentence():
    assert _date_in("Acme raised 42 million on 2026-06-10.") == "2026-06-10"


def test_long_form_date_is_normalised():
    assert _date_in("Acme launched on 2 August 2026.") == "2026-08-02"


def test_sentence_with_no_date_returns_none():
    assert _date_in("Acme is a freight forwarder.") is None


def test_date_in_the_sentence_wins():
    facts, filled = _backfill_dates(
        [make("Acme raised 42 million on 2026-06-10.", "https://a.test/about")], CHUNKS
    )
    assert facts[0]["event_date"] == "2026-06-10"
    assert filled == 1


def test_falls_back_to_the_publication_date_of_the_cited_page():
    facts, _ = _backfill_dates(
        [make("Acme is a freight forwarder.", "https://a.test/about")], CHUNKS
    )
    assert facts[0]["event_date"] == "2026-01-12"


def test_quote_is_used_when_the_statement_has_no_date():
    facts, _ = _backfill_dates(
        [make("Acme raised money.", "https://b.test/news",
              quote="The round closed on 2026-05-20.")],
        CHUNKS,
    )
    assert facts[0]["event_date"] == "2026-05-20"


def test_an_existing_date_is_never_overwritten():
    facts, filled = _backfill_dates(
        [make("Acme raised money.", "https://a.test/about", event_date="2026-05-05")], CHUNKS
    )
    assert facts[0]["event_date"] == "2026-05-05"
    assert filled == 0


def test_genuinely_undated_facts_are_left_alone():
    """No date in the text and no publication date. Inventing one here would put
    a fabricated date behind a real score."""
    facts, filled = _backfill_dates(
        [make("Acme is a freight forwarder.", "https://b.test/news")], CHUNKS
    )
    assert facts[0]["event_date"] is None
    assert filled == 0


def test_backfill_is_deterministic():
    results = {
        _backfill_dates([make("Acme raised 42 million on 2026-06-10.", "https://a.test/about")],
                        CHUNKS)[0][0]["event_date"]
        for _ in range(5)
    }
    assert results == {"2026-06-10"}
