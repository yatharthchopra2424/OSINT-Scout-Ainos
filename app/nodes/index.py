"""Node 2 — chunk the documents and put them in the vector database.

Each chunk keeps the URL of the page it came from. That is what makes every fact
citable later without a second lookup.
"""

from app.rag.chunker import chunk_documents
from app.rag.store import build_store
from app.state import RunState


def index(state: RunState) -> dict:
    log = state["log"]
    log.start("index")

    chunks = chunk_documents(state.get("documents", []))
    store, note = build_store(
        collection_name=f"run_{state['run_id']}".replace("-", "_"),
        embed_backend=state.get("embed_backend"),
    )
    if note:
        log.warn("index", note)

    count = store.add(chunks)

    log.finish(
        "index",
        chunks=count,
        vector_backend=getattr(store, "backend", "?"),
        embedder=getattr(store.embedder, "name", "?"),
    )
    return {"chunks": chunks, "store": store, "chunks_indexed": count}
