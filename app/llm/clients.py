"""The two Nemotron models we talk to, and one honest fallback.

reasoning()  nemotron-3-super-120b-a12b   — extraction, summarising. Supports
                                            structured output and tool calling.
fast()       nemotron-3.5-lightning-30b   — the verifier. Runs once per fact, so
                                            it has to be cheap.

If there is no NVIDIA_API_KEY the pipeline still runs end to end: `available()`
returns False and the nodes fall back to deterministic behaviour. That is what
lets the eval harness run in CI with no secrets.
"""

import json
import re
import time
import warnings
from functools import lru_cache

from app.config import settings

# The wrapper keeps a registry of known model ids and warns on anything newer than
# itself. The Nemotron 3 endpoints are not in that registry yet but answer fine —
# verified against the live API — so the warning is noise on every single call.
warnings.filterwarnings("ignore", message=r".*type is unknown and inference may fail.*")

RETRY_ATTEMPTS = 4
RETRY_BACKOFF = 2.5          # seconds, doubled each attempt

# Transient on NVIDIA's free tier: 503 when the shared endpoint is saturated, 429
# when we cross ~40 requests/minute. Both are worth waiting out; a 401 is not.
RETRYABLE = ("503", "429", "overloaded", "timeout", "temporarily", "rate limit")


def available() -> bool:
    """True when we can actually call NVIDIA NIM."""
    return settings.has_nvidia_key


def call(runnable, payload, attempts: int = RETRY_ATTEMPTS):
    """Invoke a model with backoff on the errors that are worth retrying.

    The eval harness makes hundreds of calls in a row, so a single 503 from a
    shared free-tier endpoint should not fail a run that is otherwise fine.
    Anything that is not transient — a bad key, a bad request — is raised at once
    rather than retried four times.
    """
    delay = RETRY_BACKOFF
    last: Exception | None = None

    for attempt in range(attempts):
        try:
            return runnable.invoke(payload)
        except Exception as exc:                            # noqa: BLE001
            last = exc
            if not any(token in str(exc).lower() for token in RETRYABLE):
                raise
            if attempt == attempts - 1:
                break
            time.sleep(delay)
            delay *= 2

    raise last                                              # type: ignore[misc]


@lru_cache(maxsize=None)
def _chat(model: str, temperature: float, max_tokens: int):
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    return ChatNVIDIA(
        model=model,
        api_key=settings.nvidia_api_key,
        base_url=settings.nvidia_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def reasoning(temperature: float = 0.1, max_tokens: int = 2048):
    """The big model: extraction and summarising."""
    return _chat(settings.model_reasoning, temperature, max_tokens)


def fast(temperature: float = 0.0, max_tokens: int = 1024):
    """The small model: verification, one call per fact."""
    return _chat(settings.model_fast, temperature, max_tokens)


# ---------------------------------------------------------------------------
# structured output, without depending on the endpoint supporting it
# ---------------------------------------------------------------------------
# LangChain implements with_structured_output for this provider by sending a
# `guided_json` field. The NIM endpoint accepts it on some backend instances and
# rejects it with a 400 on others — the same model, the same key, minutes apart.
# So we try the strict path, and fall back to asking for JSON in the prompt when
# the endpoint refuses. Either way the result is validated against the schema.
_GUIDED_JSON_UNSUPPORTED = ("guided_json", "unknown field", "response_format")

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def _unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return "400" in text and any(token in text for token in _GUIDED_JSON_UNSUPPORTED)


def first_json_object(text: str) -> dict | None:
    """Pull the first balanced JSON object out of a model reply.

    Handles code fences, thinking tags, and prose wrapped around the JSON. Also
    makes one repair attempt on a reply that was cut off mid-object, which happens
    when reasoning eats the token budget.
    """
    cleaned = _THINK.sub("", text or "").strip()
    fenced = _FENCE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()

    start = cleaned.find("{")
    if start == -1:
        return None

    depth, in_string, escaped = 0, False, False
    for i, ch in enumerate(cleaned[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start:i + 1])
                except json.JSONDecodeError:
                    return None

    # Never closed: try to close it ourselves rather than lose the whole reply.
    tail = cleaned[start:].rstrip().rstrip(",")
    for suffix in ('"}]}', '"}]', '}]}', ']}', '}}', '}'):
        try:
            return json.loads(tail + suffix)
        except json.JSONDecodeError:
            continue
    return None


def structured(chat, prompt: str, schema, shape_hint: str):
    """Return an instance of `schema`, however the endpoint will give it to us."""
    try:
        return call(chat.with_structured_output(schema), prompt)
    except Exception as exc:                                # noqa: BLE001
        if not _unsupported(exc):
            raise

    fallback = (
        f"{prompt}\n\n"
        f"Return ONLY a JSON object of exactly this shape, and nothing else — "
        f"no explanation, no code fence, no text before or after it:\n{shape_hint}"
    )
    reply = call(chat, fallback)
    data = first_json_object(str(reply.content))
    if data is None:
        raise ValueError("model did not return parsable JSON")
    return schema(**data)


def smoke_test() -> dict:
    """Prove chat and embeddings both work. Used by `python -m app.smoke`."""
    from app.rag.embeddings import get_embedder

    result: dict = {
        "nvidia_key_present": available(),
        "embed_backend": settings.embed_backend,
        "chat": None,
        "embed": None,
    }

    if available():
        try:
            reply = call(reasoning(), "Reply with the single word: ready")
            result["chat"] = {"ok": True, "reply": str(reply.content)[:120]}
        except Exception as exc:                          # noqa: BLE001
            result["chat"] = {"ok": False, "error": str(exc)[:300]}
    else:
        result["chat"] = {"ok": False, "error": "NVIDIA_API_KEY not set"}

    try:
        vector = get_embedder().embed_query("hello")
        result["embed"] = {"ok": True, "dimensions": len(vector)}
    except Exception as exc:                              # noqa: BLE001
        result["embed"] = {"ok": False, "error": str(exc)[:300]}

    return result
