"""Split documents into overlapping chunks, keeping the source URL on each one.

The source URL riding along with every chunk is what makes citation possible
later: when the verify node finds the chunk that supports a fact, it already
knows which page the fact came from.
"""

import re

CHUNK_CHARS = 700
OVERLAP_CHARS = 120

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def split_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Sentence-aware chunking: never cut a sentence in half if we can avoid it."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    sentences = _SENTENCE.split(text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= size:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            # Carry the tail of the last chunk forward so a fact spanning the
            # boundary still has its context.
            current = (current[-overlap:] + " " + sentence).strip() if current else sentence

    if current:
        chunks.append(current)
    return chunks


def chunk_documents(documents: list[dict]) -> list[dict]:
    """documents: [{url, title, published, text}] -> [{id, text, url, title, published}]"""
    chunks: list[dict] = []
    for doc_index, doc in enumerate(documents):
        for chunk_index, piece in enumerate(split_text(doc.get("text", ""))):
            chunks.append(
                {
                    "id": f"d{doc_index}c{chunk_index}",
                    "text": piece,
                    "url": doc.get("url", ""),
                    "title": doc.get("title", ""),
                    "published": doc.get("published", ""),
                }
            )
    return chunks
