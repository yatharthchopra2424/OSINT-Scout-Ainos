"""Deterministic scoring. No model involved.

Give it verified facts, it gives back a number, a band, and a line-by-line
explanation of how it got there.
"""

from datetime import date, datetime

import yaml

from app.config import settings
from app.schemas.brief import Score, ScoreLine, VerifiedFact


def load_rules() -> dict:
    with open(settings.rules_file, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _band(total: int, bands: dict) -> str:
    # Pick the highest band whose floor the total clears.
    best, best_floor = "Low", -10**9
    for name, floor in bands.items():
        if total >= floor >= best_floor:
            best, best_floor = name, floor
    return best


def score_facts(
    facts: list[VerifiedFact],
    today: date | None = None,
    rules: dict | None = None,
) -> Score:
    """Apply every rule to every fact. A rule may fire at most once."""
    rules = rules or load_rules()
    today = today or date.today()

    lines: list[ScoreLine] = []
    already_fired: set[str] = set()

    for rule in rules["rules"]:
        if rule["name"] in already_fired:
            continue

        for fact in facts:
            if fact.type != rule["fact_type"]:
                continue

            window = rule.get("within_days")
            if window is not None:
                event = _parse_date(fact.event_date)
                if event is None:
                    continue                      # rule needs a date, fact has none
                if (today - event).days > window:
                    continue                      # too old to count

            lines.append(
                ScoreLine(
                    rule=rule["name"],
                    points=rule["points"],
                    because=f"{rule['because']} ({fact.statement})",
                    source_url=fact.source_url,
                )
            )
            already_fired.add(rule["name"])
            break

    total = max(0, sum(line.points for line in lines))
    return Score(total=total, band=_band(total, rules["bands"]), lines=lines)
