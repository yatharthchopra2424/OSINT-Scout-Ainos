"""The style checker: does this read like a person wrote it?

A note on what this is and is not.

This does NOT try to defeat AI-detection tools. Those detectors are unreliable in
both directions, gaming them is a moving target you lose, and a feature branded
"evade detection" is a liability in front of an enterprise buyer.

What it does instead is the thing that actually makes cold email land: it catches
the specific habits that make generated prose obvious and weak — stock openers,
consultant filler, hedging, tricolons, sentences nobody would say out loud — and
it checks the email contains real specifics (a number, a date, a name) drawn from
verified facts. Email that reads human reads human because it is specific and
short, not because it was laundered.

Every check is plain Python. No model, no API key, and the same text always gets
the same score.
"""

import re

# Openers that announce "a template starts here".
BANNED_OPENERS = [
    "i hope this email finds you well",
    "i hope this finds you well",
    "i hope you're doing well",
    "i hope you are doing well",
    "i hope this message finds you",
    "i trust this email finds you",
    "i wanted to reach out",
    "i am reaching out",
    "i'm reaching out",
    "my name is",
    "allow me to introduce",
    "i hope you don't mind me",
]

# Vocabulary that shows up far more in generated text than in email people send.
FILLER = {
    "leverage": "use",
    "utilize": "use",
    "utilise": "use",
    "synergy": "overlap",
    "synergies": "overlap",
    "seamless": "",
    "seamlessly": "",
    "robust": "",
    "cutting-edge": "",
    "state-of-the-art": "",
    "game-changer": "",
    "game-changing": "",
    "revolutionary": "",
    "unlock": "get",
    "unlocking": "getting",
    "delve": "look",
    "landscape": "market",
    "realm": "area",
    "tapestry": "",
    "testament": "sign",
    "pivotal": "key",
    "spearhead": "lead",
    "elevate": "improve",
    "empower": "help",
    "streamline": "simplify",
    "holistic": "",
    "bespoke": "custom",
    "myriad": "many",
    "plethora": "many",
    "navigate the": "handle the",
    "in today's": "",
    "fast-paced": "",
    "ever-evolving": "",
    "at the forefront": "",
    "resonate": "land",
}

HEDGES = [
    "i just wanted to", "just wanted to", "i was wondering if",
    "i thought i'd", "if that makes sense", "does that make sense",
    "i'd love to pick your brain", "quick question for you",
    "sorry to bother", "hope that's ok",
]

# "not only X but also Y" and friends — grammatical tics of generated prose.
TICS = [
    r"\bnot only\b.{0,60}\bbut also\b",
    r"\bit'?s worth noting\b",
    r"\bthat said,",
    r"\bneedless to say\b",
    r"\bin conclusion\b",
    r"\bfurthermore\b",
    r"\bmoreover\b",
    r"\badditionally,",
]

MAX_SENTENCE_WORDS = 26
# Cold email that gets replies is short. The floor is low on purpose — a tight
# 50-word email outperforms a padded 120-word one, so only flag genuinely thin.
TARGET_WORDS = (40, 125)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z0-9'’-]+")
_PROPER = re.compile(r"\b[A-Z][a-z]{2,}\b")
_NUMBER = re.compile(r"\b\d[\d,.]*\b")


def _flag(check: str, severity: int, message: str, evidence: str = "") -> dict:
    return {"check": check, "severity": severity, "message": message, "evidence": evidence}


