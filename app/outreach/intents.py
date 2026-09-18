"""What the email is FOR.

Intent is the one thing that changes an outreach email most, and it is the thing
a generic "write me an email" prompt always gets wrong. Each intent below says
which facts to hook on, what the reason for writing is, and what to ask for.

The retrieval side matters here: an intro email should open on the freshest
commercial signal, while a partnership email should open on who they already work
with. Same account, same facts, different pick.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Intent:
    key: str
    label: str
    description: str
    # Fact types to open on, best first. The drafter walks this list and uses the
    # first type the account actually has a verified fact for.
    hooks: list[str]
    ask: str
    guidance: str
    # Fact types this intent must never open on, even if they are the only thing
    # the account has. Opening a post-layoffs email by naming the layoffs is the
    # example that makes this field necessary.
    avoid: list[str] = field(default_factory=list)
    bands: list[str] = field(default_factory=lambda: ["Low", "Medium", "High"])


INTENTS: list[Intent] = [
    Intent(
        key="intro",
        label="First touch",
        description="No prior relationship. Earn a reply by showing you did the reading.",
        hooks=["funding", "market_expansion", "hiring", "product_launch", "leadership_change"],
        ask="Ask for 20 minutes, offer two concrete times, make saying no easy.",
        guidance=(
            "Open on the specific event, not on them. One sentence connecting that event "
            "to a problem it creates. One sentence on what you do about it. Then the ask."
        ),
    ),
    Intent(
        key="reengage",
        label="Re-engage a quiet account",
        description="You spoke before and it went cold. A new signal is the reason to return.",
        hooks=["leadership_change", "funding", "product_launch", "market_expansion"],
        ask="Ask whether the new development changes the picture. No pressure, no guilt.",
        guidance=(
            "Reference that you spoke before in half a sentence, without relitigating it. "
            "The new event is the entire reason for the email — lead with it."
        ),
    ),
    Intent(
        key="partnership",
        label="Partnership / alliance",
        description="A joint or channel angle rather than a direct sale.",
        hooks=["partnership", "market_expansion", "product_launch", "company_profile"],
        ask="Propose a specific, small first step — one call between the two alliance leads.",
        guidance=(
            "Talk about the overlap, not your product. Name the partner or market that made "
            "you think of them. Mutual benefit has to be visible in one sentence."
        ),
    ),
    Intent(
        key="new_exec",
        label="New executive",
        description="Someone just took the seat. Their first two quarters are when vendors get re-evaluated.",
        hooks=["leadership_change", "hiring", "product_launch"],
        ask="Offer something useful with no meeting attached, then a soft opening for one.",
        guidance=(
            "Congratulate in at most four words — anything longer reads as filler. Assume they "
            "are drowning. Lead with what you can take off their plate."
        ),
    ),
    Intent(
        key="event_followup",
        label="Event follow-up",
        description="You met, or you were both at the same thing. Short memory window.",
        hooks=["product_launch", "market_expansion", "funding", "hiring"],
        ask="Pick up exactly where the conversation stopped. One question, not a pitch.",
        guidance=(
            "Reference the specific conversation, not the event. If you cannot remember "
            "something specific, the email should not be sent — say so in the draft notes."
        ),
    ),
    Intent(
        key="careful",
        label="Careful timing (post-layoffs)",
        description="Cost-cutting or restructuring. Wrong email here costs you the account.",
        hooks=["hiring", "tech_stack", "product_launch", "company_profile"],
        ask="No meeting ask. Offer something genuinely useful and step back.",
        guidance=(
            "Do not mention the layoffs directly and do not pitch efficiency savings off the "
            "back of job cuts — it reads as circling. Be short, be useful, leave."
        ),
        avoid=["layoffs"],
        bands=["Low"],
    ),
]

BY_KEY = {i.key: i for i in INTENTS}


def suggest(band: str, fact_types: set[str]) -> str:
    """Pick a sensible default intent for an account, given what we actually found."""
    if "layoffs" in fact_types:
        return "careful"
    if "leadership_change" in fact_types:
        return "new_exec"
    if "partnership" in fact_types and band != "High":
        return "partnership"
    return "intro"


def as_dicts() -> list[dict]:
    return [
        {
            "key": i.key,
            "label": i.label,
            "description": i.description,
            "hooks": i.hooks,
            "ask": i.ask,
        }
        for i in INTENTS
    ]
