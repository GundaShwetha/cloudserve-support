"""A9/A10 - one command processes a file it has never seen, unattended, and writes a metrics report."""
import json

from evaluation.harness import main


def test_harness_end_to_end(tmp_env, tmp_path, dev_tickets):
    records = dev_tickets[-12:] + [None, {"channel": "forum"}, "garbage"]
    inp = tmp_path / "unseen.json"
    inp.write_text(json.dumps(records), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--input", str(inp), "--output", str(out)]) == 0
    m = json.loads((out / "metrics_report.json").read_text())
    assert m["volume"]["tickets_processed"] == len(records)
    assert m["volume"]["answered_automatically"] + m["volume"]["escalated"] == len(records)
    assert m["governance"]["decision_log_reconciliation"]["reconciles"]
    for key in ("first_contact_resolution_claimed", "escalation_rate", "time_to_first_reply_automated_seconds"):
        assert key in m["business"]
    for key in ("intent_classification", "retrieval", "latency_seconds_all_tickets"):
        assert key in m["technical"]
    for f in ("metrics_report.md", "results.jsonl", "decision_log.csv", "review_sample.csv"):
        assert (out / f).exists()
    assert sum(1 for _ in open(out / "results.jsonl")) == len(records)


def test_harness_accepts_unlabelled_input(tmp_env, tmp_path):
    inp = tmp_path / "nolabels.jsonl"
    inp.write_text('{"ticket_id": "N1", "channel": "chat", "body": "429 too many requests"}\n', encoding="utf-8")
    assert main(["--input", str(inp), "--output", str(tmp_path / "o2")]) == 0
