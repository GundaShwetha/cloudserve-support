"""End to end: each channel, escalation with context, guardrail blocks, decision log (A2, A7, A8)."""
import json

from src.ingest import normalise

SAMPLES = json.loads(open("data/samples/demo_tickets.json", encoding="utf-8").read())
BY_ID = {t["ticket_id"]: t for t in SAMPLES}


def test_each_channel_end_to_end(system):
    run = system.start_run("test-channels")
    for tid in ("DEMO-EMAIL-01", "DEMO-CHAT-02", "DEMO-DOCS-03", "DEMO-FORUM-04"):
        o = system.process(BY_ID[tid], run)
        assert o.final_status == "answered", (tid, o.reason)
        assert o.citations and all(system.corpus.resolve(c) for c in o.citations)
        assert "drafted automatically" in o.response_text  # customers are told it is automated


def test_escalation_carries_summary_and_reason(system):
    o = system.process(BY_ID["DEMO-ESCALATE-05"], system.start_run("test-esc"))
    assert o.action == "escalate" and o.response_text == ""
    assert "security incident" in o.reason
    assert "Why it was escalated" in o.escalation_summary and "unsure" in o.escalation_summary


def test_engineered_tickets_are_blocked(system):
    run = system.start_run("test-block")
    for tid in ("DEMO-GUARDRAIL-06", "DEMO-GUARDRAIL-07"):
        o = system.process(BY_ID[tid], run)
        assert o.action == "block" and o.final_status == "blocked_escalated" and o.response_text == ""
        assert any(g.status == "fail" for g in o.guardrails)


def test_output_guardrail_blocks_a_bad_model_reply(settings, fake_provider):
    from src.pipeline import SupportSystem

    leaky = json.dumps({"cannot_answer": False, "sentences": [
        {"text": "A refund has been issued and you can email ops@cloudserve.example for details.", "citations": ["DOC-API-001#resolution"]}]})
    s = SupportSystem(settings, provider=fake_provider([leaky]))
    o = s.process(BY_ID["DEMO-EMAIL-01"], s.start_run("test-output-block"))
    assert o.action == "block", o.reason
    failed = {g.name for g in o.guardrails if g.status == "fail"}
    assert {"private_data", "tone_and_scope"} <= failed
    rows = s.decisions.for_ticket("DEMO-EMAIL-01", o.run_id)
    val = [r for r in rows if r["stage"] == "validation"][0]
    assert val["action_taken"] == "block" and "private_data" in val["guardrail_results"]


def test_decision_log_has_required_fields_and_reconciles(system, dev_tickets):
    run = system.start_run("test-log")
    for raw in dev_tickets[:15]:
        system.process(raw, run)
    rec = system.decisions.reconcile(run, 15)
    assert rec["reconciles"] and rec["final_decisions_logged"] == 15
    row = system.decisions.query("SELECT * FROM decisions WHERE run_id=? AND stage='routing' LIMIT 1", (run,))[0]
    for field in ("decision_id", "created_at", "ticket_id", "stage", "input_summary", "prediction", "confidence",
                  "sources_used", "threshold", "action_taken", "reason", "guardrail_results", "requirement_ids"):
        assert field in row
    assert row["reason"]


def test_log_masks_secrets(system):
    run = system.start_run("test-mask")
    system.process(BY_ID["DEMO-GUARDRAIL-07"], run)
    rows = system.decisions.query("SELECT input_summary FROM decisions WHERE run_id=?", (run,))
    assert rows and all("sk_live" not in r["input_summary"] and "@example.com" not in r["input_summary"] for r in rows)
