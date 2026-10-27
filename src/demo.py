"""Live demonstration for the video and for test-procedure steps 6 and 7.

    python -m src.demo

Submits one ticket from each channel, one that must escalate, and two engineered to trigger
guardrails (prompt injection and private data), then prints what happened and why.
"""
from __future__ import annotations

import json
import logging
import textwrap
from pathlib import Path

from .config import ROOT
from .pipeline import SupportSystem

SAMPLES = ROOT / "data" / "samples" / "demo_tickets.json"


def show(o) -> None:
    bar = "=" * 92
    print(bar)
    print(f"{o.ticket_id}  [{o.channel}]  ->  {o.final_status.upper()}   ({o.latency_s * 1000:.0f} ms)")
    if o.classification:
        c = o.classification
        print(f"  intent: {c.intent} ({c.intent_confidence:.2f})  urgency: {c.urgency}  P(docs answer it): {c.answerable_probability:.2f}")
    print("  why: " + textwrap.fill(o.reason, 88, subsequent_indent="       "))
    for g in o.guardrails:
        if g.status == "fail":
            print(f"  GUARDRAIL {g.name}: {g.detail}")
    if o.response_text:
        print("  reply sent to customer:")
        print(textwrap.indent(o.response_text, "    | "))
    elif o.escalation_summary:
        print("  handover note for the agent (nothing sent to the customer):")
        print(textwrap.indent(o.escalation_summary, "    | "))


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    system = SupportSystem()
    d = system.describe()
    print(f"orchestration={d['orchestration']} retrieval={d['retrieval_backend']} generation={d['generation']}")
    run_id = system.start_run(str(SAMPLES))
    tickets = json.loads(Path(SAMPLES).read_text(encoding="utf-8"))
    for i, t in enumerate(tickets):
        show(system.process(t, run_id, i))
    print("=" * 92)
    print("decision log:", system.decisions.reconcile(run_id, len(tickets)))
    print(f"inspect any ticket: GET /decisions/<ticket_id> or the decisions table in {system.settings.decision_db}")


if __name__ == "__main__":
    main()
