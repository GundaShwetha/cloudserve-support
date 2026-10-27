"""Train the classifiers and choose every threshold from development data (FR-04, NFR-03).

    python -m src.train            # train, sweep thresholds, write config/thresholds.json + analysis

Only `data/development_tickets.json` is used. The validation set and the hidden set are never read
here, so nothing is tuned against the data the system is assessed on.

Threshold selection rule (documented in docs/threshold_analysis.md):
  * answerable_probability_min - the threshold with the lowest expected cost in a simulation of the full
    routing policy over 5-fold out-of-fold predictions, counting a wrong automatic reply as WRONG_AUTO_COST
    times an unnecessary escalation, subject to zero automatic replies to never-auto classes.
    (Version 1 of the PRD fixed a 90 % automation-precision target instead; the data showed no threshold
    can reach it because of label noise - see the Stage 5 revision log, change R-02.)
  * intent_confidence_min - the lowest confidence at which out-of-fold intent accuracy is >= 95 %.
  * retrieval_min_score (per backend) - the 5th percentile of the score given to the correct article
    for answerable development tickets: 95 % of genuine matches clear it, anything weaker is treated
    as "nothing relevant found" and returns no passages.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .classify import Classifier, TrainedModels, build_model, save_models, train_models
from .config import ROOT, Settings
from .ingest import load_tickets
from .retrieve import Corpus, Retriever, learn_intent_doc_prior, make_backend
from .schemas import INCIDENT_INTENTS, NEVER_AUTO_INTENTS

log = logging.getLogger(__name__)
# Cost of a wrong automatic reply relative to a missed automation (an unnecessary escalation).
# A wrong reply costs the original ticket plus the complaint it creates (Sofia Restrepo: "I will be the one
# who picks up the angry follow-up"), i.e. at least two units of agent work; Marcus Adeyemi ranks it as the
# first failure mode. Sensitivity to this ratio (1x-4x) is reported in docs/threshold_analysis.md.
WRONG_AUTO_COST = 2.0
INTENT_ACCURACY_TARGET = 0.95
SEED = 42


def _read(settings: Settings) -> dict:
    try:
        return json.loads(settings.thresholds_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(settings: Settings, data: dict) -> None:
    settings.thresholds_path.parent.mkdir(parents=True, exist_ok=True)
    settings.thresholds_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def oof_predictions(tickets) -> dict:
    """5-fold out-of-fold calibrated predictions for every development ticket."""
    from sklearn.model_selection import StratifiedKFold

    texts = np.array([t.text for t in tickets], dtype=object)
    y_int = np.array([t.labels["intent"] for t in tickets])
    y_urg = np.array([t.labels["urgency"] for t in tickets])
    y_ans = np.array([bool(t.labels["answerable_from_docs"]) for t in tickets])
    n = len(tickets)
    out = {"intent": np.empty(n, dtype=object), "intent_conf": np.zeros(n), "urgency": np.empty(n, dtype=object),
           "urgency_conf": np.zeros(n), "p_ans": np.zeros(n)}
    skf = StratifiedKFold(5, shuffle=True, random_state=SEED)
    for tr, te in skf.split(texts, y_int):
        mi = build_model(C=10.0, method="isotonic", cv=3).fit(list(texts[tr]), y_int[tr])
        mu = build_model(C=1.0).fit(list(texts[tr]), y_urg[tr])
        ma = build_model(C=3.0).fit(list(texts[tr]), y_ans[tr])
        pi, pu, pa = mi.predict_proba(list(texts[te])), mu.predict_proba(list(texts[te])), ma.predict_proba(list(texts[te]))
        out["intent"][te] = mi.classes_[pi.argmax(1)]
        out["intent_conf"][te] = pi.max(1)
        out["urgency"][te] = mu.classes_[pu.argmax(1)]
        out["urgency_conf"][te] = pu.max(1)
        out["p_ans"][te] = pa[:, list(ma.classes_).index(True)]
    out["y_int"], out["y_urg"], out["y_ans"] = y_int, y_urg, y_ans
    out["y_route"] = np.array([t.labels["expected_route"] for t in tickets])
    out["y_never"] = np.array([bool(t.labels.get("must_not_auto_respond")) for t in tickets])
    return out


def simulate(oof: dict, t_ans: float, t_int: float, hits: np.ndarray) -> dict:
    auto = []
    for i in range(len(oof["intent"])):
        it = oof["intent"][i]
        ok = (it not in NEVER_AUTO_INTENTS
              and not (it in INCIDENT_INTENTS and oof["urgency"][i] == "high")
              and oof["intent_conf"][i] >= t_int and hits[i] and oof["p_ans"][i] >= t_ans)
        auto.append(ok)
    auto = np.array(auto)
    should = oof["y_route"] == "auto_respond"
    n_auto = int(auto.sum())
    return {
        "t_ans": round(t_ans, 2), "auto_rate": auto.mean(), "escalation_rate": 1 - auto.mean(),
        "auto_precision": (should & auto).sum() / n_auto if n_auto else 1.0,
        "auto_recall": (should & auto).sum() / max(1, should.sum()),
        "routing_accuracy": (auto == should).mean(),
        "wrong_auto": int((auto & ~should).sum()), "missed_auto": int((~auto & should).sum()),
        "never_auto_violations": int((auto & oof["y_never"]).sum()),
    }


def calibration_table(conf: np.ndarray, correct: np.ndarray, bands: int = 5) -> list[dict]:
    rows = []
    for i in range(bands):
        lo, hi = i / bands, (i + 1) / bands
        m = (conf >= lo) & ((conf < hi) if i < bands - 1 else (conf <= hi))
        if m.sum() == 0:
            continue
        rows.append({"band": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "stated": float(conf[m].mean()),
                     "observed": float(correct[m].mean()), "gap": float(conf[m].mean() - correct[m].mean())})
    return rows


def ece(conf: np.ndarray, correct: np.ndarray, bands: int = 10) -> float:
    total = 0.0
    for i in range(bands):
        lo, hi = i / bands, (i + 1) / bands
        m = (conf >= lo) & ((conf < hi) if i < bands - 1 else (conf <= hi))
        if m.sum():
            total += m.sum() / len(conf) * abs(conf[m].mean() - correct[m].mean())
    return float(total)


def retrieval_scores(corpus: Corpus, backend, tickets, intents, confs, prior) -> tuple[np.ndarray, np.ndarray]:
    """Best combined score per ticket, and whether the top document is an expected one."""
    r = Retriever(corpus, backend, prior, min_score=-1.0)
    best, correct = [], []
    for t, it, cf in zip(tickets, intents, confs):
        scores = r.doc_scores(t.text, it, float(cf))
        doc, (sc, _, _) = max(scores.items(), key=lambda kv: kv[1][0])
        best.append(sc)
        correct.append(doc in (t.labels.get("expected_doc_ids") or []))
    return np.array(best), np.array(correct)


def calibrate_retrieval_threshold(corpus: Corpus, backend, tickets, classifier: Classifier) -> float:
    preds = [classifier.classify(t) for t in tickets]
    prior = learn_intent_doc_prior(tickets)
    best, correct = retrieval_scores(corpus, backend, tickets, [p.intent for p in preds],
                                     [p.intent_confidence for p in preds], prior)
    answerable = np.array([bool(t.labels.get("answerable_from_docs")) for t in tickets])
    pos = best[answerable & correct]
    return round(float(np.percentile(pos, 5)), 4) if len(pos) else 0.2


def save_retrieval_threshold(settings: Settings, backend_name: str, value: float) -> None:
    data = _read(settings)
    data.setdefault("retrieval_min_score_by_backend", {})[backend_name] = value
    _write(settings, data)


def train_and_save(settings: Settings, analyse: bool = False) -> dict:
    tickets = [t for t in load_tickets(settings.train_path) if t.labels.get("intent")]
    models: TrainedModels = train_models(tickets, settings.train_path.name)
    save_models(models, settings)
    data = _read(settings)
    data.update({"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "classifier_version": models.version, "n_train": len(tickets)})
    if analyse or "answerable_probability_min" not in data:
        data.update(select_thresholds(settings, tickets))
    _write(settings, data)
    return data


def select_thresholds(settings: Settings, tickets) -> dict:
    corpus = Corpus.load(settings.docs_path)
    oof = oof_predictions(tickets)
    correct_int = oof["intent"] == oof["y_int"]

    # intent confidence threshold
    t_int = 0.30
    for cand in np.arange(0.0, 0.96, 0.01):
        m = oof["intent_conf"] >= cand
        if m.sum() and correct_int[m].mean() >= INTENT_ACCURACY_TARGET:
            t_int = max(0.30, round(float(cand), 2))
            break

    # retrieval hits with the local backend (always available) for the routing simulation
    from .retrieve import TfidfBackend

    prior = learn_intent_doc_prior(tickets)
    tf = TfidfBackend(corpus)
    best, top_correct = retrieval_scores(corpus, tf, tickets, oof["intent"], oof["intent_conf"], prior)
    pos = best[oof["y_ans"] & top_correct]
    tfidf_min = round(float(np.percentile(pos, 5)), 4)
    hits = best >= tfidf_min

    sweep = [simulate(oof, float(t), t_int, hits) for t in np.arange(0.30, 0.96, 0.01)]
    for r in sweep:
        r["cost"] = WRONG_AUTO_COST * r["wrong_auto"] + r["missed_auto"]
    safe = [r for r in sweep if r["never_auto_violations"] == 0] or sweep
    # minimum expected cost; ties go to the higher (more cautious) threshold
    chosen = min(safe, key=lambda r: (r["cost"], -r["t_ans"]))
    sensitivity = {}
    for ratio in (1.0, 1.5, 2.0, 3.0, 4.0):
        best = min(safe, key=lambda r: (ratio * r["wrong_auto"] + r["missed_auto"], -r["t_ans"]))
        sensitivity[ratio] = best

    calib_int = calibration_table(oof["intent_conf"], correct_int)
    calib_ans = calibration_table(oof["p_ans"], oof["y_ans"])
    _write_analysis(settings, sweep, chosen, t_int, tfidf_min, oof, calib_int, calib_ans, top_correct, sensitivity)
    return {
        "answerable_probability_min": chosen["t_ans"],
        "intent_confidence_min": t_int,
        "retrieval_min_score": tfidf_min,
        "retrieval_min_score_by_backend": {**_read(settings).get("retrieval_min_score_by_backend", {}), "tfidf": tfidf_min},
        "grounding_min_support": 0.6,
        "selected_by": (f"5-fold out-of-fold simulation on development_tickets.json: minimum expected cost with a wrong "
                        f"automatic reply costing {WRONG_AUTO_COST:g}x a missed automation, zero never-auto violations"),
        "expected_on_development": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in chosen.items()},
    }


def _write_analysis(settings, sweep, chosen, t_int, tfidf_min, oof, calib_int, calib_ans, top_correct, sensitivity) -> None:
    res_dir = ROOT / "evaluation" / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    with (res_dir / "threshold_sweep_development.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sweep[0].keys()))
        w.writeheader()
        for r in sweep:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    lines = [
        "# Threshold analysis (generated by `python -m src.train`)", "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} from `development_tickets.json` only "
        "(5-fold stratified out-of-fold predictions). Validation and hidden sets are not used.", "",
        "## Answerability threshold: the trade-off", "",
        "Each row simulates the full routing policy (never-auto classes, urgent incidents, intent confidence, retrieval "
        "relevance and the answerability threshold) on out-of-fold predictions for the 500 development tickets.", "",
        f"| threshold | auto-answered | escalated | automation precision | wrong auto-replies | missed automations | routing accuracy | cost ({WRONG_AUTO_COST:g}x) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    rows = sorted({id(r): r for r in sweep[::5] + [chosen]}.values(), key=lambda r: r["t_ans"])
    for r in rows:
        mark = " **(chosen)**" if r is chosen else ""
        lines.append(f"| {r['t_ans']:.2f}{mark} | {r['auto_rate']:.1%} | {r['escalation_rate']:.1%} | {r['auto_precision']:.1%} | "
                     f"{r['wrong_auto']} | {r['missed_auto']} | {r['routing_accuracy']:.1%} | {r['cost']:.0f} |")
    best_prec = max(r["auto_precision"] for r in sweep if r["auto_rate"] >= 0.05)
    lines += ["", f"Chosen answerability threshold: **{chosen['t_ans']:.2f}** - minimum expected cost when a wrong automatic "
              f"reply is counted as {WRONG_AUTO_COST:g}x the cost of an unnecessary escalation, with "
              f"{chosen['never_auto_violations']} automatic replies to never-auto classes.", "",
              f"No threshold reaches 90% automation precision on this data (best with at least 5% automation: "
              f"{best_prec:.1%}), because identical ticket texts carry different `answerable_from_docs` labels. "
              "Raising the threshold mostly removes correct automations rather than wrong ones.", "",
              "Sensitivity of the choice to the cost ratio:", "",
              "| wrong reply cost vs escalation | chosen threshold | auto-answered | automation precision |", "|---|---|---|---|"]
    lines += [f"| {k:g}x | {v['t_ans']:.2f} | {v['auto_rate']:.1%} | {v['auto_precision']:.1%} |" for k, v in sensitivity.items()]
    lines += ["",
              f"Intent confidence threshold: **{t_int:.2f}** (out-of-fold intent accuracy "
              f"{(oof['intent'] == oof['y_int']).mean():.1%}).", "",
              f"Local TF-IDF retrieval relevance threshold: **{tfidf_min:.4f}**; top-1 article correct for "
              f"{top_correct[oof['y_ans']].mean():.1%} of answerable development tickets.", "",
              "## Calibration (out-of-fold)", "", "Intent confidence:", "", "| band | n | stated | observed | gap |", "|---|---|---|---|---|"]
    lines += [f"| {r['band']} | {r['n']} | {r['stated']:.3f} | {r['observed']:.3f} | {r['gap']:+.3f} |" for r in calib_int]
    lines += ["", f"Expected calibration error, intent: {ece(oof['intent_conf'], oof['intent'] == oof['y_int']):.3f}", "",
              "P(answerable from docs):", "", "| band | n | stated | observed | gap |", "|---|---|---|---|---|"]
    lines += [f"| {r['band']} | {r['n']} | {r['stated']:.3f} | {r['observed']:.3f} | {r['gap']:+.3f} |" for r in calib_ans]
    lines += ["", f"Expected calibration error, answerability: {ece(oof['p_ans'], oof['y_ans']):.3f}", "",
              "## Label noise ceiling", "",
              "Identical ticket bodies in the development set carry different `answerable_from_docs`, `urgency` and "
              "`expected_route` labels. Grouping exact duplicates, a perfect text-only system could reach at most "
              "~89% routing accuracy and ~73% urgency accuracy on this data. See docs/discovery_evidence.md."]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "threshold_analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Train classifiers and select thresholds from development data.")
    ap.add_argument("--no-analysis", action="store_true", help="train only; keep existing thresholds")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    settings.ensure_dirs()
    data = train_and_save(settings, analyse=not args.no_analysis)
    # retrieval threshold for whichever backend is active on this machine
    corpus = Corpus.load(settings.docs_path)
    backend = make_backend(corpus, settings)
    if backend.name != "tfidf":
        from .classify import load_models

        tickets = [t for t in load_tickets(settings.train_path) if t.labels.get("intent")]
        value = calibrate_retrieval_threshold(corpus, backend, tickets, Classifier(load_models(settings)))
        save_retrieval_threshold(settings, backend.name, value)
        data = _read(settings)
    print(json.dumps({k: data[k] for k in ("answerable_probability_min", "intent_confidence_min",
                                           "retrieval_min_score_by_backend", "classifier_version") if k in data}, indent=2))


if __name__ == "__main__":
    main()
