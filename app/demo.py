"""Public demo deployment.

A free host gives you an ephemeral disk: every restart and every wake-from-sleep
starts with nothing in data/. A console that opens onto empty tables is a bad
first impression, so demo mode fills itself on startup, in a background thread so
the health check answers immediately.

What it does, in order:

1. Runs the eval harness once on the control path, so the Eval tab has results.
   Those runs also write lead state, so step 2 clears it.
2. Clears runtime state.
3. Runs the six synthetic gold accounts and spreads them across pipeline stages,
   so the stage board, the conversion funnel and the stale-deal panel all have
   something in them.

Everything here uses the deterministic control path, so a visitor sees the same
numbers the README shows and nothing on this path can spend an API key.
"""

import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from app.config import ROOT, settings

# One extractor, one embedder, one source. Reproducible by anyone who clones it.
DEMO_RUN = dict(source_mode="fixture", extract_mode="baseline", embed_backend="lexical")

ACCOUNTS = [
    "Northwind Logistics", "Helio Airways", "Verdant Hospitality",
    "Castor Telecom", "Solent Maritime", "Atlas Freight Systems",
]

# stage, owner — a spread, so the board and the funnel are not all in one column
STAGES = {
    "northwind-logistics": ("qualified", "Yatharth"),
    "helio-airways": ("contacted", "Yatharth"),
    "verdant-hospitality": ("replied", "Priya"),
    "castor-telecom": ("researched", "Priya"),
    "solent-maritime": ("contacted", "Yatharth"),
}

# One account is backdated so the "Needs attention" panel shows what it is for.
# It is demo data by construction, and the UI banner says the deployment is a demo.
STALE_ACCOUNT = "castor-telecom"
STALE_DAYS = 21

_state = {"seeding": False, "seeded": False, "error": None, "started_at": None}


def status() -> dict:
    return dict(_state)


def _clear_runtime_state() -> None:
    shutil.rmtree(settings.runs_dir, ignore_errors=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    leads = ROOT / "data" / "leads.json"
    if leads.exists():
        leads.unlink()


def _run_eval() -> None:
    """Produce eval results for the Eval tab. Runs as a subprocess, like the API does."""
    subprocess.run(
        [sys.executable, "-m", "eval.run_eval", "--extract-mode", "baseline",
         "--embed-backend", "lexical"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=600,
    )


def seed() -> None:
    """Populate a fresh deployment. Safe to call more than once."""
    from app.graph import run_account
    from app.ops import leads

    _state.update(seeding=True, error=None, started_at=time.time())
    try:
        _run_eval()
        _clear_runtime_state()

        for name in ACCOUNTS:
            run_account(name=name, **DEMO_RUN)

        for account_id, (stage, owner) in STAGES.items():
            leads.set_stage(account_id, stage)
            leads.set_owner(account_id, owner)

        data = leads.load()
        if STALE_ACCOUNT in data:
            when = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
            data[STALE_ACCOUNT]["last_touch_at"] = when.isoformat(timespec="seconds")
            leads.save(data)

        _state.update(seeded=True)
    except Exception as exc:                                # noqa: BLE001
        _state.update(error=f"{type(exc).__name__}: {exc}"[:300])
    finally:
        _state.update(seeding=False)


def seed_in_background() -> None:
    threading.Thread(target=seed, daemon=True, name="demo-seed").start()


# ---------------------------------------------------------------------------
# what a visitor is not allowed to do
# ---------------------------------------------------------------------------
READ_ONLY_MESSAGE = (
    "This is a read-only demo deployment. Clone the repository to run it with your "
    "own accounts, rules and API keys."
)

MAX_OWNER_LENGTH = 40
MAX_STORED_RUNS = 120


def prune_runs() -> int:
    """Keep the newest runs and delete the rest.

    Anyone can press Run as often as they like, and every run leaves a folder on
    disk. Unbounded, a bored visitor could grow the runs directory and slow every
    listing that scans it. Oldest first, so the freshest results are what remain.
    """
    folders = sorted((d for d in settings.runs_dir.iterdir() if d.is_dir()),
                     key=lambda d: d.name)
    excess = folders[: max(0, len(folders) - MAX_STORED_RUNS)]
    for folder in excess:
        shutil.rmtree(folder, ignore_errors=True)
    return len(excess)


def allowed_accounts() -> list[str]:
    """Only the bundled synthetic companies can be run on the public demo."""
    return list(ACCOUNTS)
