"""Node 1 — collect public documents about the company.

Two sources, picked by SOURCE_MODE:
  fixture  frozen documents on disk, no network  (default; what CI uses)
  web      Tavily search + page fetch, cached to .cache/
"""

from app.sources import clean, fixtures, web
from app.state import RunState


def ingest(state: RunState) -> dict:
    log = state["log"]
    log.start("ingest")

    mode = state.get("source_mode", "fixture")
    account = state["account"]

    if mode == "web":
        documents = web.fetch(account, state.get("domain") or None)
        if not documents:
            log.warn("ingest", "web source returned nothing, falling back to fixtures")
            documents = fixtures.fetch(account)
    else:
        documents = fixtures.fetch(account)

    # Strip navigation, cookie notices and truncated boilerplate before anything
    # is indexed. On fixtures this is a no-op; on the live web it is the difference
    # between facts and page furniture.
    raw_count = len(documents)
    documents, emptied = clean.clean_documents(documents)
    if emptied:
        log.warn("ingest", "documents dropped as boilerplate-only", dropped=emptied)

    errors = list(state.get("errors", []))
    if not documents:
        errors.append(f"No usable public documents found for '{account}'.")
        log.warn("ingest", "no documents found", account=account)

    log.finish("ingest", documents=len(documents), fetched=raw_count, mode=mode)
    return {"documents": documents, "errors": errors}
