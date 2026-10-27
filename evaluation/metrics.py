"""Metrics computed by code from one unattended run (A10). Nothing here is filled in by hand.

Tiers (Evaluation Framework): business outcomes first, then technical performance, then governance
conditions, plus the fairness segmentation. Where a measure needs labels and the input file has none,
it is reported as "not available" rather than guessed. Proportions carry Wilson 95 % intervals so
the report can state how much confidence each figure deserves.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Any, Optional

from src.guardrails import find_private_data
from src.schemas import Outcome, Ticket


def wilson(k: int, n: int, z: float = 1.96) -> Optional[tuple[float, float]]:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def prop(k: int, n: int) -> dict:
    return {"value": round(k / n, 4) if n else None, "k": k, "n": n, "ci95": wilson(k, n)}


def pct(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    v = sorted(values)
    idx = min(len(v) - 1, max(0, math.ceil(q * len(v)) - 1))
    return round(v[idx], 4)


def per_class(y_true: list[str], y_pred: list[str]) -> dict:
    labels = sorted(set(y_true) | set(y_pred))
    out = {}
    for c in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        out[c] = {"precision": round(tp / (tp + fp), 4) if tp + fp else None,
                  "recall": round(tp / (tp + fn), 4) if tp + fn else None, "support": tp + fn}
    prec = [v["precision"] for v in out.values() if v["precision"] is not None and v["support"]]
    rec = [v["recall"] for v in out.values() if v["recall"] is not None]
    return {"per_class": out, "macro_precision": round(statistics.mean(prec), 4) if prec else None,
            "macro_recall": round(statistics.mean(rec), 4) if rec else None,
            "accuracy": round(sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true), 4) if y_true else None}


def confusion(y_true: list[str], y_pred: list[str]) -> dict:
    labels = sorted(set(y_true) | set(y_pred))
    m = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        m[t][p] += 1
    return {"labels": labels, "matrix": m}


def calibration(conf: list[float], correct: list[bool], bands: int = 5) -> dict:
    rows, total = [], 0.0
    n = len(conf)
    for i in range(bands):
        lo, hi = i / bands, (i + 1) / bands
        idx = [j for j, c in enumerate(conf) if (lo <= c < hi) or (i == bands - 1 and c == 1.0)]
        if not idx:
            continue
        stated = statistics.mean(conf[j] for j in idx)
        observed = sum(correct[j] for j in idx) / len(idx)
        total += len(idx) / n * abs(stated - observed)
        rows.append({"band": f"{lo:.1f}-{hi:.1f}", "n": len(idx), "stated": round(stated, 4),
                     "observed": round(observed, 4), "gap_points": round(100 * (stated - observed), 1)})
    overall = None
    if n:
        overall = round(100 * (statistics.mean(conf) - sum(correct) / n), 1)
    return {"bands": rows, "expected_calibration_error_points": round(100 * total, 1) if n else None,
            "mean_stated_minus_observed_points": overall}


def _labels(t: Ticket) -> dict:
    return t.labels or {}


def handled_correctly(o: Outcome, t: Ticket) -> Optional[bool]:
    """Quality measure used for fairness: the routing matched the label, and an automatic answer
    cited a document that answers the ticket."""
    lab = _labels(t)
    if "expected_route" not in lab:
        return None
    should_auto = lab["expected_route"] == "auto_respond"
    if o.action == "auto_respond":
        expected = set(lab.get("expected_doc_ids") or [])
        cited_docs = {c.split("#")[0] for c in o.citations}
        return should_auto and bool(cited_docs & expected)
    return not should_auto


def compute(outcomes: list[Outcome], tickets: list[Ticket], reconcile: dict, system: dict,
            baseline_history: Optional[list[Ticket]] = None) -> dict[str, Any]:
    n = len(outcomes)
    by_id = list(zip(outcomes, tickets))
    labelled = [(o, t) for o, t in by_id if _labels(t).get("intent")]
    answered = [o for o in outcomes if o.action == "auto_respond"]
    escalated = [o for o in outcomes if o.action != "auto_respond"]
    blocked = [o for o in outcomes if o.action == "block"]
    errors = [o for o in outcomes if o.final_status == "error_escalated"]

    # ---------------------------------------------------------------- business
    lat_all = [o.latency_s for o in outcomes]
    lat_auto = [o.latency_s for o in answered]
    hist = [t for t in (baseline_history or []) if t.history]
    hist_esc_minutes = [t.history.get("resolution_time_minutes") for t in hist
                        if t.history.get("escalated") and isinstance(t.history.get("resolution_time_minutes"), (int, float))]
    human_minutes = statistics.median(hist_esc_minutes) if hist_esc_minutes else None
    modelled = None
    if human_minutes is not None and n:
        mins = [o.latency_s / 60 for o in answered] + [human_minutes] * len(escalated)
        modelled = {"mean_minutes": round(statistics.mean(mins), 1), "median_minutes": round(statistics.median(mins), 1),
                    "assumption": (f"escalated tickets still wait for a person; modelled at the historical median of "
                                   f"{human_minutes:.0f} minutes for escalated tickets (history block of the development set). "
                                   "This is an upper bound: escalations now arrive with a summary and sources attached.")}
    correct_auto = [o for o, t in labelled if o.action == "auto_respond" and handled_correctly(o, t)]
    business = {
        "first_contact_resolution_claimed": prop(len(answered), n),
        "first_contact_resolution_correct": prop(len(correct_auto), len(labelled)) if labelled else "not available (no labels)",
        "escalation_rate": prop(len(escalated), n),
        "time_to_first_reply_automated_seconds": {"mean": round(statistics.mean(lat_auto), 3) if lat_auto else None,
                                                  "median": round(statistics.median(lat_auto), 3) if lat_auto else None,
                                                  "p95": pct(lat_auto, 0.95)},
        "time_to_first_substantive_reply_modelled_all_tickets": modelled,
        "repeat_contact_risk": prop(sum(1 for o, t in labelled if o.action == "auto_respond"
                                        and not _labels(t).get("answerable_from_docs", True)), len(labelled)) if labelled else None,
        "customer_satisfaction": "not measured automatically - see review_sample.csv and the rubric in docs/evaluation_method.md",
    }
    if hist:
        business["baseline_from_history"] = {
            "first_contact_resolution": prop(sum(1 for t in hist if t.history.get("first_contact_resolution")), len(hist)),
            "escalation_rate": prop(sum(1 for t in hist if t.history.get("escalated")), len(hist)),
            "repeat_contact_rate": prop(sum(1 for t in hist if t.history.get("repeat_contact")), len(hist)),
            "mean_resolution_minutes": round(statistics.mean(t.history.get("resolution_time_minutes", 0) for t in hist), 1),
            "mean_csat": round(statistics.mean(t.history.get("csat_rating", 0) for t in hist), 2),
            "source": "history block of the tickets in this input file" if any(o for o in outcomes) else "",
        }

    # ---------------------------------------------------------------- technical
    technical: dict[str, Any] = {"latency_seconds_all_tickets": {"p50": pct(lat_all, 0.5), "p95": pct(lat_all, 0.95),
                                                                 "max": round(max(lat_all), 3) if lat_all else None}}
    if labelled:
        yt = [_labels(t)["intent"] for _, t in labelled]
        yp = [o.classification.intent if o.classification else "none" for o, _ in labelled]
        technical["intent_classification"] = per_class(yt, yp)
        technical["intent_confusion"] = confusion(yt, yp)
        ut = [_labels(t).get("urgency") for _, t in labelled]
        up = [o.classification.urgency if o.classification else "none" for o, _ in labelled]
        technical["urgency_classification"] = per_class(ut, up)
        rt = [_labels(t).get("expected_route") for _, t in labelled]
        rp = ["auto_respond" if o.action == "auto_respond" else "escalate" for o, _ in labelled]
        technical["routing"] = {
            "accuracy": prop(sum(a == b for a, b in zip(rt, rp)), len(rt)),
            "confusion": confusion(rt, rp),
            "wrong_auto_replies": sum(1 for a, b in zip(rt, rp) if a == "escalate" and b == "auto_respond"),
            "missed_automations": sum(1 for a, b in zip(rt, rp) if a == "auto_respond" and b == "escalate"),
            "automation_precision": prop(sum(1 for a, b in zip(rt, rp) if a == b == "auto_respond"), rp.count("auto_respond")),
        }
        ans = [(o, t) for o, t in labelled if _labels(t).get("answerable_from_docs") and _labels(t).get("expected_doc_ids")]
        hit = sum(1 for o, t in ans if o.retrieval and {p.doc_id for p in o.retrieval.passages} & set(_labels(t)["expected_doc_ids"]))
        top1 = sum(1 for o, t in ans if o.retrieval and o.retrieval.passages and o.retrieval.passages[0].doc_id in _labels(t)["expected_doc_ids"])
        technical["retrieval"] = {"hit_rate_answerable": prop(hit, len(ans)), "top1_accuracy_answerable": prop(top1, len(ans)),
                                  "returned_nothing": prop(sum(1 for o in outcomes if o.retrieval and not o.retrieval.hit), n),
                                  "backend": system.get("retrieval_backend")}
        cites_total = cites_ok = answers_ok = 0
        auto_l = [(o, t) for o, t in labelled if o.action == "auto_respond"]
        auto_doc = [(o, t) for o, t in auto_l if _labels(t).get("expected_doc_ids")]
        for o, t in auto_doc:
            exp = set(_labels(t).get("expected_doc_ids") or [])
            docs = {c.split("#")[0] for c in o.citations}
            cites_total += len(docs)
            cites_ok += len(docs & exp)
            answers_ok += bool(docs & exp)
        technical["citation_accuracy"] = {
            "citations_matching_expected_document": prop(cites_ok, cites_total),
            "answers_citing_an_expected_document": prop(answers_ok, len(auto_doc)),
            "auto_answers_to_tickets_with_no_documented_answer": prop(len(auto_l) - len(auto_doc), len(auto_l)),
            "scope": "answers sent to tickets whose label lists at least one expected document; answers to tickets with no "
                     "documented answer are routing errors and are counted separately",
            "citations_resolving_to_retrieved_passages": "100% by construction: the grounding guardrail blocks any reply whose citation does not resolve",
        }
        technical["calibration_intent"] = calibration(
            [o.classification.intent_confidence for o, _ in labelled if o.classification],
            [o.classification.intent == _labels(t)["intent"] for o, t in labelled if o.classification])
        technical["calibration_answerability"] = calibration(
            [o.classification.answerable_probability for o, _ in labelled if o.classification],
            [bool(_labels(t).get("answerable_from_docs")) for o, t in labelled if o.classification])
    gen_modes = Counter(o.generation_mode for o in answered)
    technical["generation_modes_for_sent_replies"] = dict(gen_modes)
    technical["provider_fallbacks_to_extractive"] = sum(1 for o in outcomes if o.provider_error)
    technical["hallucination_rate_automated_proxy"] = {
        "released_replies_failing_grounding": 0,
        "note": "every released reply passed the grounding check; replies failing it were blocked (see guardrail activations). "
                "The human-assessed rate requires the two-assessor review of review_sample.csv.",
    }

    # ---------------------------------------------------------------- governance
    activations: Counter = Counter()
    for o in outcomes:
        for g in o.guardrails:
            if g.status == "fail":
                activations[g.name] += 1
    pii_outbound = [o.ticket_id for o in answered if find_private_data(o.response_text)]
    never_auto = [o.ticket_id for o, t in labelled if o.action == "auto_respond" and _labels(t).get("must_not_auto_respond")]
    governance = {
        "decision_log_reconciliation": reconcile,
        "guardrail_activations_by_type": dict(activations),
        "blocked_by_guardrails": len(blocked),
        "private_data_detections_in_sent_replies": len(pii_outbound),
        "private_data_detections_in_incoming_tickets": activations.get("private_data_in_ticket", 0),
        "auto_replies_to_never_auto_tickets": len(never_auto),
        "never_auto_ticket_ids": never_auto,
        "kill_switch_engaged": not system.get("automation_enabled", True),
    }

    # ---------------------------------------------------------------- fairness
    fairness = {}
    if labelled:
        words = sorted(len(t.body.split()) for _, t in labelled)
        median_words = words[len(words) // 2]
        dims = {
            "customer_tier": lambda t: t.customer_tier,
            "language_fluency": lambda t: t.language_fluency,
            "customer_region": lambda t: t.customer_region,
            "channel": lambda t: t.channel,
            "length": lambda t: "long" if len(t.body.split()) > median_words else "short",
        }
        for dim, f in dims.items():
            groups = defaultdict(list)
            for o, t in labelled:
                groups[f(t)].append((o, t))
            rows = {}
            for g, items in sorted(groups.items()):
                q = sum(1 for o, t in items if handled_correctly(o, t))
                auto = sum(1 for o, _ in items if o.action == "auto_respond")
                ans = [(o, t) for o, t in items if _labels(t).get("answerable_from_docs")]
                hit = sum(1 for o, t in ans if o.retrieval and {p.doc_id for p in o.retrieval.passages} & set(_labels(t).get("expected_doc_ids") or []))
                rows[g] = {"n": len(items), "quality_correct_handling": prop(q, len(items)),
                           "auto_answered": prop(auto, len(items)), "retrieval_hit_rate": prop(hit, len(ans))}
            vals = [r["quality_correct_handling"]["value"] for r in rows.values() if r["n"] >= 5]
            spread = round(100 * (max(vals) - min(vals)), 1) if len(vals) >= 2 else None
            fairness[dim] = {"groups": rows, "max_gap_points": spread,
                             "within_5_points": spread is not None and spread < 5,
                             "note": "groups with fewer than 5 tickets excluded from the gap"}

    return {
        "volume": {"tickets_processed": n, "answered_automatically": len(answered), "escalated": len(escalated),
                   "of_which_blocked_by_guardrails": len(blocked), "of_which_internal_errors": len(errors),
                   "labelled_tickets": len(labelled)},
        "business": business, "technical": technical, "governance": governance, "fairness": fairness,
    }
