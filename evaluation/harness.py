"""Evaluation harness: one command, one unattended run, a metrics report at the end (A9, A10).

    python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results/validation

* Takes an input path and an output path - it is run against a file it has never seen.
* Processes every record in the file. A ticket that misbehaves is escalated and logged, never skipped.
* Writes results incrementally (results.jsonl), so even an interrupted run leaves evidence.
* Produces metrics_report.json and metrics_report.md, a decision-log export for reconciliation,
  per-segment fairness tables, and a sample of automated replies for the two-person human review.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.config import Settings
from src.ingest import load_records, load_tickets, normalise
from src.pipeline import SupportSystem

from .metrics import compute
from .report import write_markdown

log = logging.getLogger("harness")


def _jsonable(o):
    d = asdict(o)
    if d.get("retrieval"):
        d["retrieval"]["passages"] = [{k: v for k, v in p.items() if k != "text"} for p in d["retrieval"]["passages"]]
    return d


def run(input_path: str, output_dir: str, limit: int | None = None, label: str | None = None) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    settings = Settings()
    system = SupportSystem(settings)
    records = load_records(input_path)
    if limit:
        records = records[:limit]
    tickets = [normalise(r, i) for i, r in enumerate(records)]
    run_id = system.start_run(str(input_path))
    desc = system.describe()
    log.info("run %s: %d tickets from %s | orchestration=%s retrieval=%s generation=%s",
             run_id, len(records), input_path, desc["orchestration"], desc["retrieval_backend"], desc["generation"])

    outcomes = []
    t_start = time.perf_counter()
    with (out / "results.jsonl").open("w", encoding="utf-8") as f:
        for i, raw in enumerate(records):
            o = system.process(raw, run_id, i)
            outcomes.append(o)
            f.write(json.dumps(_jsonable(o), default=str) + "\n")
            f.flush()
            if (i + 1) % 10 == 0 or i + 1 == len(records):
                log.info("  %d/%d processed (%s)", i + 1, len(records), o.final_status)
    wall = time.perf_counter() - t_start

    reconcile = system.decisions.reconcile(run_id, len(outcomes))
    history = [t for t in tickets if t.history] or (
        load_tickets(settings.train_path) if settings.train_path.exists() else [])
    metrics = compute(outcomes, tickets, reconcile, desc, baseline_history=history)
    metrics["run"] = {
        "run_id": run_id, "label": label, "input_path": str(input_path), "output_path": str(out),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wall_clock_seconds": round(wall, 1), "system": desc,
        "baseline_source": "input file history block" if any(t.history for t in tickets) else "development set history block",
    }
    (out / "metrics_report.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    write_markdown(metrics, out / "metrics_report.md")
    _export_decisions(system, run_id, out / "decision_log.csv")
    _write_review_sample(outcomes, tickets, out / "review_sample.csv")
    _write_escalations(outcomes, out / "escalations.jsonl")
    log.info("done in %.1fs - report: %s", wall, out / "metrics_report.md")
    return metrics


def _export_decisions(system: SupportSystem, run_id: str, path: Path) -> None:
    rows = system.decisions.query("SELECT * FROM decisions WHERE run_id=? ORDER BY ticket_id, seq", (run_id,))
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _write_review_sample(outcomes, tickets, path: Path, size: int = 50) -> None:
    """A fixed-seed sample of sent replies for two independent human assessors (hallucination rate,
    citation support and the satisfaction proxy rubric in docs/evaluation_method.md)."""
    sent = [(o, t) for o, t in zip(outcomes, tickets) if o.action == "auto_respond"]
    random.Random(7).shuffle(sent)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "channel", "language_fluency", "ticket_text", "reply", "citations",
                    "assessor_A_unsupported_claims(0/1)", "assessor_B_unsupported_claims(0/1)",
                    "assessor_A_citations_support(0/1)", "assessor_B_citations_support(0/1)",
                    "assessor_A_rubric_1to5", "assessor_B_rubric_1to5", "notes"])
        for o, t in sent[:size]:
            w.writerow([o.ticket_id, t.channel, t.language_fluency, t.text, o.response_text, " ".join(o.citations),
                        "", "", "", "", "", "", ""])


def _write_escalations(outcomes, path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for o in outcomes:
            if o.action != "auto_respond":
                f.write(json.dumps({"ticket_id": o.ticket_id, "status": o.final_status, "reason": o.reason,
                                    "handover": o.escalation_summary}) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the full pipeline over a ticket file, unattended, and report metrics.")
    ap.add_argument("--input", required=True, help="path to a ticket file (JSON list or JSON Lines)")
    ap.add_argument("--output", required=True, help="directory for the results and the metrics report")
    ap.add_argument("--limit", type=int, default=None, help="process only the first N tickets (smoke tests)")
    ap.add_argument("--label", default=None, help="free-text label recorded with the run")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    for noisy in ("httpx", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    m = run(args.input, args.output, args.limit, args.label)
    v = m["volume"]
    print(f"\nProcessed {v['tickets_processed']} tickets: {v['answered_automatically']} answered automatically, "
          f"{v['escalated']} escalated ({v['of_which_blocked_by_guardrails']} blocked by guardrails). "
          f"Decision log reconciles: {m['governance']['decision_log_reconciliation']['reconciles']}.")
    print(f"Report: {Path(args.output) / 'metrics_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
