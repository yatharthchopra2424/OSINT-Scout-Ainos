"""The vector database, behind one small interface.

Chroma is the default. NumpyStore is a ~30-line in-memory fallback so the app
still runs if chromadb will not install on a given machine, and so the eval
harness has no external dependency. Swapping in pgvector or Qdrant later means
writing one more class with these three methods.
"""

import numpy as np

from app.config import settings
from app.rag.embeddings import get_embedder


class NumpyStore:
    """Cosine similarity over an in-memory matrix. Small, obvious, no dependencies."""

    backend = "numpy"

    def __init__(self, embedder) -> None:
        self.embedder = embedder
        self.chunks: list[dict] = []
        self.matrix: np.ndarray | None = None

    def add(self, chunks: list[dict]) -> int:
        if not chunks:
            return 0
        vectors = self.embedder.embed_documents([c["text"] for c in chunks])
        self.chunks = chunks
        self.matrix = np.array(vectors, dtype=np.float32)
        return len(chunks)

    def search(self, query: str, k: int) -> list[dict]:
        if self.matrix is None or not len(self.chunks):
            return []
        q = np.array(self.embedder.embed_query(query), dtype=np.float32)
        scores = self.matrix @ q / (
            np.linalg.norm(self.matrix, axis=1) * np.linalg.norm(q) + 1e-9
        )
        order = np.argsort(-scores)[:k]
        return [{**self.chunks[i], "score": round(float(scores[i]), 4)} for i in order]


class ChromaStore:
    """Chroma with our own embedder — we pass vectors in, Chroma just indexes them."""

    backend = "chroma"
    KEEP_COLLECTIONS = 40          # runs worth of indexes to retain on disk

    def __init__(self, embedder, collection_name: str) -> None:
        import chromadb

        self.embedder = embedder
        client = chromadb.PersistentClient(path=str(settings.chroma_dir))

        # Each run gets its own collection, so runs stay independent and a past
        # run's index can still be queried. Without a prune they would pile up
        # forever, so keep a rolling window and drop the oldest.
        self._prune(client)

        try:
            client.delete_collection(collection_name)
        except Exception:                                  # noqa: BLE001
            pass
        self.collection = client.create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )

    def _prune(self, client) -> None:
        try:
            names = sorted(c.name for c in client.list_collections())
        except Exception:                                  # noqa: BLE001
            return
        for name in names[: max(0, len(names) - self.KEEP_COLLECTIONS)]:
            try:
                client.delete_collection(name)
            except Exception:                              # noqa: BLE001
                pass

    def add(self, chunks: list[dict]) -> int:
        if not chunks:
            return 0
        self.collection.add(
            ids=[c["id"] for c in chunks],
            documents=[c["text"] for c in chunks],
            embeddings=self.embedder.embed_documents([c["text"] for c in chunks]),
            metadatas=[
                {"url": c["url"], "title": c["title"], "published": c["published"]}
                for c in chunks
            ],
        )
        return len(chunks)

    def search(self, query: str, k: int) -> list[dict]:
        result = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query)], n_results=k
        )
        hits: list[dict] = []
        for i, doc in enumerate(result["documents"][0]):
            meta = result["metadatas"][0][i]
            distance = result["distances"][0][i]
            hits.append(
                {
                    "id": result["ids"][0][i],
                    "text": doc,
                    "url": meta.get("url", ""),
                    "title": meta.get("title", ""),
                    "published": meta.get("published", ""),
                    "score": round(1.0 - float(distance), 4),   # cosine distance -> similarity
                }
            )
        return hits


def build_store(collection_name: str, embed_backend: str | None = None):
    """Make a store. Falls back to numpy with a note if Chroma is unavailable."""
    embedder = get_embedder(embed_backend)

    if settings.vector_backend == "chroma":
        try:
            return ChromaStore(embedder, collection_name), None
        except Exception as exc:                           # noqa: BLE001
            return NumpyStore(embedder), f"chroma unavailable, using numpy store ({exc})"

    return NumpyStore(embedder), None
