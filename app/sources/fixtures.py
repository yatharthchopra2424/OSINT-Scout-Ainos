"""Frozen documents, read from disk.

The eval harness runs against these and never touches the network. That is
deliberate: if CI hits the live web, the tests are flaky and you end up measuring
the internet's mood instead of your own system.

These companies are synthetic. Nothing here asserts anything about a real
business, which is also what makes it safe to commit.
"""

import json

from app.config import settings


def _docs_dir():
    return settings.fixtures_dir / "docs"


def account_slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")


def available_accounts() -> list[str]:
    if not _docs_dir().exists():
        return []
    return sorted(p.stem for p in _docs_dir().glob("*.json"))


def fetch(account_name: str) -> list[dict]:
    """Return [{url, title, published, text}] for an account, or [] if unknown."""
    path = _docs_dir() / f"{account_slug(account_name)}.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)["documents"]
