"""The agent, as a graph.

  ingest -> index -> retrieve -> extract -> verify -> score -> diff -> deliver
                        ^                      |
                        |                      | too few verified facts
                        +------- widen --------+   (widen k, once)

Three of the eight nodes involve no model at all — score, diff and deliver are
plain Python. That split is deliberate: the model reads and extracts, the code
decides and reports.
"""

from datetime import date

from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.nodes import (deliver, diff, extract, index, ingest, needs_retry,
                       retrieve, score, verify, widen)
from app.ops.run_log import RunLog, new_run_id
from app.sources.fixtures import account_slug
from app.state import RunState


def build_graph():
    graph = StateGraph(RunState)

    graph.add_node("ingest", ingest)
    graph.add_node("index", index)
    graph.add_node("retrieve", retrieve)
    graph.add_node("extract", extract)
    graph.add_node("verify", verify)
    graph.add_node("widen", widen)
    graph.add_node("score", score)
    graph.add_node("diff", diff)
    graph.add_node("deliver", deliver)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "index")
    graph.add_edge("index", "retrieve")
    graph.add_edge("retrieve", "extract")
    graph.add_edge("extract", "verify")

    # The one loop in the system, and it can only go round once.
    graph.add_conditional_edges(
        "verify", needs_retry, {"retry": "widen", "continue": "score"}
    )
    graph.add_edge("widen", "retrieve")

    graph.add_edge("score", "diff")
    graph.add_edge("diff", "deliver")
    graph.add_edge("deliver", END)

    return graph.compile()


COMPILED = build_graph()

# Rendered once here so the UI and the README can show the same picture.
GRAPH_SHAPE = [
    {"node": "ingest", "does": "collect public documents", "model": "none / search API"},
    {"node": "index", "does": "chunk and embed into the vector DB", "model": "nemotron-3-embed-1b"},
    {"node": "retrieve", "does": "semantic search, one query per fact type", "model": "nemotron-3-embed-1b"},
    {"node": "extract", "does": "structured facts with citations", "model": "nemotron-3-super-120b"},
    {"node": "verify", "does": "drop anything the sources do not support", "model": "nemotron-3.5-lightning"},
    {"node": "score", "does": "apply rules.yml", "model": "none — pure Python"},
    {"node": "diff", "does": "compare against the previous run", "model": "none — pure Python"},
    {"node": "deliver", "does": "write brief.json, brief.md and the log", "model": "none — pure Python"},
]


def run_account_state(
    name: str,
    domain: str = "",
    source_mode: str | None = None,
    extract_mode: str = "llm",
    embed_backend: str | None = None,
    today: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Run the pipeline and return the FULL final state.

    The eval harness uses this because it needs to see inside the run — which
    chunks retrieval returned, what the extractor produced before the gate — not
    just the brief that came out the end.

    `run_id` can be supplied by the caller so the API can hand it to the browser
    before the work starts, and the browser can then follow the run's log live.
    """
    account_id = account_slug(name)
    run_id = run_id or new_run_id(account_id)
    log = RunLog(run_id)

    initial: RunState = {
        "run_id": run_id,
        "account": name,
        "account_id": account_id,
        "domain": domain,
        "source_mode": source_mode or settings.source_mode,
        "embed_backend": embed_backend or settings.embed_backend,
        "extract_mode": extract_mode,
        "today": today or date.today().isoformat(),
        "log": log,
        "k": settings.retrieval_k,
        "retries": 0,
        "errors": [],
    }

    log.info("run", "started", account=name, source_mode=initial["source_mode"],
             extract_mode=extract_mode, embed_backend=initial["embed_backend"])

    final = COMPILED.invoke(initial)

    log.info("run", "completed", facts=len(final.get("verified", [])),
             score=final.get("score", {}).get("total", 0))

    # Write the activity entry here rather than in a node: every caller — the API,
    # the nightly job, the eval — goes through this function, so the lead timeline
    # stays complete without anyone remembering to log.
    try:
        from app.ops import leads
        leads.record_run(final["brief"])
    except Exception as exc:                                # noqa: BLE001
        log.warn("run", "could not update lead state", error=str(exc)[:200])

    return final


def run_account(**kwargs) -> dict:
    """Run the pipeline for one company and return the finished brief."""
    return run_account_state(**kwargs)["brief"]
