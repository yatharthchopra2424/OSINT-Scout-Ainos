"""Node 8 — assemble the brief, write it to disk as JSON and Markdown.

Gaps are reported explicitly. Most demos hide what the system could not find;
this one prints it, and the eval harness scores whether it was right to stay quiet.
"""

from datetime import datetime, timezone

from app.config import settings
from app.llm import clients
from app.ops import store as run_store
from app.prompts import load as load_prompt
from app.schemas.brief import FACT_TYPES, AccountBrief, Delta, Score, VerifiedFact
from app.state import RunState

# Fact types we always want to say something about, even if that something is
# "we found nothing".
REPORTABLE = ["funding", "leadership_change", "hiring", "product_launch",
              "market_expansion", "partnership", "layoffs"]

LABELS = {t: t.replace("_", " ") for t in FACT_TYPES}


def _gaps(verified: list[dict]) -> list[str]:
    found = {f["type"] for f in verified}
    return [f"No public evidence found for: {LABELS[t]}" for t in REPORTABLE if t not in found]


def _summary_template(state: RunState, facts: list[dict]) -> str:
    account = state["account"]
    if not facts:
        return (
            f"No verified public information was found for {account}. "
            f"Either the company has little public footprint, or the sources searched "
            f"did not cover it. Treat this account as unresearched, not as low-signal."
        )
    band = state.get("score", {}).get("band", "Low")
    total = state.get("score", {}).get("total", 0)
    kinds = sorted({LABELS[f["type"]] for f in facts})
    return (
        f"{account}: {len(facts)} verified fact(s) across {', '.join(kinds)}. "
        f"Signal score {total} ({band}). "
        f"Every statement below links to the source it was read from."
    )


def _summary_llm(state: RunState, facts: list[dict]) -> str:
    bullets = "\n".join(f"- [{f['type']}] {f['statement']} ({f['source_url']})" for f in facts)
    prompt = load_prompt("summarize.v1").format(
        account=state["account"],
        facts=bullets or "(none)",
        score=state.get("score", {}).get("total", 0),
        band=state.get("score", {}).get("band", "Low"),
    )
    return str(clients.call(clients.reasoning(temperature=0.2), prompt).content).strip()


def to_markdown(brief: AccountBrief) -> str:
    lines = [
        f"# {brief.account}",
        "",
        f"*Run `{brief.run_id}` · {brief.generated_at} · source: {brief.source_mode}*",
        "",
        f"**Signal score {brief.score.total} ({brief.score.band})**",
        "",
        brief.summary,
        "",
        "## Verified facts",
    ]

    if brief.facts:
        for fact in brief.facts:
            date = fact.event_date or "undated"
            lines.append(
                f"- **{LABELS[fact.type]}** ({date}) — {fact.statement}  \n"
                f"  <{fact.source_url}> · support {fact.support_score}"
            )
    else:
        lines.append("- none")

    lines += ["", "## Why this score"]
    if brief.score.lines:
        for line in brief.score.lines:
            lines.append(f"- `{line.rule}` {line.points:+d} — {line.because}")
    else:
        lines.append("- no rules fired")

    lines += ["", "## What changed"]
    if brief.delta.is_first_run:
        lines.append("- first run for this account, nothing to compare against")
    else:
        lines.append(f"- band {brief.delta.band_before} -> {brief.delta.band_after} "
                     f"({brief.delta.direction})")
        for statement in brief.delta.new_facts:
            lines.append(f"- NEW: {statement}")
        for statement in brief.delta.dropped_facts:
            lines.append(f"- GONE: {statement}")

    lines += ["", "## Gaps"]
    lines += [f"- {gap}" for gap in brief.gaps] or ["- none"]

    if brief.dropped:
        lines += ["", "## Dropped by the verifier"]
        for fact in brief.dropped:
            lines.append(f"- {fact.statement} — {fact.reason} (score {fact.support_score})")

    return "\n".join(lines) + "\n"


def deliver(state: RunState) -> dict:
    log = state["log"]
    log.start("deliver")

    verified = state.get("verified", [])
    # The summary was a third model call for prose that the template already
    # produces well and deterministically. Off by default: set SUMMARY_MODEL=llm
    # if you want the model to write it.
    use_llm = (settings.summary_model == "llm"
               and clients.available() and state.get("extract_mode") == "llm")

    try:
        summary = _summary_llm(state, verified) if use_llm else _summary_template(state, verified)
    except Exception as exc:                                # noqa: BLE001
        log.warn("deliver", "summary model failed, using template", error=str(exc)[:200])
        summary = _summary_template(state, verified)

    brief = AccountBrief(
        run_id=state["run_id"],
        account=state["account"],
        account_id=state["account_id"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_mode=state.get("source_mode", "fixture"),
        summary=summary,
        facts=[VerifiedFact(**f) for f in verified],
        dropped=[VerifiedFact(**f) for f in state.get("dropped", [])],
        gaps=_gaps(verified),
        score=Score(**state.get("score", {})),
        delta=Delta(**state.get("delta", {})),
        documents_used=len(state.get("documents", [])),
        chunks_indexed=state.get("chunks_indexed", 0),
        retries=state.get("retries", 0),
        errors=state.get("errors", []),
    )

    markdown = to_markdown(brief)
    run_store.save_brief(brief, markdown)
    run_store.save_documents(brief.run_id, state.get("documents", []))

    log.finish("deliver", facts=len(brief.facts), gaps=len(brief.gaps),
               documents_kept=len(state.get("documents", [])))
    return {"brief": brief.model_dump(), "markdown": markdown}
