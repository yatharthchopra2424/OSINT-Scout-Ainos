"""Node 3 — semantic search, once per kind of fact we are looking for.

Rather than one vague query, we run a focused query per fact type and union the
results. That keeps recall high for the rare signals (layoffs, leadership changes)
which a single generic query tends to bury.

On a retry the graph comes back here with a larger k.
"""

from app.config import settings
from app.state import RunState

# One retrieval query per fact type the scoring rules care about.
QUERIES: dict[str, str] = {
    "company_profile": "what the company does, its size, markets and structure",
    "funding": "funding round investment raised capital valuation",
    "leadership_change": "appointed new chief executive officer CIO CTO joins steps down",
    "hiring": "hiring open roles vacancies headcount growth recruiting",
    "product_launch": "launches new product service platform release",
    "market_expansion": "expands into new market country region route network",
    "partnership": "partnership alliance agreement integration signs deal with",
    "layoffs": "layoffs job cuts restructuring cost reduction redundancies",
    "tech_stack": "technology platform software vendor system uses built on",
}


def retrieve(state: RunState) -> dict:
    log = state["log"]
    log.start("retrieve")

    store = state["store"]
    k = state.get("k") or settings.retrieval_k

    by_type: dict[str, list[dict]] = {}
    pool: dict[str, dict] = {}

    for fact_type, query in QUERIES.items():
        hits = store.search(query, k) if store else []
        by_type[fact_type] = hits
        for hit in hits:
            pool[hit["id"]] = hit            # de-duplicate across queries

    retrieved = sorted(pool.values(), key=lambda c: -c.get("score", 0))

    log.finish("retrieve", k=k, queries=len(QUERIES), unique_chunks=len(retrieved))
    return {"retrieved": retrieved, "retrieval_by_type": by_type, "k": k}
