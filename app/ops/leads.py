"""Lead state: what stage each account is at, and what has happened to it.

This is the spine the research layer was missing. A brief tells you what is true
about a company; a lead tells you what you have done about it. Without stage and
last-touch there is no pipeline, no stale-deal list and no conversion rate — which
is most of what a salesperson actually looks at.

Everything on the timeline is written automatically. Reps famously spend about as
much of their week on CRM data entry as they do on prospecting research, and data
entry is the one part of the job that is fully automatable — so nothing here asks
anyone to type what the system already knows.

Stored as plain JSON next to the runs, for the same reason the briefs are: you can
read it, diff it and commit it from a scheduled job without a database.
"""

import json
from datetime import datetime, timedelta, timezone

from app.config import settings

# Ordered. Position matters: conversion between consecutive stages, and "furthest
# reached" is the max index seen on an account's timeline.
STAGES = ["new", "researched", "contacted", "replied", "qualified", "won", "lost"]
OPEN_STAGES = [s for s in STAGES if s not in ("won", "lost")]

STAGE_LABELS = {
    "new": "New",
    "researched": "Researched",
    "contacted": "Contacted",
    "replied": "Replied",
    "qualified": "Qualified",
    "won": "Won",
    "lost": "Lost",
}

STALE_AFTER_DAYS = 14


def _file():
    return settings.runs_dir.parent / "leads.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    path = _file()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save(leads: dict) -> None:
    with open(_file(), "w", encoding="utf-8") as fh:
        json.dump(leads, fh, indent=2)


def ensure(account_id: str, account: str) -> dict:
    leads = load()
    if account_id not in leads:
        leads[account_id] = {
            "account_id": account_id,
            "account": account,
            "stage": "new",
            "owner": "",
            "created_at": _now(),
            "last_touch_at": _now(),
            "timeline": [],
        }
        save(leads)
    return leads[account_id]


def log(account_id: str, account: str, kind: str, detail: str, **extra) -> dict:
    """Append one event and bump last-touch. Called by the system, not by a person."""
    ensure(account_id, account)
    leads = load()
    lead = leads[account_id]

    lead["timeline"].insert(0, {"ts": _now(), "kind": kind, "detail": detail, **extra})
    lead["timeline"] = lead["timeline"][:60]           # keep it readable
    lead["last_touch_at"] = _now()

    save(leads)
    return lead


def set_stage(account_id: str, stage: str, account: str = "") -> dict:
    if stage not in STAGES:
        raise ValueError(f"unknown stage '{stage}'")

    leads = load()
    lead = leads.get(account_id) or ensure(account_id, account or account_id)
    leads = load()
    lead = leads[account_id]

    before = lead["stage"]
    if before == stage:
        return lead

    lead["stage"] = stage
    lead["last_touch_at"] = _now()
    lead["timeline"].insert(0, {
        "ts": _now(), "kind": "stage",
        "detail": f"{STAGE_LABELS[before]} → {STAGE_LABELS[stage]}",
        "from": before, "to": stage,
    })
    save(leads)
    return lead


def set_owner(account_id: str, owner: str, account: str = "") -> dict:
    ensure(account_id, account or account_id)
    leads = load()
    leads[account_id]["owner"] = owner
    save(leads)
    return leads[account_id]


# ---------------------------------------------------------------------------
# automatic logging
# ---------------------------------------------------------------------------
def record_run(brief: dict) -> None:
    """A research run happened. Advance a brand-new lead to Researched."""
    account_id, account = brief["account_id"], brief["account"]
    score = brief.get("score", {})
    delta = brief.get("delta", {})

    detail = (f"Researched — {len(brief.get('facts', []))} facts, "
              f"score {score.get('total', 0)} ({score.get('band', 'Low')})")
    if delta.get("direction") == "up":
        detail += f", band up from {delta.get('band_before')}"

    log(account_id, account, "run", detail,
        run_id=brief.get("run_id"), band=score.get("band"), score=score.get("total"))

    if load().get(account_id, {}).get("stage") == "new":
        set_stage(account_id, "researched", account)


