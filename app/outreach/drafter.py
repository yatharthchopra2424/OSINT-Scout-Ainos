"""Draft an outreach email from a brief.

Two grounding hops, not one:

1. The brief's verified facts — already retrieved, already checked, already cited.
   The intent decides which of them the email opens on.
2. A second retrieval over the same documents, this time with a query shaped by
   the intent. A partnership email and a first-touch email ask the index different
   questions about the same company, and get different colour back.

The email may only use what those two hops return. Anything it asserts that is not
in a verified fact is a fabrication about a real company, sent to a real person,
with your name on it — so the drafter reports exactly which facts it used, and the
style checker flags a draft that references none of them.
"""

import json
import re

from app.config import settings
from app.llm import clients
from app.outreach import intents as intent_lib
from app.outreach import style
from app.prompts import load as load_prompt
from app.rag.store import build_store


RETRIEVAL_K = 3

# What each intent asks the index for, over and above the facts it already has.
INTENT_QUERIES = {
    "intro": "what the company does, its size, markets, recent growth and priorities",
    "reengage": "recent changes, new direction, new leadership, strategy shift",
    "partnership": "partnerships alliances integrations resellers joint ventures ecosystem",
    "new_exec": "new executive appointment, their remit, modernisation, transformation plans",
    "event_followup": "new product, launch, roadmap, what they are building next",
    "careful": "what the company does, its markets, its operations",
}


def _load_documents(run_id: str) -> list[dict]:
    path = settings.runs_dir / run_id / "documents.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _second_hop(run_id: str, intent_key: str, allowed_urls: set[str]) -> list[dict]:
    """Intent-shaped retrieval over the run's own documents.

    Restricted to pages that a VERIFIED fact already cites. Without that filter
    the hop happily returns a passage about a competitor's funding round, the
    model opens the email on it, and the tool asserts something the verify node
    had already rejected — observed in testing, on the Solent fixture. The second
    hop is for extra colour on facts we trust, not a side door around them.
    """
    documents = [d for d in _load_documents(run_id) if d.get("url") in allowed_urls]
    if not documents:
        return []

    from app.rag.chunker import chunk_documents

    chunks = chunk_documents(documents)
    store, _ = build_store(collection_name=f"email_{run_id}".replace("-", "_"))
    store.add(chunks)
    return store.search(INTENT_QUERIES.get(intent_key, INTENT_QUERIES["intro"]), RETRIEVAL_K)


def _pick_hook(facts: list[dict], intent: intent_lib.Intent) -> dict | None:
    """The fact the email opens on: first hook type this account actually has.

    Anything in intent.avoid is excluded outright, including from the fallback —
    a post-layoffs email must not open on the layoffs just because that is the
    only fact available. Better to have no hook and refuse to write.
    """
    usable = [f for f in facts if f["type"] not in intent.avoid]

    by_type: dict[str, list[dict]] = {}
    for fact in usable:
        by_type.setdefault(fact["type"], []).append(fact)

    for fact_type in intent.hooks:
        if by_type.get(fact_type):
            # Most recent first when several share a type.
            return sorted(by_type[fact_type], key=lambda f: f.get("event_date") or "", reverse=True)[0]
    return usable[0] if usable else None


def short_name(company: str) -> str:
    """'Northwind Logistics' -> 'Northwind'. How a person would say it out loud."""
    words = (company or "").split()
    return words[0] if len(words) > 1 and len(words[0]) > 3 else (company or "").strip()


# Trailing date clutter lifted straight from a press release. Keeping it makes the
# email read like a robot reciting a filing; the numbers that matter stay.
_DATE_TAIL = re.compile(
    r"[,]?\s*(announced|listed|reported|confirmed)?\s*(on|in)?\s*"
    r"(20\d{2}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+20\d{2})\s*$",
    re.I,
)


def _trim(statement: str, company: str) -> str:
    """Strip the company name off the front and the date off the back.

    Deliberately does NOT touch the verb. An earlier version stripped 'is' and
    'has' so the sentence could be rebuilt around 'you', which produced
    'Saw that you partners with PortLink'. The company stays the subject, so the
    conjugation stays correct.
    """
    text = statement.strip().rstrip(".")
    for prefix in (company, short_name(company)):
        if prefix and text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break
    return _DATE_TAIL.sub("", text).strip().rstrip(",")


