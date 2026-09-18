"""Read and write data/watchlist.yml — the list of accounts we monitor."""

import yaml

from app.config import settings


def load() -> list[dict]:
    if not settings.watchlist_file.exists():
        return []
    with open(settings.watchlist_file, "r", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("accounts", []) or []


def save(accounts: list[dict]) -> None:
    with open(settings.watchlist_file, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"accounts": accounts}, fh, sort_keys=False, allow_unicode=True)


def add(name: str, domain: str = "", notes: str = "") -> list[dict]:
    accounts = load()
    if any(a["name"].lower() == name.lower() for a in accounts):
        return accounts
    accounts.append({"name": name, "domain": domain, "notes": notes})
    save(accounts)
    return accounts


def remove(name: str) -> list[dict]:
    accounts = [a for a in load() if a["name"].lower() != name.lower()]
    save(accounts)
    return accounts
