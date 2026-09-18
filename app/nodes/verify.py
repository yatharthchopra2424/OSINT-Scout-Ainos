"""Node 5 — the gate. This is the node that makes the tool worth trusting.

Every extracted fact is checked against the text that was actually retrieved.
A fact that nothing supports is DROPPED, not softened — and the dropped ones are
kept and shown in the UI, because "here is what I threw away and why" is the part
that makes a reviewer believe the rest.

Two modes, matching the extractor:
  lexical  quote-and-token overlap against retrieved chunks. Deterministic, free.
  llm      nemotron-3.5-lightning judges each fact. One cheap call per fact.
"""

import re

from app.config import settings
from app.llm import clients
from app.prompts import load as load_prompt
from app.state import RunState

_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "been", "has", "have", "had", "its", "it", "that", "this",
    "as", "at", "by", "from", "will", "their", "they",
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


def _evidence_for(fact: dict, chunks: list[dict]) -> str:
    """The retrieved text from the same page the fact claims to come from."""
    same_url = [c["text"] for c in chunks if c.get("url") == fact.get("source_url")]
    return " ".join(same_url) if same_url else " ".join(c["text"] for c in chunks)


def _score_lexical(fact: dict, evidence: str) -> tuple[float, str]:
    """1.0 if the quote is present verbatim, otherwise token overlap of the claim."""
    haystack = re.sub(r"\s+", " ", evidence.lower())
    quote = re.sub(r"\s+", " ", (fact.get("quote") or "").lower()).strip()

    if quote and quote in haystack:
        return 1.0, "quote found verbatim in the retrieved source text"

    claim = _tokens(fact.get("statement", ""))
    if not claim:
        return 0.0, "empty statement"

    overlap = len(claim & _tokens(evidence)) / len(claim)
    return round(overlap, 3), f"{int(overlap * 100)}% of the claim's terms appear in the source"


def _score_llm(fact: dict, evidence: str) -> tuple[float, str]:
    prompt = load_prompt("verify.v1").format(
        statement=fact.get("statement", ""), evidence=evidence[:6000]
    )
    reply = str(clients.call(clients.fast(), prompt).content).strip()
    verdict = reply.split("\n")[0].strip().upper()
    reason = " ".join(reply.split("\n")[1:]).strip() or verdict

    if verdict.startswith("SUPPORTED"):
        return 1.0, reason
    if verdict.startswith("PARTIAL"):
        return 0.6, reason
    return 0.0, reason


def verify(state: RunState) -> dict:
    log = state["log"]
    log.start("verify")

    chunks = state.get("retrieved", [])
    use_llm = clients.available() and state.get("extract_mode") == "llm"

    verified: list[dict] = []
    dropped: list[dict] = []

    for fact in state.get("facts", []):
        evidence = _evidence_for(fact, chunks)

        if use_llm:
            try:
                score, reason = _score_llm(fact, evidence)
            except Exception as exc:                        # noqa: BLE001
                log.warn("verify", "llm judge failed, using lexical", error=str(exc)[:200])
                score, reason = _score_lexical(fact, evidence)
        else:
            score, reason = _score_lexical(fact, evidence)

        checked = {
            **fact,
            "support_score": score,
            "supported": score >= settings.support_threshold,
            "reason": reason,
        }
        (verified if checked["supported"] else dropped).append(checked)

        if not checked["supported"]:
            log.warn(
                "verify", "fact dropped",
                fact_type=fact.get("type"), score=score, statement=fact.get("statement", "")[:120],
            )

    log.finish(
        "verify",
        judge="llm" if use_llm else "lexical",
        kept=len(verified), dropped=len(dropped),
        threshold=settings.support_threshold,
    )
    return {"verified": verified, "dropped": dropped}


def needs_retry(state: RunState) -> str:
    """Conditional edge: if the gate kept almost nothing, widen k and search again.

    Only ever retries once — an agent that can loop forever is a bug, not a feature.
    """
    log = state["log"]

    if state.get("retries", 0) >= 1:
        return "continue"
    if not state.get("documents"):
        return "continue"                    # nothing to retry with
    if len(state.get("verified", [])) >= 3:
        return "continue"

    log.warn(
        "verify", "too few verified facts, retrying retrieval with a wider k",
        verified=len(state.get("verified", [])), next_k=settings.retrieval_k_retry,
    )
    return "retry"


def widen(state: RunState) -> dict:
    """Bump k and the retry counter before going back to retrieve."""
    return {"k": settings.retrieval_k_retry, "retries": state.get("retries", 0) + 1}
