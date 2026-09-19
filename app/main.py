"""The HTTP layer.

Every endpoint here exists because something in the UI needs it. The UI is not a
demo skin — it is the operator console for the pipeline: run an account, read the
brief, read the log the run produced, read the rules that scored it, and run the
eval harness. If it happens in the backend, there is a tab for it.
"""

import json
import subprocess
import sys
from contextlib import asynccontextmanager

import yaml
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import demo
from app.config import ROOT, settings
from app.graph import GRAPH_SHAPE, run_account
from app.llm import clients
from app.ops import jobs, leads, run_log, store, watchlist
from app.ops.run_log import new_run_id
from app.outreach import drafter, intents, style
from app.rules.engine import load_rules
from app.sources import fixtures
from app.sources.fixtures import account_slug

@asynccontextmanager
async def lifespan(_: FastAPI):
    """On the public demo, fill the empty disk before anyone looks at it."""
    if settings.demo_mode:
        demo.seed_in_background()
    yield


app = FastAPI(
    title="OSINT Scout",
    description="Account monitoring agent for Sales & Alliances.",
    version="1.0.0",
    lifespan=lifespan,
)

WEB_DIR = ROOT / "app" / "web"


def read_only() -> None:
    """Refuse a change that would alter shared state on the public demo.

    Called by every endpoint that edits the rules, the watchlist, or launches
    something expensive. One function, one message — so the UI can show the reason
    verbatim rather than a generic 403.
    """
    if settings.demo_mode:
        raise HTTPException(403, demo.READ_ONLY_MESSAGE)




# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
@app.get("/api/health", tags=["status"])
def health() -> dict:
    """Is everything wired up? The UI shows this in the header."""
    return {
        "ok": True,
        "nvidia_key_present": clients.available(),
        "source_mode": settings.source_mode,
        "embed_backend": settings.embed_backend,
        "vector_backend": settings.vector_backend,
        "support_threshold": settings.support_threshold,
        "retrieval_k": settings.retrieval_k,
        "fixture_accounts": fixtures.available_accounts(),
        "demo_mode": settings.demo_mode,
        "seeding": demo.status()["seeding"],
        "seed_error": demo.status()["error"],
    }


@app.get("/api/smoke", tags=["status"])
def smoke() -> dict:
    """Actually call the models and report what happened."""
    return clients.smoke_test()


@app.get("/api/architecture", tags=["status"])
def architecture() -> dict:
    """The eight nodes, so the UI can draw the pipeline instead of describing it."""
    return {"nodes": GRAPH_SHAPE}


# ---------------------------------------------------------------------------
# watchlist
# ---------------------------------------------------------------------------
@app.get("/api/watchlist", tags=["watchlist"])
def get_watchlist() -> list[dict]:
    return watchlist.load()


@app.post("/api/watchlist", tags=["watchlist"])
def add_to_watchlist(payload: dict = Body(...)) -> list[dict]:
    read_only()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    return watchlist.add(name, payload.get("domain", ""), payload.get("notes", ""))


