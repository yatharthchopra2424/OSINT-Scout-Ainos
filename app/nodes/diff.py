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


def fingerprint(fact: dict) -> str:
    words = re.findall(r"[a-z0-9]+", fact.get("statement", "").lower())
    return f"{fact.get('type')}::{' '.join(words[:8])}"


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

    before = {fingerprint(f): f for f in previous.get("facts", [])}
    after = {fingerprint(f): f for f in current_facts}

    new_facts = [after[k]["statement"] for k in after.keys() - before.keys()]
    gone = [before[k]["statement"] for k in before.keys() - after.keys()]

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