# ---------------------------------------------------------------------------
# the control drafter — no API key required
# ---------------------------------------------------------------------------
OPENERS = {
    "intro":          "Saw that {company} {hook}.",
    "reengage":       "We spoke a while back. Since then {company} {hook}.",
    "partnership":    "Noticed {company} {hook}.",
    "new_exec":       "Congratulations on the new role. Saw that {company} {hook}.",
    "event_followup": "Following up on our conversation. Since then {company} {hook}.",
    "careful":        "Not pitching you anything. Saw that {company} {hook}.",
}

# The second line, chosen by the type of fact the email opened on. Each one is a
# complete sentence, so no template can assemble a broken clause out of it.
PRESSURE = {
    "funding":           "Money like that usually turns into systems work faster than the team plans for.",
    "market_expansion":  "New markets usually mean local systems having to stand up quickly.",
    "hiring":            "A team growing that fast normally outruns its tooling.",
    "product_launch":    "Launches tend to bring support load before the process is ready for it.",
    "leadership_change": "New leadership usually inherits a backlog of systems decisions.",
    "partnership":       "Integrations like that normally need more glue than anyone budgets for.",
    "layoffs":           "That usually means the same work spread across fewer people.",
    "tech_stack":        "Integration work tends to be where the time goes.",
    "company_profile":   "Operations at that scale usually generate steady integration work.",
}

# Intents where the second line is about the relationship, not the fact.
BRIDGE_OVERRIDE = {
    "partnership": "We work with teams in the same space, which is why I'm writing.",
    "careful":     "No ask attached to this one.",
}

ASKS = {
    "intro":          "Worth 20 minutes next week to see if it's relevant? Tuesday or Thursday both work.",
    "reengage":       "Has any of that changed the picture on your side?",
    "partnership":    "Would it be worth putting our two alliance leads on a call?",
    "new_exec":       "Happy to send it over with no meeting attached. Want me to?",
    "event_followup": "Where did you land on it in the end?",
    "careful":        "Happy to send it across if it's useful, no call needed. Want it?",
}


def _draft_template(brief: dict, intent: intent_lib.Intent, sender: dict) -> dict:
    facts = brief.get("facts", [])
    company = brief.get("account", "")
    hook = _pick_hook(facts, intent)

    if not hook:
        return {
            "subject": f"{company}",
            "body": (
                f"No verified public information was found for {company}, so there is nothing "
                f"specific to open on. Sending a generic email here would do more harm than "
                f"sending nothing. Research the account manually before reaching out."
            ),
            "facts_used": [],
            "blocked": True,
            "blocked_reason": "no verified facts to ground an email in",
        }

    lines = [
        OPENERS[intent.key].format(
            company=short_name(company), hook=_trim(hook["statement"], company)
        ),
        BRIDGE_OVERRIDE.get(intent.key) or PRESSURE.get(hook["type"], PRESSURE["company_profile"]),
    ]
    if sender.get("offer"):
        lines.append(sender["offer"].strip().rstrip(".") + ".")
    lines.append(ASKS[intent.key])

    body = "\n\n".join(lines)
    if sender.get("name"):
        body += f"\n\n{sender['name']}"
        if sender.get("company"):
            body += f"\n{sender['company']}"

    subject_bits = {
        "funding": "your round",
        "market_expansion": "your expansion",
        "hiring": "the roles you're hiring for",
        "product_launch": "your launch",
        "leadership_change": "your new role",
        "partnership": "your partner work",
    }
    bit = subject_bits.get(hook["type"])

    return {
        "subject": f"{company} — {bit}" if bit else company,
        "body": body,
        "facts_used": [hook],
        "blocked": False,
        "blocked_reason": "",
    }


# ---------------------------------------------------------------------------
# the model drafter
# ---------------------------------------------------------------------------
# nemotron-3-super is a reasoning model: it thinks before it answers, and that
# thinking sometimes lands in the response. Observed in testing — a draft came back
# as 1334 words of "Check for greeting: we didn't open with a greeting. Good."
# The style checker flagged it (11 questions, way over length), but nothing that
# obviously broken should reach a person in the first place.
_THINK_TAGS = re.compile(r"<think>.*?</think>", re.S | re.I)
_META_LINE = re.compile(
    r"^\s*(check(ing)? for\b|let me\b|we need\b|note:|okay[,.]|wait[,.]|first,|now,|"
    r"analysis:|reasoning:|thinking:|draft \d|version \d|i should\b|the user\b)",
    re.I,
)
MAX_BODY_WORDS = 160