@app.delete("/api/watchlist/{name}", tags=["watchlist"])
def remove_from_watchlist(name: str) -> list[dict]:
    read_only()
    return watchlist.remove(name)


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------
@app.post("/api/runs", tags=["runs"])
def create_run(payload: dict = Body(...)) -> dict:
    """Start a run and return its id straight away.

    Asynchronous because a run with the LLM enabled takes about seven minutes.
    Holding the request open for that long gave a frozen button and lost the run
    entirely on a restart. The nodes already write a log from the moment a run
    starts, so the browser follows progress by polling /status.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    options = dict(
        domain=payload.get("domain", ""),
        source_mode=payload.get("source_mode"),
        extract_mode=payload.get("extract_mode", "llm"),
        embed_backend=payload.get("embed_backend"),
        today=payload.get("today"),
    )

    if settings.demo_mode:
        # Only the bundled synthetic companies, and only the deterministic path.
        # Anything else would either find nothing (no live web) or, if it could,
        # spend a key on behalf of an anonymous visitor.
        if name.lower() not in {a.lower() for a in demo.allowed_accounts()}:
            raise HTTPException(
                400,
                "The public demo only runs the bundled synthetic companies: "
                + ", ".join(demo.allowed_accounts()) + ".",
            )
        options.update(demo.DEMO_RUN, domain="", today=None)
        demo.prune_runs()

    account_id = account_slug(name)
    run_id = new_run_id(account_id)

    jobs.start(run_id, name, lambda: run_account(name=name, run_id=run_id, **options))

    return {"run_id": run_id, "account": name, "account_id": account_id, "state": "running"}


@app.get("/api/runs/{run_id}/status", tags=["runs"])
def run_status(run_id: str) -> dict:
    """How far a run has got: which nodes finished, which is executing, how long."""
    return jobs.status(run_id)


@app.get("/api/runs", tags=["runs"])
def list_runs(account_id: str | None = None) -> list[dict]:
    return store.list_runs(account_id)


@app.get("/api/runs/{run_id}", tags=["runs"])
def get_run(run_id: str) -> dict:
    brief = store.load_brief(run_id)
    if not brief:
        raise HTTPException(404, f"no run {run_id}")
    return brief


@app.get("/api/runs/{run_id}/log", tags=["runs"])
def get_run_log(run_id: str) -> list[dict]:
    return run_log.read_log(run_id)


@app.get("/api/runs/{run_id}/markdown", response_class=PlainTextResponse, tags=["runs"])
def get_run_markdown(run_id: str) -> str:
    return store.load_markdown(run_id) or "not found"


@app.get("/api/runs/{run_id}/documents", tags=["runs"])
def get_run_documents(run_id: str) -> list[dict]:
    """The raw sources the run read. Kept so a claim can be audited months later."""
    path = settings.runs_dir / run_id / "documents.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@app.get("/api/digest", tags=["runs"])
def digest() -> list[dict]:
    """Latest run per account, newest first — the Monday-morning view."""
    seen: set[str] = set()
    rows: list[dict] = []
    for row in store.list_runs():
        if row["account_id"] in seen:
            continue
        seen.add(row["account_id"])
        brief = store.load_brief(row["run_id"]) or {}
        rows.append({**row, "delta": brief.get("delta", {}), "summary": brief.get("summary", "")})
    return rows


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
@app.get("/api/pipeline", tags=["pipeline"])
def get_pipeline(stale_after: int = leads.STALE_AFTER_DAYS) -> dict:
    """Stage counts, conversion, stale deals and band movement — the rep's view."""
    return leads.pipeline(stale_after)


@app.get("/api/stages", tags=["pipeline"])
def get_stages() -> list[dict]:
    return [{"key": s, "label": leads.STAGE_LABELS[s]} for s in leads.STAGES]


@app.get("/api/leads/{account_id}/timeline", tags=["pipeline"])
def get_timeline(account_id: str) -> list[dict]:
    """Everything that has happened to this account, written automatically."""
    return leads.timeline(account_id)


