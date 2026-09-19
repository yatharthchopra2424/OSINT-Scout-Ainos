"""Node 7 — what changed since last time.

This is the reason the tool is a workflow instead of a one-shot answer. A brief you
generate once is a commodity; a brief that tells you what moved this week is
something a rep actually opens on a Monday.

Facts are compared by a fingerprint (type + the first words of the statement) so a
reworded sentence about the same event does not register as news.
"""

import re

from app.ops import store as run_store
from app.state import RunState


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "its", "has", "have",
    "was", "were", "are", "will", "their", "they", "said", "into", "across",
    "about", "which", "than", "also", "more", "been", "over",
}
SAME_EVENT = 0.6        # token overlap above which two statements are one event


def signature(fact: dict) -> tuple[str, frozenset]:
    """What a fact is *about*, independent of how it was worded.

    Matching on the first few words of a statement looked fine against the control
    extractor, which emits the source sentence verbatim. A model rewords the same
    event between runs — "raised 42 million in a Series B" one run, "closed a
    Series B round of 42 million" the next — and a literal fingerprint reports
    that as a fact appearing and a fact disappearing. On a screen whose entire job
    is "what changed since last time", phantom change is the worst possible bug.
    """
    words = re.findall(r"[a-z0-9]+", fact.get("statement", "").lower())
    keep = {w for w in words if (w.isdigit() or len(w) > 3) and w not in STOPWORDS}
    return fact.get("type", ""), frozenset(keep)


def same_event(a: tuple[str, frozenset], b: tuple[str, frozenset]) -> bool:
    """Same fact type, same figures, and most of the meaningful words in common.

    Numbers are checked first and are decisive. Word overlap alone is not enough:
    "raised 42 million in a Series B" and "raised 8 million in a seed round" share
    the company name and every generic verb, which clears any sensible threshold
    while describing two completely different events. If both statements carry
    figures and none of them match, they are not the same thing.
    """
    if a[0] != b[0] or not a[1] or not b[1]:
        return False

    numbers_a = {t for t in a[1] if t.isdigit()}
    numbers_b = {t for t in b[1] if t.isdigit()}
    if numbers_a and numbers_b and not (numbers_a & numbers_b):
        return False

    overlap = len(a[1] & b[1]) / min(len(a[1]), len(b[1]))
    return overlap >= SAME_EVENT


def fingerprint(fact: dict) -> str:
    """Stable, human-readable id. Kept for logs and tests."""
    kind, tokens = signature(fact)
    return f"{kind}::{' '.join(sorted(tokens)[:8])}"


def diff(state: RunState) -> dict:
    log = state["log"]
    log.start("diff")

    previous = run_store.previous_run(state["account_id"], state["run_id"])
    current_facts = state.get("verified", [])

    if not previous:
        log.finish("diff", first_run=True)
        return {
            "delta": {
                "is_first_run": True,
                "previous_run_id": None,
                "new_facts": [],
                "dropped_facts": [],
                "band_before": None,
                "band_after": state.get("score", {}).get("band"),
                "direction": "flat",
            }
        }

    before = [(signature(f), f) for f in previous.get("facts", [])]
    after = [(signature(f), f) for f in current_facts]

    new_facts = [
        fact["statement"] for sig, fact in after
        if not any(same_event(sig, old_sig) for old_sig, _ in before)
    ]
    gone = [
        fact["statement"] for sig, fact in before
        if not any(same_event(sig, new_sig) for new_sig, _ in after)
    ]

    order = {"Low": 0, "Medium": 1, "High": 2}
    band_before = previous.get("score", {}).get("band", "Low")
    band_after = state.get("score", {}).get("band", "Low")
    direction = (
        "up" if order[band_after] > order[band_before]
        else "down" if order[band_after] < order[band_before]
        else "flat"
    )

    log.finish("diff", new=len(new_facts), gone=len(gone), direction=direction)
    return {
        "delta": {
            "is_first_run": False,
            "previous_run_id": previous.get("run_id"),
            "new_facts": new_facts,
            "dropped_facts": gone,
            "band_before": band_before,
            "band_after": band_after,
            "direction": direction,
        }
    }