def record_email(brief: dict, draft: dict) -> None:
    """A draft was written. Note that this is NOT the same as one being sent —
    the stage only moves to Contacted when a person says it did."""
    if draft.get("blocked"):
        log(brief["account_id"], brief["account"], "email",
            f"Refused to draft ({draft.get('blocked_reason', 'no grounding')})")
        return

    style = draft.get("style") or {}
    log(brief["account_id"], brief["account"], "email",
        f"Drafted {draft.get('intent_label', 'outreach')} — style {style.get('score')}/100",
        intent=draft.get("intent"), engine=draft.get("engine"))


# ---------------------------------------------------------------------------
# pipeline view
# ---------------------------------------------------------------------------
def _days_since(iso: str) -> int:
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return 0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).days


def furthest_stage(lead: dict) -> str:
    """The furthest stage this account ever reached, not where it sits now.

    A deal that went Contacted then Lost still counts as having reached Contacted,
    which is the only way stage-to-stage conversion means anything.
    """
    reached = {lead.get("stage", "new")}
    for event in lead.get("timeline", []):
        if event.get("kind") == "stage":
            reached.add(event.get("to", ""))
            reached.add(event.get("from", ""))
    indexes = [STAGES.index(s) for s in reached if s in STAGES]
    return STAGES[max(indexes)] if indexes else "new"


def pipeline(stale_after: int = STALE_AFTER_DAYS) -> dict:
    """Everything the Pipeline tab needs, in one call."""
    from app.ops import store

    leads = load()
    latest_by_account: dict[str, dict] = {}
    for row in store.list_runs():
        latest_by_account.setdefault(row["account_id"], row)

    rows: list[dict] = []
    for account_id, lead in leads.items():
        run = latest_by_account.get(account_id, {})
        idle = _days_since(lead.get("last_touch_at", ""))
        rows.append({
            "account_id": account_id,
            "account": lead.get("account", account_id),
            "stage": lead.get("stage", "new"),
            "stage_label": STAGE_LABELS.get(lead.get("stage", "new"), "New"),
            "owner": lead.get("owner", ""),
            "band": run.get("band"),
            "score": run.get("score"),
            "direction": run.get("direction", "flat"),
            "last_run": run.get("generated_at"),
            "last_touch_at": lead.get("last_touch_at"),
            "days_idle": idle,
            "stale": idle >= stale_after and lead.get("stage") in OPEN_STAGES,
            "events": len(lead.get("timeline", [])),
        })

    rows.sort(key=lambda r: (STAGES.index(r["stage"]), -(r["score"] or 0)))

    # Stage counts, plus how many accounts ever reached each stage.
    counts = {s: 0 for s in STAGES}
    reached = {s: 0 for s in STAGES}
    for account_id, lead in leads.items():
        counts[lead.get("stage", "new")] = counts.get(lead.get("stage", "new"), 0) + 1
        top = STAGES.index(furthest_stage(lead))
        for i in range(top + 1):
            reached[STAGES[i]] += 1

    # Conversion between consecutive open stages, on "ever reached".
    conversion = []
    for a, b in zip(OPEN_STAGES, OPEN_STAGES[1:]):
        conversion.append({
            "from": STAGE_LABELS[a], "to": STAGE_LABELS[b],
            "from_count": reached[a], "to_count": reached[b],
            "rate": round(reached[b] / reached[a], 3) if reached[a] else None,
        })

    bands = {"High": 0, "Medium": 0, "Low": 0}
    for row in rows:
        if row["band"] in bands:
            bands[row["band"]] += 1

    return {
        "stages": [{"key": s, "label": STAGE_LABELS[s], "count": counts.get(s, 0)} for s in STAGES],
        "conversion": conversion,
        "bands": bands,
        "rows": rows,
        "stale": [r for r in rows if r["stale"]],
        "movers": [r for r in rows if r["direction"] == "up"],
        "stale_after_days": stale_after,
        "totals": {
            "accounts": len(rows),
            "open": sum(1 for r in rows if r["stage"] in OPEN_STAGES),
            "won": counts.get("won", 0),
            "lost": counts.get("lost", 0),
        },
    }


def timeline(account_id: str) -> list[dict]:
    return load().get(account_id, {}).get("timeline", [])
