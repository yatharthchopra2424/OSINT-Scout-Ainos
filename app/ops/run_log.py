"""Structured run logs — one JSON object per line, one folder per run.

Every node writes a line as it starts and finishes. That log is what the Logs tab
in the UI reads, and it is what makes a brief auditable after the fact: you can
replay exactly which node saw what, how long it took, and why a fact was dropped.
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


def new_run_id(account_id: str) -> str:
    # Milliseconds, not seconds: the eval harness fires three runs per account
    # back to back, and at second resolution they collide and overwrite one
    # another's output.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return f"{account_id}_{stamp}"


def run_dir(run_id: str) -> Path:
    path = settings.runs_dir / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


class RunLog:
    """Append-only log for a single run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.path = run_dir(run_id) / "run.jsonl"
        self._started: dict[str, float] = {}
        # The verify node judges facts on a thread pool, so several threads can
        # log at once. Without this, two appends can interleave and produce a
        # half-written line that breaks every reader of the file.
        self._lock = threading.Lock()

    def _write(self, record: dict) -> None:
        record["ts"] = datetime.now(timezone.utc).isoformat()
        record["run_id"] = self.run_id
        line = json.dumps(record, default=str) + "\n"
        with self._lock, open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)

    def event(self, level: str, node: str, message: str, **fields) -> None:
        self._write({"level": level, "node": node, "message": message, **fields})

    def info(self, node: str, message: str, **fields) -> None:
        self.event("info", node, message, **fields)

    def warn(self, node: str, message: str, **fields) -> None:
        self.event("warn", node, message, **fields)

    def error(self, node: str, message: str, **fields) -> None:
        self.event("error", node, message, **fields)

    def start(self, node: str) -> None:
        self._started[node] = time.perf_counter()
        self.event("info", node, "started")

    def finish(self, node: str, **fields) -> None:
        elapsed = time.perf_counter() - self._started.get(node, time.perf_counter())
        self.event("info", node, "finished", ms=round(elapsed * 1000), **fields)

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


def read_log(run_id: str) -> list[dict]:
    return RunLog(run_id).read()
