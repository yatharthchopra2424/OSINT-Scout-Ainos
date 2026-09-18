"""The data contract.

Everything the pipeline produces is one of these shapes. The LLM is never allowed
to invent a field: the extract node asks for `FactList` via structured output, and
anything that does not fit is rejected before it reaches the rest of the system.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "account_brief.v1"

# The only fact types the scoring rules know about. Keeping this closed is what
# lets rules.yml stay a simple lookup instead of fuzzy string matching.
FactType = Literal[
    "company_profile",
    "funding",
    "leadership_change",
    "hiring",
    "product_launch",
    "market_expansion",
    "partnership",
    "layoffs",
    "tech_stack",
]

FACT_TYPES: list[str] = list(FactType.__args__)


class Fact(BaseModel):
    """One claim about a company, with the source it came from."""

    type: FactType
    statement: str = Field(description="One sentence, factual, no speculation.")
    event_date: Optional[str] = Field(
        default=None, description="ISO date (YYYY-MM-DD) of the event, or null if undated."
    )
    source_url: str = Field(description="The URL this fact was read from.")
    quote: str = Field(
        default="", description="The sentence from the source that supports the statement."
    )


class FactList(BaseModel):
    """What the extract node asks the model for."""

    facts: list[Fact] = Field(default_factory=list)


class VerifiedFact(Fact):
    """A fact after the verify node has checked it against retrieved text."""

    support_score: float = 0.0
    supported: bool = False
    reason: str = ""


class EmailDraft(BaseModel):
    """What the model is asked for when drafting outreach.

    Structured output, not a text format to parse. An earlier version asked for
    "Subject: ...\\n\\n<body>" and the reasoning model echoed the format template
    back verbatim and then thought out loud underneath it. Constraining the shape
    removes the parsing problem entirely.
    """

    subject: str = Field(description="The email subject. Under 8 words. No placeholders.")
    body: str = Field(
        description="The email body only. 60-110 words, plain text, no markdown, "
        "no subject line, no commentary about the email."
    )


class ScoreLine(BaseModel):
    """One rule that fired, and the fact that made it fire."""

    rule: str
    points: int
    because: str
    source_url: str


class Score(BaseModel):
    total: int = 0
    band: Literal["Low", "Medium", "High"] = "Low"
    lines: list[ScoreLine] = Field(default_factory=list)


class Delta(BaseModel):
    """What changed since the previous run of this account."""

    is_first_run: bool = True
    previous_run_id: Optional[str] = None
    new_facts: list[str] = Field(default_factory=list)
    dropped_facts: list[str] = Field(default_factory=list)
    band_before: Optional[str] = None
    band_after: Optional[str] = None
    direction: Literal["up", "down", "flat"] = "flat"


class AccountBrief(BaseModel):
    """The deliverable."""

    schema_version: str = SCHEMA_VERSION
    run_id: str
    account: str
    account_id: str
    generated_at: str
    source_mode: str

    summary: str = ""
    facts: list[VerifiedFact] = Field(default_factory=list)
    dropped: list[VerifiedFact] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    score: Score = Field(default_factory=Score)
    delta: Delta = Field(default_factory=Delta)

    documents_used: int = 0
    chunks_indexed: int = 0
    retries: int = 0
    errors: list[str] = Field(default_factory=list)
