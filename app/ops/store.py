"""Where finished briefs live.

One folder per run under data/runs/, holding brief.json, brief.md and run.jsonl.
Plain files on purpose: you can read a run with `cat`, diff two runs with `diff`,
and commit a brief from a GitHub Action without a database.
"""

import json

from app.config import settings
from app.ops.run_log import run_dir
from app.schemas.brief import AccountBrief


def save_brief(brief: AccountBrief, markdown: str) -> None:
    folder = run_dir(brief.run_id)
    with open(folder / "brief.json", "w", encoding="utf-8") as fh:
        json.dump(brief.model_dump(), fh, indent=2, default=str)
    with open(folder / "brief.md", "w", encoding="utf-8") as fh:
        fh.write(markdown)


def save_documents(run_id: str, documents: list[dict]) -> None:
    """Keep the raw sources with the run.

    Two reasons. It makes a brief auditable months later — you can see the text a
    claim was read from, not just the URL. And the outreach drafter re-queries
    them with an intent-shaped question, which needs the documents, not the brief.
    """
    with open(run_dir(run_id) / "documents.json", "w", encoding="utf-8") as fh:
        json.dump(documents, fh, indent=2)


def load_brief(run_id: str) -> dict | None:
    path = settings.runs_dir / run_id / "brief.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_markdown(run_id: str) -> str:
    path = settings.runs_dir / run_id / "brief.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def list_runs(account_id: str | None = None) -> list[dict]:
    """Newest first. Returns the summary fields the UI needs for its run table."""
    rows: list[dict] = []
    for folder in settings.runs_dir.iterdir():
        if not folder.is_dir():
            continue
        brief = load_brief(folder.name)
        if not brief:
            continue
        if account_id and brief.get("account_id") != account_id:
            continue
        rows.append(
            {
                "run_id": brief["run_id"],
                "account": brief["account"],
                "account_id": brief["account_id"],
                "generated_at": brief["generated_at"],
                "source_mode": brief.get("source_mode", ""),
                "facts": len(brief.get("facts", [])),
                "dropped": len(brief.get("dropped", [])),
                "score": brief.get("score", {}).get("total", 0),
                "band": brief.get("score", {}).get("band", "Low"),
                "direction": brief.get("delta", {}).get("direction", "flat"),
            }
        )
    return sorted(rows, key=lambda r: r["generated_at"], reverse=True)


def previous_run(account_id: str, before_run_id: str) -> dict | None:
    """The most recent completed run for this account, excluding the current one."""
    for row in list_runs(account_id):
        if row["run_id"] != before_run_id:
            return load_brief(row["run_id"])
    return None
