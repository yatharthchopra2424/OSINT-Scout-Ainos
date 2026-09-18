"""Node 4 — turn retrieved text into structured, cited facts.

Two modes, and the eval harness runs both so you can see what the model is worth:

  baseline  keyword + sentence matching. No API key, deterministic, fast.
            This is the control. If the LLM cannot beat it, it is not earning
            its place in the system.

  llm       nemotron-3-super-120b-a12b with structured output, constrained to the
            Fact schema so it physically cannot return a shape we did not ask for.
"""

import re

from app.llm import clients
from app.prompts import load as load_prompt
from app.schemas.brief import FACT_TYPES, FactList
from app.state import RunState

MAX_CONTEXT_CHUNKS = 14

# The control extractor. One phrase list per fact type.
KEYWORDS: dict[str, list[str]] = {
    "funding": ["raised", "funding", "series a", "series b", "series c", "investment round",
                "valuation", "led the round", "secured"],
    "leadership_change": ["appointed", "named as", "joins as", "steps down", "stepping down",
                          "new chief", "promoted to", "takes over as", "succeeds"],
    "hiring": ["hiring", "open roles", "open positions", "vacancies", "recruiting",
               "headcount", "job openings", "is recruiting"],
    "product_launch": ["launched", "launches", "unveiled", "introduces", "introduced",
                       "rolled out", "went live"],
    "market_expansion": ["expands", "expanding", "expansion", "new market", "enters the",
                         "opening in", "new route", "entering"],
    "partnership": ["partnership", "partners with", "partnered with", "alliance",
                    "signed an agreement", "teams up", "joint venture"],
    "layoffs": ["layoffs", "laid off", "job cuts", "redundanc", "restructuring",
                "cut roles", "reduce headcount"],
    "tech_stack": ["built on", "migrated to", "runs on", "uses", "deployed",
                   "platform is", "standardised on", "standardized on"],
    "company_profile": ["is a ", "provides", "operates", "headquartered", "founded in"],
}

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_LONG_DATE = re.compile(
    r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+(20\d{2})\b",
    re.I,
)
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]


def _date_in(text: str) -> str | None:
    match = _ISO_DATE.search(text)
    if match:
        return match.group(1)
    match = _LONG_DATE.search(text)
    if match:
        day, month, year = match.group(1), match.group(2).lower(), match.group(3)
        return f"{year}-{_MONTHS.index(month) + 1:02d}-{int(day):02d}"
    return None


def _build_context(chunks: list[dict]) -> str:
    """Numbered, URL-labelled context so the model can cite what it used."""
    blocks = []
    for i, chunk in enumerate(chunks[:MAX_CONTEXT_CHUNKS], start=1):
        published = chunk.get("published") or "undated"
        blocks.append(
            f"[{i}] source_url: {chunk['url']}\n"
            f"    title: {chunk.get('title', '')}\n"
            f"    published: {published}\n"
            f"    text: {chunk['text']}"
        )
    return "\n\n".join(blocks)


def _extract_baseline(state: RunState) -> list[dict]:
    """Keyword control extractor. Never invents: the quote IS the sentence."""
    facts: list[dict] = []
    seen: set[tuple] = set()

    for fact_type, hits in state.get("retrieval_by_type", {}).items():
        phrases = KEYWORDS.get(fact_type, [])
        found_this_type = False

        # Hits are already ordered best-first, so the control extractor takes the
        # single best-supported sentence per fact type and stops. One claim per
        # signal keeps it comparable to the gold set and stops it flooding the
        # brief with near-duplicates.
        for chunk in hits:
            if found_this_type:
                break
            for sentence in _SENTENCE.split(chunk["text"]):
                sentence = sentence.strip()
                if len(sentence) < 30:
                    continue
                lowered = sentence.lower()
                if not any(phrase in lowered for phrase in phrases):
                    continue

                key = (fact_type, sentence[:80])
                if key in seen:
                    continue
                seen.add(key)

                facts.append(
                    {
                        "type": fact_type,
                        "statement": sentence,
                        "event_date": _date_in(sentence) or (chunk.get("published") or None),
                        "source_url": chunk["url"],
                        "quote": sentence,
                    }
                )
                found_this_type = True
                break
    return facts


# Shown to the model when the endpoint refuses guided_json and we have to ask for
# JSON in the prompt instead. Kept next to the schema it mirrors.
FACTLIST_SHAPE = (
    '{"facts": [{"type": "<one of: ' + " | ".join(FACT_TYPES) + '>", '
    '"statement": "<one factual sentence>", '
    '"event_date": "<YYYY-MM-DD, or null if the source gives no date>", '
    '"source_url": "<the source_url this came from>", '
    '"quote": "<the sentence from the source that supports it>"}]}'
)


def _extract_llm(state: RunState) -> list[dict]:
    """Structured extraction with Nemotron Super.

    Goes through clients.structured() rather than calling with_structured_output
    directly: the NIM endpoint rejects guided_json on some backend instances with
    a 400, intermittently, for the same model and key. The fallback asks for the
    same shape in the prompt and validates the reply against FactList either way.
    """
    prompt = load_prompt("extract.v1").format(
        account=state["account"],
        context=_build_context(state.get("retrieved", [])),
    )
    result = clients.structured(
        clients.reasoning(max_tokens=4096),      # room for several facts plus thinking
        prompt,
        FactList,
        FACTLIST_SHAPE,
    )
    return [fact.model_dump() for fact in result.facts]


def _backfill_dates(facts: list[dict], chunks: list[dict]) -> tuple[list[dict], int]:
    """Fill in event_date the model left out, from the text it cited.

    The model is asked for a date and often returns null anyway — and a fact with
    no date cannot fire a time-windowed rule, so an account with a fresh funding
    round silently scores zero. Observed turning Northwind from High to Low.

    The date is not a judgement call: it is either written in the sentence or it
    is the publication date of the page the fact came from. So the code takes it
    rather than asking again.
    """
    published_by_url = {c["url"]: c.get("published") for c in chunks if c.get("url")}
    filled = 0

    for fact in facts:
        if fact.get("event_date"):
            continue
        found = (_date_in(fact.get("statement", ""))
                 or _date_in(fact.get("quote", ""))
                 or published_by_url.get(fact.get("source_url", "")))
        if found:
            fact["event_date"] = found
            filled += 1

    return facts, filled


def extract(state: RunState) -> dict:
    log = state["log"]
    log.start("extract")

    mode = state.get("extract_mode", "baseline")
    errors = list(state.get("errors", []))

    if mode == "llm" and clients.available():
        try:
            facts = _extract_llm(state)
        except Exception as exc:                            # noqa: BLE001
            log.error("extract", "llm extraction failed, using baseline", error=str(exc)[:300])
            errors.append(f"LLM extraction failed: {exc}")
            facts = _extract_baseline(state)
            mode = "baseline"
    else:
        if mode == "llm":
            log.warn("extract", "no NVIDIA_API_KEY, using baseline extractor")
            mode = "baseline"
        facts = _extract_baseline(state)

    facts, filled = _backfill_dates(facts, state.get("retrieved", []))
    if filled:
        log.info("extract", "back-filled event_date from cited text", facts=filled)

    undated = sum(1 for f in facts if not f.get("event_date"))
    if undated:
        log.warn("extract", "facts with no date cannot fire time-windowed rules",
                 undated=undated)

    log.finish("extract", mode=mode, facts=len(facts), dated=len(facts) - undated)
    return {"facts": facts, "extract_mode": mode, "errors": errors}
