"""Re-run every account on the watchlist and report what moved.

This is what the nightly GitHub Action executes. It writes one Markdown brief per
account into reports/, a combined digest at reports/DIGEST.md, and alerts.json
listing any account whose signal band went up — which the workflow turns into a
GitHub Issue.

    python -m scripts.refresh_watchlist
    python -m scripts.refresh_watchlist --extract-mode llm --source-mode web
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows consoles default to cp1252, so a single non-ASCII character in a company
# name or a source title kills the whole run with a UnicodeEncodeError. Force UTF-8
# on the way out; anything unprintable degrades to a replacement character instead
# of an exception.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.config import ROOT
from app.graph import run_account
from app.nodes.deliver import to_markdown
from app.ops import watchlist
from app.schemas.brief import AccountBrief

REPORTS = ROOT / "reports"


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh every watchlist account")
    parser.add_argument("--source-mode", default="fixture", choices=["fixture", "web"])
    parser.add_argument("--extract-mode", default="baseline", choices=["baseline", "llm"])
    parser.add_argument("--embed-backend", default=None, choices=["lexical", "nemotron"])
    args = parser.parse_args()

    REPORTS.mkdir(exist_ok=True)
    accounts = watchlist.load()
    if not accounts:
        print("watchlist is empty — nothing to do")
        return 0

    digest: list[str] = [
        "# Watchlist digest",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
        f"· sources: {args.source_mode} · extractor: {args.extract_mode}",
        "",
    ]
    alerts: list[dict] = []

    for entry in accounts:
        name = entry["name"]
        print(f"-> {name}")

        brief_dict = run_account(
            name=name,
            domain=entry.get("domain", ""),
            source_mode=args.source_mode,
            extract_mode=args.extract_mode,
            embed_backend=args.embed_backend,
        )
        brief = AccountBrief(**brief_dict)

        slug = brief.account_id
        (REPORTS / f"{slug}.md").write_text(to_markdown(brief), encoding="utf-8")

        delta = brief.delta
        moved = "first run" if delta.is_first_run else f"{delta.band_before} -> {delta.band_after}"

        digest.append(
            f"## {brief.account} — {brief.score.total} ({brief.score.band}) · {moved}"
        )
        digest.append("")
        if delta.new_facts:
            digest.append("**New since the last run**")
            digest += [f"- {s}" for s in delta.new_facts]
        elif not delta.is_first_run:
            digest.append("No change since the last run.")
        digest.append("")

        if delta.direction == "up":
            alerts.append({
                "account": brief.account,
                "band_before": delta.band_before,
                "band_after": delta.band_after,
                "score": brief.score.total,
                "new_facts": delta.new_facts,
            })

        print(f"   {len(brief.facts)} facts, score {brief.score.total} ({brief.score.band}), {moved}")

    (REPORTS / "DIGEST.md").write_text("\n".join(digest), encoding="utf-8")
    Path(REPORTS / "alerts.json").write_text(json.dumps(alerts, indent=2), encoding="utf-8")

    print(f"\n{len(accounts)} accounts refreshed, {len(alerts)} moved up a band")
    return 0


if __name__ == "__main__":
    sys.exit(main())
