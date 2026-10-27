"""Chunking and retrieval comparison on development tickets (Setup Guide: "try at least two
configurations, measure the difference in retrieval quality, and record which you chose and why").

    python -m evaluation.retrieval_experiment            # uses every backend available on this machine

Measures, for answerable development tickets: top-1 article accuracy, hit@3, and whether a passage
returned to the generator contains the complete numbered resolution. Results go to
evaluation/results/retrieval_experiment.md. Uses development data only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.config import ROOT, Settings
from src.ingest import load_tickets
from src.retrieve import ChromaBackend, Corpus, Retriever, TfidfBackend, learn_intent_doc_prior


def _resolution_text(corpus: Corpus, doc_id: str) -> str:
    content = corpus.docs[doc_id]["content"]
    start = content.find("## Resolution")
    end = content.find("## ", start + 5)
    return content[start:end if end > 0 else None]


def _steps(text: str) -> list[str]:
    import re

    return [m.group(1).strip() for m in re.finditer(r"^\s*\d+\.\s+(.*)$", text, re.M)]


def evaluate(corpus: Corpus, backend, tickets, prior_weight: float, prior) -> dict:
    r = Retriever(corpus, backend, prior, min_score=-1.0)
    r.PRIOR_WEIGHT = prior_weight
    top1 = hit3 = complete = 0
    ans = [t for t in tickets if t.labels.get("answerable_from_docs") and t.labels.get("expected_doc_ids")]
    for t in ans:
        exp = set(t.labels["expected_doc_ids"])
        scores = r.doc_scores(t.text, t.labels["intent"] if prior_weight else None, 1.0 if prior_weight else 0.0)
        ranked = [d for d, _ in sorted(scores.items(), key=lambda kv: -kv[1][0])]
        top1 += ranked[0] in exp
        hit3 += bool(set(ranked[:3]) & exp)
        # Would the generator receive the article's complete numbered resolution in one passage?
        res = corpus.resolution_chunk(ranked[0]) or corpus.resolve(scores[ranked[0]][2])
        steps = _steps(_resolution_text(corpus, ranked[0]))
        complete += bool(res and steps and all(st[:60] in res.text for st in steps))
    n = len(ans)
    return {"n": n, "top1": round(top1 / n, 4), "hit@3": round(hit3 / n, 4), "complete_resolution_available": round(complete / n, 4)}


def main() -> None:
    s = Settings()
    tickets = load_tickets(s.train_path)
    prior = learn_intent_doc_prior(tickets)
    docs = json.loads(s.docs_path.read_text(encoding="utf-8"))
    rows = []
    for chunking in ("section", "fixed"):
        corpus = Corpus(docs, chunking)
        backends = [("tfidf", lambda c=corpus: TfidfBackend(c))]
        backends.append(("chroma-minilm", lambda c=corpus: ChromaBackend(c, s)))
        for name, make in backends:
            try:
                be = make()
            except Exception as exc:
                rows.append({"chunking": chunking, "backend": name, "error": f"{type(exc).__name__}: {exc}"[:120]})
                continue
            for pw in (0.0, 0.35):
                res = evaluate(corpus, be, tickets, pw, prior)
                rows.append({"chunking": chunking, "backend": name, "chunks": len(corpus.chunks), "intent_prior_weight": pw, **res})
    lines = ["# Retrieval experiment (development tickets, answerable only)", "",
             f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `python -m evaluation.retrieval_experiment`.", "",
             "| chunking | backend | chunks | intent prior | top-1 | hit@3 | full resolution passed to generator |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['chunking']} | {r['backend']} | - | - | unavailable: {r['error']} | | |")
        else:
            lines.append(f"| {r['chunking']} | {r['backend']} | {r['chunks']} | {r['intent_prior_weight']} | {r['top1']:.1%} | "
                         f"{r['hit@3']:.1%} | {r['complete_resolution_available']:.1%} |")
    lines += ["", "Note: the intent prior here uses the true intent label (an upper bound); in the running system it uses the "
              "predicted intent weighted by its confidence."]
    out = ROOT / "evaluation" / "results" / "retrieval_experiment.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
