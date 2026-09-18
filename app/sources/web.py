"""Live public sources: Tavily search plus a plain page fetch.

Scope guardrail, on purpose: company-level public information only. We do not
scrape personal profiles and we do not compile information about individuals.
Every response is cached to .cache/ so re-running an account during development
costs nothing and does not hammer anyone's server.
"""

import hashlib
import json
import re

import httpx

from app.config import settings

TIMEOUT = 20.0
MAX_DOCS = 8

# What we ask the search engine for. Company-level only.
#
# Topic matters more than it looks. A "general" search returns pages with no
# publication date, and an undated fact cannot fire any time-windowed scoring
# rule — so an account with a fresh funding round still scores zero. The "news"
# topic returns published_date, so event-shaped queries use it and profile-shaped
# queries stay general.
QUERIES = [
    ("{name} company overview", "general"),
    ("{name} hiring open roles careers", "general"),
    ("{name} funding round raised investment", "news"),
    ("{name} appoints new chief executive", "news"),
    ("{name} launches new product", "news"),
    ("{name} partnership agreement signed", "news"),
    ("{name} expands into new market", "news"),
]

NEWS_WINDOW_DAYS = 365


def _cache_path(key: str):
    return settings.cache_dir / f"{hashlib.md5(key.encode()).hexdigest()}.json"


def _cached(key: str):
    path = _cache_path(key)
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return None


def _store(key: str, value) -> None:
    with open(_cache_path(key), "w", encoding="utf-8") as fh:
        json.dump(value, fh)


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _search(query: str, topic: str = "general") -> list[dict]:
    """One Tavily search. Returns [{url, title, published, text}]."""
    cached = _cached(f"tavily:{topic}:{query}")
    if cached is not None:
        return cached

    if not settings.tavily_api_key:
        return []

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "topic": topic,
        "search_depth": "basic",
        "max_results": 3,
        "include_answer": False,
    }
    if topic == "news":
        payload["days"] = NEWS_WINDOW_DAYS      # only this key returns published_date

    response = httpx.post("https://api.tavily.com/search", json=payload, timeout=TIMEOUT)
    response.raise_for_status()

    results = [
        {
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "published": item.get("published_date", "") or "",
            "text": item.get("content", ""),
        }
        for item in response.json().get("results", [])
    ]
    _store(f"tavily:{topic}:{query}", results)
    return results


def fetch_page(url: str) -> dict | None:
    """Fetch one page as text. Best effort — a failure is not fatal."""
    cached = _cached(f"page:{url}")
    if cached is not None:
        return cached

    try:
        response = httpx.get(
            url,
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "OSINT-Scout/1.0 (internal research tool)"},
        )
        response.raise_for_status()
        doc = {"url": url, "title": url, "published": "", "text": _strip_html(response.text)[:20000]}
    except Exception:                                      # noqa: BLE001
        return None

    _store(f"page:{url}", doc)
    return doc


def fetch(account_name: str, domain: str | None = None) -> list[dict]:
    """Gather public documents about a company."""
    documents: list[dict] = []
    seen: set[str] = set()

    for template, topic in QUERIES:
        for item in _search(template.format(name=account_name), topic):
            if item["url"] and item["url"] not in seen and item["text"]:
                seen.add(item["url"])
                documents.append(item)

    if domain and len(documents) < MAX_DOCS:
        page = fetch_page(f"https://{domain}")
        if page and page["url"] not in seen:
            documents.append(page)

    return documents[:MAX_DOCS]