def check(text: str, facts: list[dict] | None = None) -> dict:
    """Score a draft out of 100 and say exactly what is wrong with it."""
    facts = facts or []
    body = text or ""
    lowered = body.lower()
    words = _WORD.findall(body)
    sentences = [s.strip() for s in _SENTENCE.split(body.strip()) if s.strip()]

    flags: list[dict] = []

    # --- stock openers ------------------------------------------------------
    opening = " ".join(lowered.split())[:120]
    for phrase in BANNED_OPENERS:
        if phrase in opening:
            flags.append(_flag("opener", 18, "Opens with a stock phrase — cut it and start on the fact.", phrase))
            break

    # --- filler vocabulary --------------------------------------------------
    found_filler = [w for w in FILLER if re.search(rf"\b{re.escape(w)}\b", lowered)]
    if found_filler:
        flags.append(_flag(
            "filler", 6 * min(len(found_filler), 4),
            "Consultant vocabulary. Say the plain word or delete it.",
            ", ".join(found_filler[:6]),
        ))

    # --- hedging ------------------------------------------------------------
    found_hedge = [h for h in HEDGES if h in lowered]
    if found_hedge:
        flags.append(_flag("hedging", 8, "Hedging makes the ask easy to ignore.", ", ".join(found_hedge[:3])))

    # --- grammatical tics ---------------------------------------------------
    found_tics = [t for t in TICS if re.search(t, lowered)]
    if found_tics:
        flags.append(_flag("tics", 7, "Essay connectives — nobody writes these in email.", str(len(found_tics)) + " found"))

    # --- em dashes ----------------------------------------------------------
    dashes = body.count("—")
    if dashes >= 2:
        flags.append(_flag("em_dash", 8, f"{dashes} em dashes. One at most in a short email.", "—"))

    # --- sentence length ----------------------------------------------------
    long_ones = [s for s in sentences if len(_WORD.findall(s)) > MAX_SENTENCE_WORDS]
    if long_ones:
        flags.append(_flag(
            "sentence_length", 5 * min(len(long_ones), 3),
            f"{len(long_ones)} sentence(s) over {MAX_SENTENCE_WORDS} words. Split them.",
            long_ones[0][:90],
        ))

    # --- total length -------------------------------------------------------
    low, high = TARGET_WORDS
    if len(words) > high:
        flags.append(_flag("length", 12, f"{len(words)} words. Over {high} and it does not get read.", ""))
    elif len(words) < low:
        flags.append(_flag("length", 6, f"{len(words)} words — too thin to be worth a reply.", ""))

    # --- one ask ------------------------------------------------------------
    questions = body.count("?")
    if questions == 0:
        flags.append(_flag("ask", 10, "No question. There is nothing to reply to.", ""))
    elif questions > 2:
        flags.append(_flag("ask", 8, f"{questions} questions. Pick one.", ""))

    # --- specificity: the check that actually matters -----------------------
    numbers = _NUMBER.findall(body)
    propers = set(_PROPER.findall(body))
    fact_hits = sum(
        1 for f in facts
        if any(tok.lower() in lowered for tok in _PROPER.findall(f.get("statement", "")) if len(tok) > 3)
        or any(n in body for n in _NUMBER.findall(f.get("statement", "")))
    )
    if not numbers and not fact_hits:
        # The heaviest single penalty in the checker. An email with no filler and no
        # stock opener still fails if it could have been sent to anyone — being
        # generic is the actual problem, and clean grammar does not excuse it.
        flags.append(_flag(
            "specificity", 28,
            "Nothing specific in here. No number, no date, nothing from a verified fact — "
            "this email could have been sent to anyone.", "",
        ))
    elif fact_hits == 0:
        flags.append(_flag("specificity", 10, "Does not reference any verified fact about this account.", ""))

    # --- unverified numbers -------------------------------------------------
    # The heaviest check of all. A number in the email that appears in no verified
    # fact is a claim nobody checked — and in testing that is exactly how a
    # competitor's funding round ended up in an email to the wrong company.
    if facts:
        fact_numbers: set[str] = set()
        for f in facts:
            fact_numbers.update(_NUMBER.findall(f.get("statement", "")))
            fact_numbers.update(_NUMBER.findall(f.get("quote", "")))
            for part in re.split(r"[-/]", str(f.get("event_date") or "")):
                if part:
                    fact_numbers.add(part.lstrip("0") or part)

        # Meeting times and durations are the writer's own, not claims about the
        # company: "Tuesday at 10 am" and "20 minutes" must not read as unsourced.
        scrubbed = re.sub(
            r"\b\d{1,2}([:.]\d{2})?\s*(am|pm)\b|\b\d{1,3}\s*(minutes?|mins?|hours?|hrs?)\b",
            " ", body, flags=re.I,
        )
        loose = [n for n in set(_NUMBER.findall(scrubbed))
                 if n not in fact_numbers and n.lstrip("0") not in fact_numbers
                 and len(n) > 1]
        if loose:
            flags.append(_flag(
                "unverified_claim", 30,
                "Contains numbers that appear in no verified fact. Every figure in a "
                "sent email has to trace to a source.", ", ".join(sorted(loose)[:5]),
            ))

    score = max(0, 100 - sum(f["severity"] for f in flags))

    return {
        "score": score,
        "verdict": "ready" if score >= 80 else "needs work" if score >= 55 else "rewrite it",
        "flags": sorted(flags, key=lambda f: -f["severity"]),
        "stats": {
            "words": len(words),
            "sentences": len(sentences),
            "longest_sentence": max((len(_WORD.findall(s)) for s in sentences), default=0),
            "em_dashes": dashes,
            "questions": questions,
            "numbers": len(numbers),
            "proper_nouns": len(propers),
            "facts_referenced": fact_hits,
        },
    }


def quick_fix(text: str) -> str:
    """Mechanical cleanup: drop stock openers, swap filler for the plain word.

    Deliberately conservative. It fixes what is unambiguously wrong and leaves
    everything else alone — a blunt find-and-replace cannot rewrite a sentence,
    and pretending otherwise would just produce different bad prose.
    """
    out = text or ""

    # Remove a stock opening sentence entirely.
    for phrase in BANNED_OPENERS:
        pattern = re.compile(rf"[^.!?\n]*{re.escape(phrase)}[^.!?]*[.!?]\s*", re.I)
        out = pattern.sub("", out, count=1)

    for word, replacement in FILLER.items():
        pattern = re.compile(rf"\b{re.escape(word)}\b", re.I)
        out = pattern.sub(replacement, out)

    for hedge in HEDGES:
        out = re.sub(re.escape(hedge) + r"\s*", "", out, flags=re.I)

    out = out.replace("—", ",")
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:?!])", r"\1", out)
    out = re.sub(r",\s*,", ",", out)
    # Deleting a hedge mid-sentence leaves doubled punctuation behind ("chat??").
    out = re.sub(r"([?!.])[?!.]+", r"\1", out)
    out = re.sub(r"^[\s,;:]+", "", out, flags=re.M)
    out = re.sub(r"\n{3,}", "\n\n", out)

    # Re-capitalise anything a removal left mid-sentence.
    out = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
    return out.strip()