@app.put("/api/leads/{account_id}/stage", tags=["pipeline"])
def put_stage(account_id: str, payload: dict = Body(...)) -> dict:
    """Move a lead. Drafting an email does not do this — sending one does, and only
    a person knows whether that happened."""
    try:
        return leads.set_stage(account_id, payload.get("stage", ""), payload.get("account", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/leads/{account_id}/owner", tags=["pipeline"])
def put_owner(account_id: str, payload: dict = Body(...)) -> dict:
    owner = str(payload.get("owner", ""))
    if settings.demo_mode:
        owner = owner.strip()[: demo.MAX_OWNER_LENGTH]
    return leads.set_owner(account_id, owner, payload.get("account", ""))


# ---------------------------------------------------------------------------
# outreach
# ---------------------------------------------------------------------------
@app.get("/api/intents", tags=["outreach"])
def get_intents() -> list[dict]:
    """The reasons you might be writing. Intent changes which fact the email opens on."""
    return intents.as_dicts()


@app.post("/api/runs/{run_id}/email", tags=["outreach"])
def draft_email(run_id: str, payload: dict = Body(default={})) -> dict:
    """Draft outreach grounded in this run's verified facts.

    Useful before anyone has vetted the lead: the draft names which facts it used,
    and refuses to write at all when there is nothing verified to open on.
    """
    brief = store.load_brief(run_id)
    if not brief:
        raise HTTPException(404, f"no run {run_id}")

    fact_types = {f["type"] for f in brief.get("facts", [])}
    intent_key = payload.get("intent") or intents.suggest(
        brief.get("score", {}).get("band", "Low"), fact_types
    )

    draft = drafter.draft(
        brief=brief,
        intent_key=intent_key,
        sender=payload.get("sender") or {},
        mode="template" if settings.demo_mode else payload.get("mode", "auto"),
    )
    leads.record_email(brief, draft)
    return draft


@app.post("/api/email/check", tags=["outreach"])
def check_email(payload: dict = Body(...)) -> dict:
    """Score a draft for the habits that make writing read as generated.

    Pure Python, no model: stock openers, consultant filler, hedging, essay
    connectives, sentences nobody would say out loud, and whether the email
    contains anything specific at all.
    """
    brief = store.load_brief(payload.get("run_id", "")) or {}
    return style.check(payload.get("body", ""), brief.get("facts", []))


@app.post("/api/email/revise", tags=["outreach"])
def revise_email(payload: dict = Body(...)) -> dict:
    """Fix what the style checker flagged and re-score."""
    brief = store.load_brief(payload.get("run_id", ""))
    if not brief:
        raise HTTPException(404, "unknown run")
    return drafter.revise(
        brief=brief,
        subject=payload.get("subject", ""),
        body=payload.get("body", ""),
        mode="template" if settings.demo_mode else payload.get("mode", "auto"),
    )


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------
@app.get("/api/rules", tags=["rules"])
def get_rules() -> dict:
    return load_rules()


@app.get("/api/rules/raw", response_class=PlainTextResponse, tags=["rules"])
def get_rules_raw() -> str:
    return settings.rules_file.read_text(encoding="utf-8")


@app.put("/api/rules/raw", tags=["rules"])
def put_rules_raw(payload: dict = Body(...)) -> dict:
    """Edit the scoring rules from the UI. Validated before it is written."""
    read_only()
    text = payload.get("yaml", "")
    try:
        parsed = yaml.safe_load(text)
        assert "rules" in parsed and "bands" in parsed
    except Exception as exc:                                # noqa: BLE001
        raise HTTPException(400, f"invalid rules file: {exc}") from exc

    # load_rules() reads the file on every call, so the next run picks this up
    # with no cache to invalidate.
    settings.rules_file.write_text(text, encoding="utf-8")
    return {"ok": True, "rules": len(parsed["rules"])}


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------
@app.get("/api/eval", tags=["eval"])
def list_eval_runs() -> list[dict]:
    rows = []
    for folder in sorted(settings.eval_results_dir.iterdir(), reverse=True):
        summary_file = folder / "_summary.json"
        if summary_file.exists():
            with open(summary_file, "r", encoding="utf-8") as fh:
                rows.append(json.load(fh))
    return rows


@app.post("/api/eval", tags=["eval"])
def run_eval(payload: dict = Body(default={})) -> dict:
    """Run the eval harness and return its summary."""
    read_only()
    args = [sys.executable, "-m", "eval.run_eval"]
    if payload.get("extract_mode"):
        args += ["--extract-mode", payload["extract_mode"]]
    if payload.get("embed_backend"):
        args += ["--embed-backend", payload["embed_backend"]]

    completed = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    latest = list_eval_runs()

    return {
        "ok": completed.returncode == 0,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-4000:],
        "summary": latest[0] if latest else None,
    }


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", include_in_schema=False)
def home():
    """Serve the console with cache-busted asset URLs.

    Browsers hold on to app.js hard. When the run endpoint changed from returning
    a finished brief to returning a job handle, a cached page kept calling the old
    code against the new API and died with "Cannot read properties of undefined".
    Stamping the asset URLs with each file's mtime means a stale script can never
    outlive the backend it was written for.
    """
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for asset in ("app.js", "styles.css"):
        try:
            version = int((WEB_DIR / asset).stat().st_mtime)
        except OSError:
            continue
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
    return HTMLResponse(html)
