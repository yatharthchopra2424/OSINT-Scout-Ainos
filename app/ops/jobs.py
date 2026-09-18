"""Runs happen in the background, so the browser never waits on one.

A fixture run takes under a second. A run with the LLM enabled takes **about seven
minutes** — the reasoning model is slow, and when the endpoint refuses guided_json
there is a second round trip on top. Holding an HTTP request open for that long
means a frozen button, no idea whether anything is happening, and a run that is
lost for good if the server restarts or a proxy times the connection out. All
three were observed.

So POST /api/runs starts a thread and returns a run_id immediately. The nodes were
already writing a structured log to disk from the moment a run starts, so progress
comes from reading that log — no extra plumbing, and a browser that reloads
mid-run can pick the same run back up.

In-process and deliberately small. A real deployment puts this on a job queue;
this is the honest minimum that makes the UI usable.
"""

import threading
import time
from typing import Any, Callable

from app.ops.run_log import read_log

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
KEEP_JOBS = 50


def start(run_id: str, account: str, work: Callable[[], Any]) -> dict:
    """Run `work` on a thread, tracking its state under `run_id`."""
    with _LOCK:
        _prune()
        _JOBS[run_id] = {
            "run_id": run_id, "account": account, "state": "running",
            "started_at": time.time(), "finished_at": None, "error": None,
        }

    def target() -> None:
        try:
            work()
            state, error = "done", None
        except Exception as exc:                            # noqa: BLE001
            state, error = "error", f"{type(exc).__name__}: {exc}"[:500]
        with _LOCK:
            job = _JOBS.get(run_id)
            if job:
                job.update(state=state, error=error, finished_at=time.time())

    threading.Thread(target=target, daemon=True, name=f"run:{run_id}").start()
    return dict(_JOBS[run_id])


def _prune() -> None:
    if len(_JOBS) <= KEEP_JOBS:
        return
    finished = sorted(
        (j for j in _JOBS.values() if j["state"] != "running"),
        key=lambda j: j.get("finished_at") or 0,
    )
    for job in finished[: len(_JOBS) - KEEP_JOBS]:
        _JOBS.pop(job["run_id"], None)


def status(run_id: str) -> dict:
    """Where a run has got to, from the job table plus its own log on disk."""
    with _LOCK:
        job = dict(_JOBS.get(run_id) or {})

    lines = read_log(run_id)
    done_nodes, current = [], None
    for line in lines:
        node, message = line.get("node"), line.get("message")
        if node == "run":
            continue
        if message == "started":
            current = node
        elif message == "finished" and node:
            done_nodes.append({"node": node, "ms": line.get("ms")})
            if current == node:
                current = None

    if not job:
        # Not in this process's table — a run from before a restart, say. The log
        # still tells us whether it reached the end.
        finished = any(l.get("node") == "run" and l.get("message") == "completed" for l in lines)
        job = {
            "run_id": run_id, "state": "done" if finished else "unknown",
            "started_at": None, "finished_at": None, "error": None,
        }

    started = job.get("started_at")
    elapsed = (job.get("finished_at") or time.time()) - started if started else None

    return {
        **job,
        "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
        "completed_nodes": done_nodes,
        "current_node": current,
        "warnings": [l.get("message") for l in lines if l.get("level") == "warn"][-3:],
    }
