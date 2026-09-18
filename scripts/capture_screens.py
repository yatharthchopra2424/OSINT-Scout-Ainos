"""Capture the console's screens for the README.

Runs the real app against the fixture accounts and photographs each tab, so the
images in the documentation are always of the thing that actually ships rather
than a mock-up.

    python -m scripts.capture_screens

Writes PNGs to docs/screenshots/.
"""

import sys
import time

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import ROOT

BASE = "http://localhost:8000"
OUT = ROOT / "docs" / "screenshots"
VIEWPORT = {"width": 1500, "height": 950}


def reset_state() -> None:
    """Clear runtime state so the screens tell one coherent story.

    Without this the shots pick up whatever ad-hoc runs happened to be newest —
    an LLM run for one account sitting next to control runs for the others, which
    reads as an inconsistent score rather than as two different extractors.
    All of this is gitignored scratch state.
    """
    import shutil

    for path in [ROOT / "data" / "runs", ROOT / "data" / "leads.json"]:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    (ROOT / "data" / "runs").mkdir(parents=True, exist_ok=True)
    print("  runtime state cleared")


def age_one_account(account_id: str, days: int = 21) -> None:
    """Backdate one account's last touch so 'Needs attention' shows what it is for.

    The gold accounts are synthetic, so this is demo data by construction — but it
    is the one value on these screens that did not happen on its own.
    """
    import json
    from datetime import datetime, timedelta, timezone

    path = ROOT / "data" / "leads.json"
    leads = json.loads(path.read_text(encoding="utf-8"))
    if account_id in leads:
        when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        leads[account_id]["last_touch_at"] = when
        path.write_text(json.dumps(leads, indent=2), encoding="utf-8")
        print(f"  {account_id} backdated {days} days for the stale-deal panel")


def seed_state() -> None:
    """Give the pipeline something worth photographing.

    One extractor for every account — the control path, which is deterministic —
    so every score on the screens is reproducible by anyone who clones this.
    """
    for name in ["Northwind Logistics", "Helio Airways", "Verdant Hospitality",
                 "Castor Telecom", "Solent Maritime", "Atlas Freight Systems"]:
        job = httpx.post(f"{BASE}/api/runs", json={
            "name": name, "source_mode": "fixture",
            "extract_mode": "baseline", "embed_backend": "lexical",
        }, timeout=30).json()
        for _ in range(40):
            state = httpx.get(f"{BASE}/api/runs/{job['run_id']}/status", timeout=20).json()
            if state["state"] != "running":
                break
            time.sleep(0.3)
        print(f"  ran {name}")

    # A spread of stages so the board and the funnel are not all in one column.
    for account_id, stage, owner in [
        ("northwind-logistics", "qualified", "Yatharth"),
        ("helio-airways", "contacted", "Yatharth"),
        ("verdant-hospitality", "replied", "Priya"),
        ("castor-telecom", "researched", "Priya"),
        ("solent-maritime", "contacted", "Yatharth"),
    ]:
        httpx.put(f"{BASE}/api/leads/{account_id}/stage", json={"stage": stage}, timeout=20)
        httpx.put(f"{BASE}/api/leads/{account_id}/owner", json={"owner": owner}, timeout=20)
    print("  stages and owners set")


def capture() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

        # --- the tutorial, before it is dismissed ---------------------------
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "09-tutorial.png"))
        print("  09-tutorial.png")

        page.evaluate("try { localStorage.setItem('osint_scout_tour_done','1') } catch(e) {}")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1200)

        def shot(tab: str, filename: str, wait: int = 1200, full: bool = True) -> None:
            page.click(f'nav button[data-tab="{tab}"]')
            page.wait_for_timeout(wait)
            page.screenshot(path=str(OUT / filename), full_page=full)
            print(f"  {filename}")

        shot("pipeline", "01-agent.png")
        shot("watchlist", "02-watchlist.png")
        shot("deals", "03-pipeline.png", wait=1800)

        # --- a brief, opened -------------------------------------------------
        page.click('nav button[data-tab="briefs"]')
        page.wait_for_timeout(1200)
        page.click("#runsBody tr:has-text('Northwind Logistics')")
        page.wait_for_timeout(1800)
        page.screenshot(path=str(OUT / "04-brief.png"), full_page=True)
        print("  04-brief.png")

        # --- outreach, with a draft and its style score ----------------------
        page.fill("#emName", "Yatharth Chopra")
        page.fill("#emCompany", "AIONOS")
        page.fill("#emOffer", "We build agentic AI for travel and logistics operations")
        page.select_option("#emIntent", "intro")
        page.click("#emDraft")
        page.wait_for_selector("#emBody", timeout=120_000)
        page.wait_for_timeout(1500)
        page.locator("#outreachPanel").screenshot(path=str(OUT / "05-outreach.png"))
        print("  05-outreach.png")

        shot("logs", "06-logs.png", wait=1800)
        shot("rules", "07-rules.png")
        shot("evaluation", "08-eval.png", wait=1800)

        browser.close()


if __name__ == "__main__":
    print("resetting…")
    reset_state()
    print("seeding state…")
    seed_state()
    age_one_account("castor-telecom")
    print("capturing…")
    capture()
    print(f"\ndone — {len(list(OUT.glob('*.png')))} screenshots in docs/screenshots/")
