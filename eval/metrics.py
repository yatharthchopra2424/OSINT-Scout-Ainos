"""How a run is scored against the gold set.

Two principles:

1. The metrics do not trust the pipeline. Groundedness is re-checked here against
   the original fixture documents, so a bug in the verify node shows up as a bad
   score rather than hiding behind its own verdict.

2. Nothing here touches the network. The whole harness reads frozen documents from
   eval/fixtures/docs, which is what lets it gate a pull request.
"""

import json
import re

from app.config import settings
from app.sources.fixtures import account_slug

_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "its", "it", "that", "this", "as", "at", "by",
    "from", "will", "their", "they", "said", "has", "have", "had",
}

# Fact types the brief always comments on, matching app/nodes/deliver.py.
REPORTABLE = ["funding", "leadership_change", "hiring", "product_launch",
              "market_expansion", "partnership", "layoffs"]


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in STOPWORDS and len(w) > 3}


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def load_gold(slug: str) -> dict:
    with open(settings.fixtures_dir / "accounts" / f"{slug}.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_manifest() -> dict:
    with open(settings.fixtures_dir / "_manifest.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def source_text_by_url(account: str) -> dict[str, str]:
    """The original documents, keyed by URL — the ground truth for groundedness."""
    path = settings.fixtures_dir / "docs" / f"{account_slug(account)}.json"
    with open(path, "r", encoding="utf-8") as fh:
        docs = json.load(fh)["documents"]
    return {d["url"]: normalise(d["text"]) for d in docs}


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def match_facts(extracted: list[dict], gold: list[dict]) -> tuple[int, list[dict], list[dict]]:
    """A fact matches a gold entry when the type agrees and every gold keyword
    appears in the statement. Returns (matches, unmatched_extracted, missed_gold)."""
    remaining = list(gold)
    matched = 0
    unmatched: list[dict] = []

    for fact in extracted:
        statement = normalise(fact.get("statement", ""))
        hit = None
        for candidate in remaining:
            if candidate["type"] != fact.get("type"):
                continue
            if all(normalise(kw) in statement for kw in candidate["keywords"]):
                hit = candidate
                break
        if hit:
            remaining.remove(hit)
            matched += 1
        else:
            unmatched.append(fact)

    return matched, unmatched, remaining


def groundedness(facts: list[dict], sources: dict[str, str]) -> tuple[float, list[dict]]:
    """Is each fact actually in the document it cites? Checked independently."""
    if not facts:
        return 1.0, []

    grounded = 0
    failures: list[dict] = []

    for fact in facts:
        document = sources.get(fact.get("source_url", ""), "")
        quote = normalise(fact.get("quote", ""))

        if not document:
            failures.append({"statement": fact.get("statement"), "why": "cited URL is not a source document"})
            continue

        if quote and quote in document:
            grounded += 1
            continue

        # No verbatim quote: fall back to requiring the claim's content words to
        # all be present in the cited document.
        claim = content_words(fact.get("statement", ""))
        if claim and claim <= content_words(document):
            grounded += 1
        else:
            missing = sorted(claim - content_words(document))[:6]
            failures.append(
                {"statement": fact.get("statement"), "why": f"not supported by cited source; missing {missing}"}
            )

    return round(grounded / len(facts), 4), failures


def retrieval_hit_rate(retrieval_by_type: dict, gold: list[dict]) -> float:
    """For each gold fact, did its source document make the top-k for that type?"""
    if not gold:
        return 1.0

    hits = 0
    for entry in gold:
        returned = retrieval_by_type.get(entry["type"], [])
        if any(chunk.get("url") == entry["source_url"] for chunk in returned):
            hits += 1
    return round(hits / len(gold), 4)


def correct_abstention(brief: dict, gold: dict) -> float:
    """Did it own up to what it could not find?

    For an account with no public footprint at all, the only correct behaviour is
    zero facts. Otherwise we check that every signal type absent from the gold set
    was reported as a gap.
    """
    gaps_text = normalise(" ".join(brief.get("gaps", [])))

    if gold.get("expect_abstention"):
        return 1.0 if not brief.get("facts") else 0.0

    gold_types = {entry["type"] for entry in gold.get("gold_facts", [])}
    expected = [t for t in REPORTABLE if t not in gold_types]
    if not expected:
        return 1.0

    reported = sum(1 for t in expected if t.replace("_", " ") in gaps_text)
    return round(reported / len(expected), 4)


def schema_valid(brief: dict) -> bool:
    from pydantic import ValidationError

    from app.schemas.brief import AccountBrief

    try:
        AccountBrief(**brief)
        return True
    except ValidationError:
        return False