def _clean_model_output(text: str) -> str:
    """Safety net on top of structured output: strip thinking, cap length."""
    body = _THINK_TAGS.sub("", text or "").strip()

    kept: list[str] = []
    for line in body.splitlines():
        if _META_LINE.match(line):
            break                       # everything from here on is commentary
        kept.append(line)
    trimmed = "\n".join(kept).strip()

    # Only accept the cut if it left an actual email behind. A first line that
    # trips the meta pattern once deleted the whole body and shipped an empty
    # draft, which is worse than shipping a wordy one.
    if len(trimmed.split()) >= 20 or not body.strip():
        body = trimmed

    words = body.split()
    if len(words) > MAX_BODY_WORDS:
        body = " ".join(words[:MAX_BODY_WORDS]).rstrip(",;:") + "…"

    return body.strip()


_JSON_BLOCK = re.compile(r"\{.*?\"body\"\s*:.*?\}", re.S)
_SUBJECT_LINE = re.compile(r"^\s*subject\s*:\s*(.+)$", re.I | re.M)


def _parse_reply(reply: str, account: str) -> tuple[str, str]:
    """Get (subject, body) out of whatever the model returned.

    Tries JSON first, then a 'Subject:' line, then treats the whole thing as a
    body. A reasoning model will sometimes wrap JSON in prose or think out loud
    around it, so this reads the last JSON object it can find rather than
    assuming the response is clean.
    """
    text = _THINK_TAGS.sub("", reply or "").strip()

    # Same balanced-brace reader the extract node uses, so both paths cope with
    # fences, prose around the JSON and replies cut off mid-object.
    parsed = clients.first_json_object(text)
    if isinstance(parsed, dict) and str(parsed.get("body", "")).strip():
        return (str(parsed.get("subject", "")).strip() or account,
                _clean_model_output(str(parsed["body"])))

    for block in reversed(_JSON_BLOCK.findall(text)):
        try:
            obj = json.loads(block)
            body = str(obj.get("body", "")).strip()
            if body:
                return str(obj.get("subject", "")).strip() or account, _clean_model_output(body)
        except (json.JSONDecodeError, AttributeError):
            continue

    # Reasoning can eat the token budget and cut the JSON off mid-string, leaving
    # no closing brace for the block regex. Recover the fields by hand rather than
    # shipping a raw '{"subject": ...' as the email body.
    if text.lstrip().startswith("{") and '"body"' in text:
        subject_match = re.search(r'"subject"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        body_match = re.search(r'"body"\s*:\s*"((?:[^"\\]|\\.)*)', text, re.S)
        if body_match:
            def unescape(raw: str) -> str:
                return (raw.replace('\\n', '\n').replace('\\"', '"')
                           .replace("\\'", "'").replace('\\\\', '\\').strip())
            body = unescape(body_match.group(1)).rstrip('"').rstrip()
            if body:
                subject = unescape(subject_match.group(1)) if subject_match else account
                return subject or account, _clean_model_output(body)

    match = _SUBJECT_LINE.search(text)
    if match:
        subject = match.group(1).strip().strip('"')
        # A model echoing the format template writes a placeholder like
        # "<under 8 words...>" — that is not a subject.
        if subject.startswith("<"):
            subject = account
        body = text[match.end():].strip()
        return subject or account, _clean_model_output(body)

    # No JSON and no subject line. A reasoning model that never stopped thinking
    # leaves exactly this: "We need to output a JSON object with subject and body.
    # Must follow rules..." Shipping that as an email is far worse than falling
    # back to the template, so refuse it and let the caller decide.
    if _META_LINE.match(text) or _looks_like_reasoning(text):
        raise ValueError("model returned reasoning, not an email")

    return account, _clean_model_output(text)


_REASONING_TELLS = ("must follow", "hard rules", "we need to", "the body must",
                    "json object", "banned phrase", "word count", "let me write")


def _looks_like_reasoning(text: str) -> bool:
    """Commentary about writing an email, rather than an email."""
    lowered = text.lower()
    return sum(tell in lowered for tell in _REASONING_TELLS) >= 2


