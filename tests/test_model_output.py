"""Reading a model's reply without trusting its manners.

The NIM endpoint rejects `guided_json` on some backend instances and accepts it on
others — same model, same key, minutes apart — so the fallback path has to get a
shape out of free text. A reasoning model wraps JSON in prose, fences it, thinks
out loud around it, or runs out of tokens halfway through the object.

None of these tests call the network.
"""

from app.llm.clients import _unsupported, first_json_object
from app.sources.clean import clean_text, is_prose


# ---------------------------------------------------------------------------
# JSON recovery
# ---------------------------------------------------------------------------
def test_plain_object():
    assert first_json_object('{"facts": [{"type": "funding"}]}') == {"facts": [{"type": "funding"}]}


def test_fenced_object():
    reply = '```json\n{"facts": [{"type": "hiring"}]}\n```'
    assert first_json_object(reply) == {"facts": [{"type": "hiring"}]}


def test_object_wrapped_in_prose():
    reply = 'Here is the result:\n{"facts": []}\nHope that helps.'
    assert first_json_object(reply) == {"facts": []}


def test_thinking_tags_are_stripped():
    reply = '<think>let me consider this</think>{"subject": "hello", "body": "hi"}'
    assert first_json_object(reply)["subject"] == "hello"


def test_braces_inside_strings_do_not_end_the_object():
    reply = '{"facts": [{"statement": "uses {curly} braces"}]}'
    assert first_json_object(reply)["facts"][0]["statement"] == "uses {curly} braces"


def test_truncated_object_is_repaired():
    """Reasoning eats the token budget and the reply stops mid-string. Losing the
    whole extraction to a missing brace would be worse than closing it ourselves."""
    reply = '{"facts": [{"type": "funding", "statement": "raised 42 million'
    recovered = first_json_object(reply)
    assert recovered["facts"][0]["type"] == "funding"


def test_text_with_no_json_returns_none():
    assert first_json_object("no json here at all") is None


def test_guided_json_rejection_is_recognised_as_unsupported():
    exc = Exception("[400] {'message': 'unknown field `guided_json`', 'code': 400}")
    assert _unsupported(exc) is True


def test_an_auth_error_is_not_treated_as_unsupported():
    """A 401 must surface, not silently fall back to a different code path."""
    assert _unsupported(Exception("[401] invalid api key")) is False


# ---------------------------------------------------------------------------
# boilerplate filtering
# ---------------------------------------------------------------------------
def test_real_sentence_is_kept():
    assert is_prose("Northwind Logistics is a freight forwarder headquartered in Rotterdam.")


def test_navigation_chrome_is_dropped():
    assert not is_prose("Just now save ## Walk-in || Customer Support Executive Image 33:")


def test_fragment_starting_mid_word_is_dropped():
    """A truncated scrape: 'ed by companies, mined from state filings...'"""
    assert not is_prose("ed by companies, mined from state filings or news, provided by others")


def test_copyright_line_is_dropped():
    assert not is_prose("Copyright 2026 Atlas Freight Systems. All rights reserved.")


def test_clean_text_keeps_prose_and_discards_the_rest():
    raw = ("Home. About. Contact us. Northwind Logistics is a freight forwarder "
           "headquartered in Rotterdam. Privacy policy.")
    cleaned = clean_text(raw)
    assert "freight forwarder" in cleaned
    assert "Privacy policy" not in cleaned
