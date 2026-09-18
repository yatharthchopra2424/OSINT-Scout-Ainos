"""Node 6 — scoring. No model here, and that is the point.

The rules in app/rules/rules.yml decide what a fact is worth. Same facts in, same
number out, every time — and every point traces to a rule and a source URL.
"""

from datetime import date, datetime

from app.rules.engine import score_facts
from app.schemas.brief import VerifiedFact
from app.state import RunState


def score(state: RunState) -> dict:
    log = state["log"]
    log.start("score")

    facts = [VerifiedFact(**f) for f in state.get("verified", [])]

    today_str = state.get("today")
    today = datetime.strptime(today_str, "%Y-%m-%d").date() if today_str else date.today()

    result = score_facts(facts, today=today)

    log.finish(
        "score",
        total=result.total, band=result.band,
        rules_fired=[line.rule for line in result.lines], evaluated_on=str(today),
    )
    return {"score": result.model_dump()}
