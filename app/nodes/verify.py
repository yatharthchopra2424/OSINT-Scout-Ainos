"""Node 5 — the gate. This is the node that makes the tool worth trusting.

Every extracted fact is checked against the text that was actually retrieved.
A fact that nothing supports is DROPPED, not softened — and the dropped ones are
kept and shown in the UI, because "here is what I threw away and why" is the part
that makes a reviewer believe the rest.

Two modes, matching the extractor:
  lexical    quote-and-token overlap against retrieved chunks. Deterministic, free.
  llm-batch  nemotron-3.5-lightning judges every fact in ONE call.

The batch matters. Judging one fact per call was 89% of a run's wall time, because
each call re-sent the same sources and then waited on a rate-limited endpoint. The
sources now go in once and every claim is judged against them together — fewer
calls, and a judge that can see when a claim belongs to a different company
mentioned in the same text.
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


VERDICT_SCORES = {"SUPPORTED": 1.0, "PARTIAL": 0.6, "UNSUPPORTED": 0.0}


def _score_batch(facts: list[dict], chunks: list[dict], account: str) -> dict[int, tuple[float, str]]:
    """Judge every fact in ONE call.

    One call per fact was 89% of a run's wall time — the model spent most of its
    life waiting on a rate-limited endpoint, repeatedly re-reading the same
    sources. Here the sources go in once and every claim is judged against them
    together, which is both faster and slightly better grounded: the judge can
    see that a claim belongs to a different company mentioned in the text.

    Returns {index: (score, reason)}. An index missing from the reply is left out
    so the caller can fall back rather than silently assume anything.
    """
    sources = "\n\n".join(
        f"[{i}] {c.get('url', '')}\n{c['text']}" for i, c in enumerate(chunks[:16], start=1)
    ) or "(no source text)"
    claims = "\n".join(
        f"{i}. {f.get('statement', '')}" for i, f in enumerate(facts, start=1)
    )

    prompt = load_prompt("verify_batch.v1").format(
        sources=sources, claims=claims, account=account
    )
    reply = clients.call(clients.fast(max_tokens=2048), prompt)
    parsed = clients.first_json_object(str(reply.content))

    out: dict[int, tuple[float, str]] = {}
    for entry in (parsed or {}).get("verdicts", []):
        try:
            index = int(entry["id"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        verdict = str(entry.get("verdict", "")).strip().upper()
        if 0 <= index < len(facts) and verdict in VERDICT_SCORES:
            out[index] = (VERDICT_SCORES[verdict],
                          str(entry.get("reason", verdict))[:300] or verdict)
    return out


def verify(state: RunState) -> dict:
    log = state["log"]
    log.start("verify")

    chunks = state.get("retrieved", [])
    use_llm = clients.available() and state.get("extract_mode") == "llm"

    facts = state.get("facts", [])
    mode = "lexical"

    # One batched call for the whole fact set. Falls back per fact, never silently.
    batch: dict[int, tuple[float, str]] = {}
    if use_llm and facts:
        try:
            batch = _score_batch(facts, chunks, state.get("account", ""))
            mode = "llm-batch"
        except Exception as exc:                            # noqa: BLE001
            log.warn("verify", "batched judge failed, falling back", error=str(exc)[:200])

    missing = [i for i in range(len(facts)) if i not in batch]
    if use_llm and missing and batch:
        log.warn("verify", "judge skipped some claims, scoring those lexically",
                 missing=len(missing))

    def judge(index: int, fact: dict) -> dict:
        if index in batch:
            score, reason = batch[index]
        else:
            score, reason = _score_lexical(fact, _evidence_for(fact, chunks))
        return {
            **fact,
            "support_score": score,
            "supported": score >= settings.support_threshold,
            "reason": reason,
        }

    results = [judge(i, f) for i, f in enumerate(facts)]

    verified = [r for r in results if r["supported"]]
    dropped = [r for r in results if not r["supported"]]

    for fact in dropped:
        log.warn(
            "verify", "fact dropped",
            fact_type=fact.get("type"), score=fact["support_score"],
            statement=fact.get("statement", "")[:120],
        )

    log.finish(
        "verify",
        judge=mode, calls=1 if mode == "llm-batch" else 0,
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
