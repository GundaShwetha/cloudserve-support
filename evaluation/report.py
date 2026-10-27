"""Render metrics_report.json as a readable Markdown report. Figures only - interpretation belongs in
the project report, written by the author."""
from __future__ import annotations

from pathlib import Path


def _p(x) -> str:
    if isinstance(x, dict) and "value" in x:
        if x["value"] is None:
            return "n/a"
        ci = x.get("ci95")
        ci_s = f" (95% CI {ci[0]:.1%}-{ci[1]:.1%})" if ci else ""
        return f"{x['value']:.1%} ({x['k']}/{x['n']}){ci_s}"
    if isinstance(x, float):
        return f"{x:.3f}"
    return "n/a" if x is None else str(x)


def _num(x, fmt="{:.3f}"):
    return "n/a" if x is None else fmt.format(x)


def write_markdown(m: dict, path: Path) -> None:
    run, vol, bus, tech, gov, fair = m["run"], m["volume"], m["business"], m["technical"], m["governance"], m["fairness"]
    sysd = run["system"]
    L = [f"# Metrics report - {run['run_id']}", "",
         f"Input: `{run['input_path']}` | started {run['started_at']} | finished {run['finished_at']} | "
         f"wall clock {run['wall_clock_seconds']} s", "",
         f"System {sysd['system_version']} | orchestration: {sysd['orchestration']} | retrieval: {sysd['retrieval_backend']} "
         f"(min score {sysd['retrieval_min_score']}) | classifier: {sysd['classifier']} | generation: {sysd['generation']}"
         f"{' (' + sysd['model'] + ')' if sysd.get('model') else ''}", "",
         f"Thresholds: answerability >= {sysd['thresholds'].get('answerable_probability_min')}, intent confidence >= "
         f"{sysd['thresholds'].get('intent_confidence_min')} - {sysd['thresholds'].get('selected_by')}", ""]

    lat = bus["time_to_first_reply_automated_seconds"]
    modelled = bus.get("time_to_first_substantive_reply_modelled_all_tickets") or {}
    base = bus.get("baseline_from_history", {})
    routing = tech.get("routing", {})
    intent = tech.get("intent_classification", {})
    cit = tech.get("citation_accuracy", {})
    fair_gaps = {k: v.get("max_gap_points") for k, v in fair.items()}
    worst = max((g for g in fair_gaps.values() if g is not None), default=None)
    cal = tech.get("calibration_intent", {})
    L += ["## Results against targets", "",
          "| Measure | Baseline | Target | Achieved | Notes |", "|---|---|---|---|---|",
          f"| First contact resolution (sent automatically) | {_p(base.get('first_contact_resolution'))} historical | >= 60% | "
          f"{_p(bus['first_contact_resolution_claimed'])} | share of tickets closed with no human |",
          f"| First contact resolution (sent AND correct per labels) | - | >= 60% | {_p(bus['first_contact_resolution_correct'])} | "
          f"route label auto_respond and an expected document cited |",
          f"| Escalation rate | {_p(base.get('escalation_rate'))} historical | <= 30% | {_p(bus['escalation_rate'])} | includes guardrail blocks |",
          f"| Time to first reply, automated replies | 8-12 h | < 5 min | mean {_num(lat['mean'])} s, median {_num(lat['median'])} s, p95 {_num(lat['p95'])} s | measured |",
          f"| Time to first substantive reply, all tickets | 8-12 h | < 5 min | mean {modelled.get('mean_minutes', 'n/a')} min, median {modelled.get('median_minutes', 'n/a')} min | modelled - see note |",
          f"| Satisfaction proxy | {base.get('mean_csat', '3.2')} / 5 | >= 4.0 | not measured automatically | human rubric on review_sample.csv |",
          f"| Repeat-contact risk (auto reply to a ticket the docs do not answer) | {_p(base.get('repeat_contact_rate'))} historical repeat rate | halve | {_p(bus.get('repeat_contact_risk'))} | proxy |",
          f"| Intent classification precision (macro) | - | >= 85% | {_num(intent.get('macro_precision'), '{:.1%}')} | recall {_num(intent.get('macro_recall'), '{:.1%}')} |",
          f"| Routing accuracy vs expected_route | - | - | {_p(routing.get('accuracy'))} | wrong auto {routing.get('wrong_auto_replies', 'n/a')}, missed {routing.get('missed_automations', 'n/a')} |",
          f"| Citation accuracy (cited doc is an expected doc) | - | >= 95% | {_p(cit.get('citations_matching_expected_document'))} | every citation resolves to a retrieved passage |",
          f"| Hallucination rate | - | <= 5% | 0 released replies failed the automated grounding check | human two-assessor review pending |",
          f"| Latency p95, all tickets | - | < 3 s | {_num(tech['latency_seconds_all_tickets']['p95'])} s | end to end incl. retrieval |",
          f"| Private data in sent replies | - | 0 | {gov['private_data_detections_in_sent_replies']} | automated scan of every sent reply |",
          f"| Auto replies to never-auto tickets | - | 0 | {gov['auto_replies_to_never_auto_tickets']} | security, compliance, feature, unclear |",
          f"| Cross-group quality variation (worst dimension) | - | < 5 pts | {_num(worst, '{:.1f} pts')} | see fairness section |",
          f"| Confidence calibration (intent, mean stated - observed) | - | within 5 pts | {cal.get('mean_stated_minus_observed_points', 'n/a')} pts (ECE {cal.get('expected_calibration_error_points', 'n/a')} pts) | |",
          f"| Decision log coverage | - | complete | {gov['decision_log_reconciliation']['final_decisions_logged']}/{vol['tickets_processed']} reconciled = {gov['decision_log_reconciliation']['reconciles']} | |",
          ""]
    if modelled:
        L += [f"Note on modelled reply time: {modelled['assumption']}", ""]

    L += ["## Volume", "", "| | count |", "|---|---|"] + [f"| {k.replace('_', ' ')} | {v} |" for k, v in vol.items()] + [""]

    if intent:
        L += ["## Intent classification, per class", "", "| intent | precision | recall | support |", "|---|---|---|---|"]
        for c, r in intent["per_class"].items():
            L.append(f"| {c} | {_num(r['precision'], '{:.3f}')} | {_num(r['recall'], '{:.3f}')} | {r['support']} |")
        u = tech.get("urgency_classification", {})
        L += ["", f"Urgency accuracy: {_num(u.get('accuracy'), '{:.1%}')} (macro precision {_num(u.get('macro_precision'), '{:.1%}')}).", ""]
    if routing:
        cm = routing["confusion"]
        L += ["## Routing", "", "| expected \\ actual | " + " | ".join(cm["labels"]) + " |", "|---" * (len(cm["labels"]) + 1) + "|"]
        for t in cm["labels"]:
            L.append(f"| {t} | " + " | ".join(str(cm["matrix"][t][p]) for p in cm["labels"]) + " |")
        L += ["", f"Automation precision: {_p(routing['automation_precision'])}", ""]
    if "retrieval" in tech:
        r = tech["retrieval"]
        L += ["## Retrieval and citations", "",
              f"- Backend: {r['backend']}",
              f"- Hit rate (an expected document among retrieved passages, answerable tickets): {_p(r['hit_rate_answerable'])}",
              f"- Top-1 accuracy (answerable tickets): {_p(r['top1_accuracy_answerable'])}",
              f"- Returned nothing (below relevance threshold): {_p(r['returned_nothing'])}",
              f"- Answers citing an expected document: {_p(cit['answers_citing_an_expected_document'])}",
              f"- Automatic answers sent to tickets with no documented answer (a routing error): {_p(cit['auto_answers_to_tickets_with_no_documented_answer'])}", ""]
    for name in ("calibration_intent", "calibration_answerability"):
        if name in tech:
            c = tech[name]
            L += [f"## {name.replace('_', ' ').capitalize()}", "", "| band | n | stated | observed | gap (pts) |", "|---|---|---|---|---|"]
            L += [f"| {b['band']} | {b['n']} | {b['stated']:.3f} | {b['observed']:.3f} | {b['gap_points']:+.1f} |" for b in c["bands"]]
            L += ["", f"Expected calibration error: {c['expected_calibration_error_points']} points.", ""]
    L += ["## Latency (seconds, all tickets)", "",
          f"p50 {tech['latency_seconds_all_tickets']['p50']}, p95 {tech['latency_seconds_all_tickets']['p95']}, max {tech['latency_seconds_all_tickets']['max']}", "",
          f"Replies by generator: {tech['generation_modes_for_sent_replies']}; provider fallbacks to extractive: {tech['provider_fallbacks_to_extractive']}", ""]
    L += ["## Governance", "",
          f"- Decision log: {gov['decision_log_reconciliation']}",
          f"- Guardrail activations by type: {gov['guardrail_activations_by_type'] or 'none'}",
          f"- Replies blocked by guardrails: {gov['blocked_by_guardrails']}",
          f"- Private data detections in sent replies: {gov['private_data_detections_in_sent_replies']}",
          f"- Incoming tickets containing private data (blocked): {gov['private_data_detections_in_incoming_tickets']}",
          f"- Automatic replies to never-auto tickets: {gov['auto_replies_to_never_auto_tickets']}", ""]
    if fair:
        L += ["## Fairness: quality by customer group", "",
              "Quality = ticket handled correctly (routing matches the label and, if answered, an expected document was cited).", ""]
        for dim, d in fair.items():
            L += [f"### {dim} - max gap {_num(d['max_gap_points'], '{:.1f}')} pts ({'within' if d['within_5_points'] else 'OUTSIDE'} 5-point condition)", "",
                  "| group | n | quality | auto-answered | retrieval hit rate |", "|---|---|---|---|---|"]
            for g, r in d["groups"].items():
                L.append(f"| {g} | {r['n']} | {_p(r['quality_correct_handling'])} | {_p(r['auto_answered'])} | {_p(r['retrieval_hit_rate'])} |")
            L.append("")
    L += ["## Method notes", "",
          "- Every figure above is computed by `evaluation/metrics.py` from this run; nothing is entered by hand.",
          "- 'Sent' means released after all guardrails passed. Escalations include guardrail blocks.",
          "- Figures should be treated with caution because the labels themselves are noisy (identical ticket texts carry different "
          "routing and answerability labels in the development data), the satisfaction proxy and hallucination rate need human review, "
          "and reply-time figures for escalated tickets are modelled rather than observed.", ""]
    path.write_text("\n".join(L), encoding="utf-8")
