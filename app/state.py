"""The object that flows through the graph.

Each node reads what it needs and returns only the keys it changed. Having one
explicit state shape means you can look at any node in isolation and know exactly
what it is given and what it owes back.
"""

from typing import Any, TypedDict


class RunState(TypedDict, total=False):
    # --- set when the run starts --------------------------------------------
    run_id: str
    account: str
    account_id: str
    domain: str
    source_mode: str            # fixture | web
    embed_backend: str          # lexical | nemotron
    extract_mode: str           # llm | baseline
    today: str                  # ISO date the scoring rules are evaluated against
    log: Any                    # RunLog

    # --- ingest / index ------------------------------------------------------
    documents: list[dict]
    chunks: list[dict]
    store: Any
    chunks_indexed: int

    # --- retrieve ------------------------------------------------------------
    retrieved: list[dict]               # de-duplicated chunks handed to extract
    retrieval_by_type: dict             # fact_type -> hits, for the UI and eval
    k: int

    # --- extract / verify ----------------------------------------------------
    facts: list[dict]
    verified: list[dict]
    dropped: list[dict]
    retries: int

    # --- score / diff / deliver ---------------------------------------------
    score: dict
    delta: dict
    brief: dict
    markdown: str
    errors: list[str]
