"""Throw away page furniture before it reaches the index.

Fixtures are clean prose. The live web is not: a fetched page is mostly navigation,
cookie notices, job-board chrome and truncated boilerplate. Left alone, the
extractor happily lifts "Just now save ## Walk-in || Customer Support Executive"
and calls it a hiring signal — and the verifier passes it, because that text really
does appear in the cited source.

That is the honest limit of the verify node: it checks a claim came from where it
says it came from, not that the claim is worth having. Cleaning the input is how
you fix that, not a better judge.

Everything here is deterministic and runs before any model sees the text.
"""

import re

# Markers that only appear in chrome, never in a sentence a journalist wrote.
NAV_MARKERS = re.compile(
    r"(\|\||##|\bImage \d+:|\bApply now\b|\bSign in\b|\bLog in\b|\bSubscribe\b|"
    r"\bCookie\b|\bAll rights reserved\b|\bPrivacy policy\b|\bTerms of service\b|"
    r"\bJust now\b|\bSave this job\b|\bView all\b|\bRead more\b|\bShare on\b)",
    re.I,
)

MIN_WORDS = 6
MIN_LETTER_RATIO = 0.72          # below this it is symbol soup, not prose

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def is_prose(sentence: str) -> bool:
    """Would a person recognise this as a sentence from an article?"""
    text = sentence.strip()
    if len(text.split()) < MIN_WORDS:
        return False

    # A fragment that starts mid-word is a truncated scrape: "ed by companies,
    # mined from state filings...". Real sentences start with a capital or a digit.
    first = text[0]
    if not (first.isupper() or first.isdigit()):
        return False

    if NAV_MARKERS.search(text):
        return False

    letters = sum(1 for c in text if c.isalpha() or c.isspace())
    return letters / len(text) >= MIN_LETTER_RATIO


def clean_text(text: str) -> str:
    """Keep only the sentences that read like prose."""
    normalised = re.sub(r"\s+", " ", text or "").strip()
    kept = [s for s in _SENTENCE.split(normalised) if is_prose(s)]
    return " ".join(kept)


def clean_documents(documents: list[dict]) -> tuple[list[dict], int]:
    """Clean every document, drop any left with nothing. Returns (docs, dropped)."""
    cleaned: list[dict] = []
    dropped = 0

    for doc in documents:
        text = clean_text(doc.get("text", ""))
        if text:
            cleaned.append({**doc, "text": text})
        else:
            dropped += 1

    return cleaned, dropped
