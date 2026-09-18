"""Two embedders behind one interface.

NemotronEmbedder  nvidia/nemotron-3-embed-1b via the LangChain wrapper. The wrapper
                  sends input_type=passage when indexing and input_type=query when
                  searching. Getting that backwards silently wrecks retrieval
                  accuracy, which is exactly why we let the wrapper do it.

LexicalEmbedder   A hashing bag-of-words embedder. No API key, no network,
                  deterministic. It exists for two reasons: the pipeline and the
                  eval harness must run in CI without secrets, AND it gives the
                  eval a lexical baseline to compare Nemotron against. If the
                  neural embeddings do not beat this, they are not earning their
                  place in the system.
"""

import hashlib
import json
import re
import threading

import numpy as np

from app.config import settings

LEXICAL_DIMENSIONS = 512
_WORD = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------------------
# embedding cache
# ---------------------------------------------------------------------------
# Every run embeds the same nine retrieval queries and, on a retry, the same
# document chunks a second time. Over an eval that is hundreds of identical API
# calls against a rate-limited free endpoint. Text is immutable and embeddings are
# deterministic, so this is safe to cache forever — keyed by model, input type and
# a hash of the text, persisted to .cache/embeddings.json.
_LOCK = threading.Lock()
_CACHE: dict[str, list[float]] | None = None


def _cache_file():
    return settings.cache_dir / "embeddings.json"


def _load_cache() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            with open(_cache_file(), "r", encoding="utf-8") as fh:
                _CACHE = json.load(fh)
        except Exception:                                   # noqa: BLE001
            _CACHE = {}
    return _CACHE


def _save_cache() -> None:
    try:
        with open(_cache_file(), "w", encoding="utf-8") as fh:
            json.dump(_CACHE or {}, fh)
    except Exception:                                       # noqa: BLE001
        pass                                                # a cache miss is not an error


def _key(model: str, kind: str, text: str) -> str:
    return f"{model}:{kind}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:32]}"


def cache_stats() -> dict:
    return {"entries": len(_load_cache()), "file": str(_cache_file())}


class LexicalEmbedder:
    """Feature-hashed word and bigram counts, L2-normalised."""

    name = "lexical"
    dimensions = LEXICAL_DIMENSIONS

    def _vector(self, text: str) -> list[float]:
        words = _WORD.findall(text.lower())
        grams = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]

        vec = np.zeros(self.dimensions, dtype=np.float32)
        for gram in grams:
            digest = hashlib.md5(gram.encode()).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[bucket] += sign

        norm = float(np.linalg.norm(vec))
        return (vec / norm).tolist() if norm else vec.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class NemotronEmbedder:
    """nvidia/nemotron-3-embed-1b through langchain-nvidia-ai-endpoints."""

    name = "nemotron"
    dimensions = 2048          # reported by the model; only used for display

    def __init__(self) -> None:
        from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

        self.model_id = settings.model_embed
        self._inner = NVIDIAEmbeddings(
            model=settings.model_embed,
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            truncate="END",          # inputs over 4096 tokens are trimmed, not rejected
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Only send the texts we have not embedded before, in their original order."""
        cache = _load_cache()
        out: list[list[float] | None] = [None] * len(texts)
        missing: list[int] = []

        for i, text in enumerate(texts):
            hit = cache.get(_key(self.model_id, "passage", text))
            if hit is None:
                missing.append(i)
            else:
                out[i] = hit

        if missing:
            fresh = self._inner.embed_documents([texts[i] for i in missing])
            with _LOCK:
                for i, vector in zip(missing, fresh):
                    out[i] = vector
                    cache[_key(self.model_id, "passage", texts[i])] = vector
                _save_cache()

        return [v for v in out if v is not None]

    def embed_query(self, text: str) -> list[float]:
        cache = _load_cache()
        key = _key(self.model_id, "query", text)
        hit = cache.get(key)
        if hit is not None:
            return hit

        vector = self._inner.embed_query(text)         # sends input_type=query
        with _LOCK:
            cache[key] = vector
            _save_cache()
        return vector


def get_embedder(backend: str | None = None):
    """Pick an embedder. Falls back to lexical when there is no API key."""
    backend = backend or settings.embed_backend

    if backend == "nemotron":
        if not settings.has_nvidia_key:
            return LexicalEmbedder()
        return NemotronEmbedder()

    return LexicalEmbedder()