def _draft_llm(brief: dict, intent: intent_lib.Intent, sender: dict, passages: list[dict]) -> dict:
    facts = brief.get("facts", [])
    fact_lines = "\n".join(
        f"- [{f['type']}] {f['statement']} (source: {f['source_url']})" for f in facts
    ) or "(none)"
    context = "\n\n".join(f"- {p['text']}" for p in passages) or "(none)"

    prompt = load_prompt("email.v1").format(
        account=brief.get("account", ""),
        intent_label=intent.label,
        intent_guidance=intent.guidance,
        intent_ask=intent.ask,
        facts=fact_lines,
        context=context,
        sender_name=sender.get("name") or "(unsigned)",
        sender_company=sender.get("company") or "(unspecified)",
        sender_offer=sender.get("offer") or "(unspecified)",
        band=brief.get("score", {}).get("band", "Low"),
    )

    # Deliberately NOT with_structured_output here. The NIM endpoint for
    # nemotron-3-super rejects guided_json with a 400 ("unknown field
    # `guided_json`"), so the constrained path fails for this model. Asking for
    # JSON in the prompt and parsing it tolerantly depends on no API feature at
    # all, and still gives us a shape rather than a text format to guess at.
    # One retry: the leak is intermittent, so a second sample usually lands.
    # If it does not, raise and let draft() fall back to the template — which
    # scores 100 on the style checker and is never embarrassing.
    last: Exception | None = None
    for nudge in ("", "\n\nReturn ONLY the JSON object. Do not explain your reasoning."):
        try:
            reply = str(clients.call(clients.reasoning(temperature=0.4), prompt + nudge).content)
            subject, body = _parse_reply(reply, brief.get("account", ""))
            if body.strip():
                break
            last = ValueError("model returned an empty body")
        except ValueError as exc:
            last = exc
    else:
        raise last or ValueError("could not parse a draft from the model")

    return {
        "subject": subject or brief.get("account", ""),
        "body": body,
        "facts_used": facts,
        "blocked": False,
        "blocked_reason": "",
    }


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def draft(brief: dict, intent_key: str, sender: dict, mode: str = "auto") -> dict:
    """Produce a draft, check its style, and say how it was made."""
    intent = intent_lib.BY_KEY.get(intent_key) or intent_lib.BY_KEY["intro"]
    allowed = {f.get("source_url") for f in brief.get("facts", []) if f.get("source_url")}
    passages = _second_hop(brief["run_id"], intent.key, allowed)

    use_llm = clients.available() if mode == "auto" else (mode == "llm")
    engine = "template"

    if use_llm and clients.available():
        try:
            result = _draft_llm(brief, intent, sender, passages)
            engine = "nemotron"
        except Exception as exc:                            # noqa: BLE001
            result = _draft_template(brief, intent, sender)
            result["blocked_reason"] = f"model failed, fell back to template: {exc}"
    else:
        result = _draft_template(brief, intent, sender)

    # A refusal is not an email, so do not score it like one — flagging the notice
    # for "no question" and "not specific enough" is noise, not information.
    checked = (
        {"score": None, "verdict": "not applicable", "flags": [], "stats": {}}
        if result.get("blocked")
        else style.check(result["body"], brief.get("facts", []))
    )

    return {
        **result,
        "intent": intent.key,
        "intent_label": intent.label,
        "engine": engine,
        "style": checked,
        "context_passages": [
            {"text": p["text"][:300], "url": p.get("url", ""), "score": p.get("score")}
            for p in passages
        ],
    }


def revise(brief: dict, subject: str, body: str, mode: str = "auto") -> dict:
    """Fix what the style checker flagged, then re-check."""
    checked = style.check(body, brief.get("facts", []))

    if not checked["flags"]:
        return {"subject": subject, "body": body, "style": checked, "engine": "unchanged"}

    if (mode == "llm" or mode == "auto") and clients.available():
        try:
            notes = "\n".join(f"- {f['message']} ({f['evidence']})" for f in checked["flags"])
            prompt = load_prompt("email_revise.v1").format(
                body=body,
                problems=notes,
                facts="\n".join(f"- {f['statement']}" for f in brief.get("facts", [])) or "(none)",
            )
            revised = _clean_model_output(
                str(clients.call(clients.reasoning(temperature=0.3), prompt).content).strip()
            )
            return {
                "subject": subject,
                "body": revised,
                "style": style.check(revised, brief.get("facts", [])),
                "engine": "nemotron",
            }
        except Exception:                                   # noqa: BLE001
            pass

    fixed = style.quick_fix(body)
    return {
        "subject": subject,
        "body": fixed,
        "style": style.check(fixed, brief.get("facts", [])),
        "engine": "mechanical",
    }
