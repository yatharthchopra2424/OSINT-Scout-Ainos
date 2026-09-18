"""The eval harness.

    python -m eval.run_eval                      # control extractor, no API key
    python -m eval.run_eval --extract-mode llm   # Nemotron, needs NVIDIA_API_KEY
    python -m eval.run_eval --embed-backend nemotron

Runs every gold account three times: once to measure, twice more to prove the
result is stable and that a re-run with identical inputs reports no phantom
changes. Writes eval/results/run_<timestamp>/_summary.json and exits non-zero if
any gate fails — which is what lets GitHub Actions block a merge on it.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

# Windows consoles default to cp1252, so a single non-ASCII character in a company
# name or a source title kills the whole run with a UnicodeEncodeError. Force UTF-8
# on the way out; anything unprintable degrades to a replacement character instead
# of an exception.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.config import settings
from app.graph import run_account_state
from eval import metrics

RUNS_PER_ACCOUNT = 3


def evaluate_account(slug: str, extract_mode: str, embed_backend: str, today: str,
                     runs: int = RUNS_PER_ACCOUNT) -> dict:
    gold = metrics.load_gold(slug)
    account = gold["account"]

    states = [
        run_account_state(
            name=account,
            domain=gold.get("domain", ""),
            source_mode="fixture",
            extract_mode=extract_mode,
            embed_backend=embed_backend,
            today=today,
        )
        for _ in range(max(1, runs))
    ]

    first, last = states[0], states[-1]
    brief = first["brief"]
    facts = brief.get("facts", [])
    gold_facts = gold.get("gold_facts", [])

    matched, unmatched, missed = metrics.match_facts(facts, gold_facts)
    ground_score, ground_failures = metrics.groundedness(
        facts, metrics.source_text_by_url(account)
    )

    totals = [s.get("score", {}).get("total", 0) for s in states]
    repeat_delta = last.get("delta", {})

    return {
        "account": account,
        "slug": slug,
        "schema_valid": metrics.schema_valid(brief),
        "facts_extracted": len(facts),
        "facts_dropped_by_verifier": len(brief.get("dropped", [])),
        "gold_facts": len(gold_facts),
        "fact_precision": round(matched / len(facts), 4) if facts else (1.0 if not gold_facts else 0.0),
        "fact_recall": round(matched / len(gold_facts), 4) if gold_facts else 1.0,
        "citation_groundedness": ground_score,
        "retrieval_hit_rate": metrics.retrieval_hit_rate(first.get("retrieval_by_type", {}), gold_facts),
        "correct_abstention": metrics.correct_abstention(brief, gold),
        "band_correct": brief.get("score", {}).get("band") == gold.get("expected_band"),
        # Stability and delta-noise need at least two runs to mean anything. With
        # one run they would pass trivially, which is worse than not reporting
        # them — so they are marked not-measured and dropped from the gates.
        "repeats_measured": len(states) >= 2,
        "score_stable": len(set(totals)) == 1 if len(states) >= 2 else None,
        "delta_noise": bool(repeat_delta.get("new_facts") or repeat_delta.get("dropped_facts"))
                       if len(states) >= 2 else None,
        "score_actual": totals[0],
        "score_expected": gold.get("expected_score"),
        "band_actual": brief.get("score", {}).get("band"),
        "band_expected": gold.get("expected_band"),
        "retries": brief.get("retries", 0),
        "run_id": brief.get("run_id"),
        "misses": [f"{g['type']}: {', '.join(g['keywords'])}" for g in missed],
        "false_positives": [f"{f['type']}: {f['statement'][:90]}" for f in unmatched],
        "groundedness_failures": ground_failures,
    }


def mean(rows: list[dict], key: str) -> float:
    return round(sum(r[key] for r in rows) / len(rows), 4) if rows else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="OSINT Scout eval harness")
    parser.add_argument("--extract-mode", default="baseline", choices=["baseline", "llm"])
    parser.add_argument("--embed-backend", default=None, choices=["lexical", "nemotron"])
    parser.add_argument(
        "--runs", type=int, default=RUNS_PER_ACCOUNT,
        help="Runs per account. Three proves stability and that a repeat reports no "
             "phantom changes. The LLM path is ~100x slower than the control path, so "
             "--runs 1 is there for when you only need the accuracy numbers.",
    )
    args = parser.parse_args()

    manifest = metrics.load_manifest()
    today = manifest["today"]
    embed_backend = args.embed_backend or settings.embed_backend

    print(f"OSINT Scout eval — extractor={args.extract_mode} embeddings={embed_backend} "
          f"vector={settings.vector_backend} runs={args.runs} today={today}")
    print("-" * 100)

    rows = [
        evaluate_account(slug, args.extract_mode, embed_backend, today, args.runs)
        for slug in manifest["accounts"]
    ]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "extract_mode": args.extract_mode,
        "embed_backend": embed_backend,
        "vector_backend": settings.vector_backend,
        "today": today,
        "runs_per_account": args.runs,
        "accounts": len(rows),
        "schema_validity": round(sum(r["schema_valid"] for r in rows) / len(rows), 4),
        "fact_precision": mean(rows, "fact_precision"),
        "fact_recall": mean(rows, "fact_recall"),
        "citation_groundedness": mean(rows, "citation_groundedness"),
        "retrieval_hit_rate": mean(rows, "retrieval_hit_rate"),
        "correct_abstention": mean(rows, "correct_abstention"),
        "band_accuracy": round(sum(r["band_correct"] for r in rows) / len(rows), 4),
    }

    repeated = [r for r in rows if r["repeats_measured"]]
    if repeated:
        summary["score_stability"] = round(sum(r["score_stable"] for r in repeated) / len(repeated), 4)
        summary["delta_noise_accounts"] = sum(r["delta_noise"] for r in repeated)
    else:
        summary["score_stability"] = None
        summary["delta_noise_accounts"] = None

    # --- per-account table --------------------------------------------------
    header = f"{'account':24} {'facts':>6} {'prec':>6} {'rec':>6} {'grnd':>6} {'ret@k':>6} {'abst':>6} {'score':>10} {'band':>8}"
    print(header)
    print("-" * len(header))
    for row in rows:
        score_cell = f"{row['score_actual']}/{row['score_expected']}"
        band_flag = "" if row["band_actual"] == row["band_expected"] else " !"
        print(
            f"{row['account'][:24]:24} {row['facts_extracted']:>6} "
            f"{row['fact_precision']:>6.2f} {row['fact_recall']:>6.2f} "
            f"{row['citation_groundedness']:>6.2f} {row['retrieval_hit_rate']:>6.2f} "
            f"{row['correct_abstention']:>6.2f} {score_cell:>10} "
            f"{str(row['band_actual']) + band_flag:>8}"
        )

    # --- gates --------------------------------------------------------------
    print("\ngates")
    print("-" * 46)
    failures: list[str] = []
    for metric, gate in manifest["gates"].items():
        actual = summary.get(metric)
        if actual is None:
            print(f"  ----  {metric:24} not measured (needs --runs 2 or more)")
            continue
        ok = actual >= gate
        if not ok:
            failures.append(f"{metric} {actual:.2f} < {gate:.2f}")
        print(f"  {'PASS' if ok else 'FAIL'}  {metric:24} {actual:.2f}  (gate {gate:.2f})")

    noise = summary["delta_noise_accounts"]
    if noise is None:
        print(f"  ----  {'delta_noise':24} not measured (needs --runs 2 or more)")
    elif noise:
        failures.append(f"{noise} account(s) reported changes on an identical re-run")
        print(f"  FAIL  {'delta_noise':24} {noise}  (gate 0)")
    else:
        print(f"  PASS  {'delta_noise':24} 0     (gate 0)")

    # --- what it got wrong --------------------------------------------------
    for row in rows:
        if row["misses"] or row["false_positives"] or row["groundedness_failures"]:
            print(f"\n{row['account']}")
            for miss in row["misses"]:
                print(f"  missed          {miss}")
            for extra in row["false_positives"]:
                print(f"  not in gold     {extra}")
            for failure in row["groundedness_failures"]:
                print(f"  ungrounded      {failure['statement'][:80]} — {failure['why']}")

    # --- write results ------------------------------------------------------
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = settings.eval_results_dir / f"run_{stamp}"
    folder.mkdir(parents=True, exist_ok=True)

    summary["passed"] = not failures
    summary["failures"] = failures
    summary["run_folder"] = folder.name

    with open(folder / "_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    with open(folder / "accounts.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)

    print(f"\n{'PASSED' if not failures else 'FAILED'} — written to eval/results/{folder.name}")
    for failure in failures:
        print(f"  {failure}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
