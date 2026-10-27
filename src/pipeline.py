"""The pipeline: ingest -> classify -> retrieve -> route -> (generate -> validate) -> finalise.

Orchestrated with LangGraph (ADR-01). Routing is a conditional edge, and every branch ends in the
`finalise` node, which writes the decision log for the ticket in one transaction. If LangGraph is not
importable the same nodes and edges run in a small built-in executor, so orchestration can never be
the reason a run fails.

`SupportSystem.process()` never raises: whatever happens, a ticket ends as an automated answer or a
logged escalation (A9 rule 4: none silently dropped), and its decisions are written (A8).
"""
from __future__ import annotations

import logging
import time
import traceback
from typing import Any, Callable, Optional, TypedDict

from . import __version__
from . import monitoring as mon
from .classify import Classifier, load_models
from .config import Settings, load_thresholds
from .generate import TEMPLATE_SENTENCES, Generator, escalation_summary
from .guardrails import blocked, check_input, check_output
from .ingest import load_tickets, normalise
from .logging_store import DecisionLog, sha256
from .provider import make_provider
from .retrieve import Corpus, Retriever, learn_intent_doc_prior, make_backend
from .route import decide
from .schemas import Classification, Draft, GuardrailResult, Outcome, Retrieval, RouteDecision, Ticket

log = logging.getLogger(__name__)

# Which requirement each stage implements (traceability: PRD -> code -> decision log).
REQ = {
    "ingest": ["FR-01"],
    "classification": ["FR-02"],
    "retrieval": ["FR-03"],
    "routing": ["FR-04", "FR-05", "FR-06", "FR-17"],
    "generation": ["FR-08", "FR-09", "FR-10", "FR-11"],
    "validation": ["FR-12", "FR-13", "FR-14", "FR-15"],
    "escalation": ["FR-07"],
    "final": ["FR-16"],
}
_DEFAULT = object()


class State(TypedDict, total=False):
    raw: Any
    index: int
    run_id: str
    t0: float
    ticket: Ticket
    classification: Classification
    retrieval: Retrieval
    input_checks: list
    route: RouteDecision
    draft: Draft
    output_checks: list
    action: str
    final_status: str
    reason: str
    summary: Optional[str]
    rows: list
    errors: list


class SupportSystem:
    def __init__(self, settings: Optional[Settings] = None, provider=_DEFAULT, auto_train: bool = True):
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.thresholds = load_thresholds(self.settings)
        self.corpus = Corpus.load(self.settings.docs_path)
        train = load_tickets(self.settings.train_path) if self.settings.train_path.exists() else []
        models = load_models(self.settings)
        if models is None and auto_train and train:
            from .train import train_and_save

            log.info("no trained classifier found - training on %s", self.settings.train_path)
            train_and_save(self.settings)
            self.thresholds = load_thresholds(self.settings)
            models = load_models(self.settings)
        self.classifier = Classifier(models)
        backend = make_backend(self.corpus, self.settings)
        by_backend = self.thresholds.get("retrieval_min_score_by_backend", {})
        if backend.name not in by_backend and auto_train and train:
            from .train import calibrate_retrieval_threshold, save_retrieval_threshold

            value = calibrate_retrieval_threshold(self.corpus, backend, train, self.classifier)
            save_retrieval_threshold(self.settings, backend.name, value)
            self.thresholds = load_thresholds(self.settings)
            by_backend = self.thresholds.get("retrieval_min_score_by_backend", {})
        min_score = float(by_backend.get(backend.name, self.thresholds.get("retrieval_min_score", 0.2)))
        self.retriever = Retriever(self.corpus, backend, learn_intent_doc_prior(train), min_score)
        self.provider = make_provider(self.settings) if provider is _DEFAULT else provider
        self.generator = Generator(self.corpus, self.provider)
        self.decisions = DecisionLog(self.settings.decision_db)
        self.other_names = sorted({t.customer_name for t in train if t.customer_name})
        self.graph = build_graph(self)
        self.engine = getattr(self.graph, "engine", "langgraph")

    # ------------------------------------------------------------------ helpers
    def automation_enabled(self) -> bool:
        killed = self.settings.kill_switch_path.exists()
        mon.KILL.set(1 if (killed or not self.settings.auto_respond_enabled) else 0)
        return self.settings.auto_respond_enabled and not killed

    def describe(self) -> dict:
        return {
            "system_version": __version__,
            "orchestration": self.engine,
            "retrieval_backend": self.retriever.backend_name,
            "retrieval_min_score": self.retriever.min_score,
            "classifier": self.classifier.version,
            "generation": "llm+extractive-fallback" if self.provider else "extractive",
            "model": getattr(self.provider, "model", None),
            "thresholds": self.thresholds,
            "automation_enabled": self.automation_enabled(),
        }

    def start_run(self, input_path: str = "api") -> str:
        return self.decisions.start_run(input_path, __version__, self.describe())

    # ------------------------------------------------------------------ main entry
    def process(self, raw: Any, run_id: str = "adhoc", index: int = 0) -> Outcome:
        t0 = time.perf_counter()
        state: State = {"raw": raw, "index": index, "run_id": run_id, "t0": t0, "rows": [], "errors": []}
        try:
            state = self.graph.invoke(state)
            return state["outcome"]  # type: ignore[typeddict-item]
        except Exception as exc:  # last line of defence: still escalate and log
            log.exception("pipeline failure")
            return self._emergency(state, raw, run_id, index, t0, exc)

    def process_batch(self, records: list, run_id: str, on_result: Optional[Callable[[Outcome], None]] = None) -> list[Outcome]:
        out = []
        for i, raw in enumerate(records):
            o = self.process(raw, run_id, i)
            out.append(o)
            if on_result:
                on_result(o)
        return out

    def _emergency(self, state, raw, run_id, index, t0, exc) -> Outcome:
        ticket = state.get("ticket") or normalise(raw, index)
        reason = f"internal error ({type(exc).__name__}); escalated to a person so the ticket is not lost"
        outcome = Outcome(ticket.ticket_id, run_id, "escalate", "error_escalated", reason, "", [], reason,
                          state.get("classification"), state.get("retrieval"), state.get("route"), [], "none",
                          time.perf_counter() - t0, ticket.channel, REQ["final"], [traceback.format_exc(limit=3)])
        try:
            self.decisions.write([_row(run_id, ticket, 99, "final", "escalate", reason, prediction="error_escalated")])
        except Exception:
            log.exception("could not write emergency decision")
        mon.TICKETS.labels(channel=ticket.channel, outcome="error_escalated").inc()
        return outcome


def _row(run_id: str, ticket: Ticket, seq: int, stage: str, action: str, reason: str, **kw) -> dict:
    return {"run_id": run_id, "ticket_id": ticket.ticket_id, "seq": seq, "stage": stage, "action_taken": action,
            "reason": reason, "input_summary": ticket.text, "input_sha256": sha256(ticket.text),
            "requirement_ids": REQ.get(stage, []), **kw}


# ====================================================================== graph nodes
def build_graph(system: SupportSystem):
    s = system

    def n_ingest(st: State) -> dict:
        t = normalise(st["raw"], st["index"])
        rows = st["rows"] + [_row(st["run_id"], t, 1, "ingest", "normalised",
                                  "; ".join(t.ingest_warnings) or "normalised without warnings",
                                  prediction=t.channel, model_name="ingest", model_version="1.0")]
        return {"ticket": t, "rows": rows}

    def n_classify(st: State) -> dict:
        t = st["ticket"]
        c = s.classifier.classify(t)
        rows = st["rows"] + [_row(st["run_id"], t, 2, "classification", "classified", c.reason,
                                  prediction=c.intent, confidence=c.intent_confidence,
                                  alternatives=[{"value": a.value, "confidence": a.confidence} for a in c.alternatives]
                                  + [{"value": f"urgency:{c.urgency}", "confidence": c.urgency_confidence},
                                     {"value": "answerable_from_docs", "confidence": c.answerable_probability}],
                                  model_name="tfidf-logreg-calibrated", model_version=c.model_version,
                                  threshold=s.thresholds.get("intent_confidence_min"))]
        return {"classification": c, "rows": rows}

    def n_retrieve(st: State) -> dict:
        t, c = st["ticket"], st["classification"]
        r = s.retriever.retrieve(t.text, None if c.fallback_used else c.intent, c.intent_confidence, s.settings.top_k)
        reason = (f"{len(r.passages)} passage(s) above relevance threshold {r.threshold:.3f}; best score {r.best_score:.3f}"
                  if r.hit else f"nothing cleared the relevance threshold {r.threshold:.3f} (best {r.best_score:.3f}); returned no passages")
        rows = st["rows"] + [_row(st["run_id"], t, 3, "retrieval", "retrieved" if r.hit else "no_hit", reason,
                                  prediction=r.passages[0].doc_id if r.hit else None, confidence=r.best_score,
                                  sources_used=[{"doc_id": p.doc_id, "chunk_id": p.chunk_id, "score": p.score} for p in r.passages],
                                  threshold=r.threshold, model_name=r.backend, model_version=s.corpus.hash)]
        return {"retrieval": r, "rows": rows}

    def n_route(st: State) -> dict:
        t, c, r = st["ticket"], st["classification"], st["retrieval"]
        checks = check_input(t)
        failed = blocked(checks)
        route = decide(c, r, s.thresholds, s.automation_enabled())
        action = route.action
        if failed:
            # Input guardrails override everything: block, escalate, and say which check fired.
            route = RouteDecision("escalate", "Blocked before drafting by guardrail - " + "; ".join(f.detail for f in failed)
                                  + f". (Routing alone would have chosen: {route.action}.)",
                                  route.confidence, "guardrail:" + ",".join(f.name for f in failed), route.threshold)
            action = "block"
        rows = st["rows"] + [_row(st["run_id"], t, 4, "routing", action, route.reason, prediction=route.rule,
                                  confidence=route.confidence, threshold=route.threshold,
                                  guardrail_results={g.name: g.status for g in checks},
                                  sources_used=[{"doc_id": p.doc_id, "score": p.score} for p in r.passages])]
        mon.CONFIDENCE.observe(route.confidence or 0.0)
        return {"route": route, "input_checks": checks, "action": action, "rows": rows}

    def after_route(st: State) -> str:
        return "generate" if st["route"].action == "auto_respond" and st["action"] == "auto_respond" else "escalate"

    def n_generate(st: State) -> dict:
        t, r = st["ticket"], st["retrieval"]
        d = s.generator.generate(t, r)
        if d.provider_error:
            mon.PROVIDER_FAIL.inc()
        reason = (f"drafted by {d.mode} generator ({d.prompt_version})"
                  + (f"; model provider failed ({d.provider_error}) so the extractive generator was used" if d.provider_error else "")
                  + ("; generator stated it cannot answer from the documentation" if d.said_unknown else ""))
        rows = st["rows"] + [_row(st["run_id"], t, 5, "generation", "cannot_answer" if d.said_unknown else "drafted", reason,
                                  model_name=d.model, model_version=d.mode, prompt_version=d.prompt_version,
                                  sources_used=sorted({c for x in d.sentences for c in x.citations}))]
        update: dict = {"draft": d, "rows": rows}
        if d.said_unknown:
            update.update(action="escalate", reason="The drafting step said the documentation does not answer this, so it goes to a person.")
        return update

    def after_generate(st: State) -> str:
        return "escalate" if st["draft"].said_unknown else "validate"

    def n_validate(st: State) -> dict:
        t, r, d = st["ticket"], st["retrieval"], st["draft"]
        min_support = float(s.thresholds.get("grounding_min_support", 0.5))
        checks = check_output(d, r, st.get("route"), t, min_support, s.other_names, TEMPLATE_SENTENCES)
        failed = blocked(checks)
        for f in failed:
            mon.GUARDRAIL.labels(guardrail=f.name).inc()
        reason = ("released: " + "; ".join(f"{g.name}: {g.detail}" for g in checks)) if not failed else \
                 ("BLOCKED: " + "; ".join(f"{g.name}: {g.detail}" for g in failed))
        rows = st["rows"] + [_row(st["run_id"], t, 6, "validation", "block" if failed else "release", reason,
                                  guardrail_results={g.name: {"status": g.status, "detail": g.detail} for g in checks},
                                  prompt_version=d.prompt_version)]
        update: dict = {"output_checks": checks, "rows": rows}
        if failed:
            update.update(action="block", reason="Reply blocked by guardrail(s): " + ", ".join(f.name for f in failed)
                          + ". Escalated to a person; nothing was sent.")
        else:
            update.update(action="auto_respond")
        return update

    def after_validate(st: State) -> str:
        return "finalise" if st["action"] == "auto_respond" else "escalate"

    def n_escalate(st: State) -> dict:
        t, c, r = st["ticket"], st.get("classification"), st.get("retrieval")
        route = st.get("route")
        reason = st.get("reason") or (route.reason if route else "escalated")
        if st.get("action") == "block" and not st.get("reason") and route:
            reason = route.reason
        draft = st.get("draft")
        if (draft is None or not draft.sentences) and r is not None and r.hit:
            draft = s.generator.extractive.draft(r)  # context for the agent, never sent
        summary = escalation_summary(t, c, r, route, reason, draft)
        rows = st["rows"] + [_row(st["run_id"], t, 7, "escalation", "handover", "handover note prepared for agent",
                                  sources_used=[p.chunk_id for p in (r.passages if r else [])],
                                  prompt_version="PR-04 v1.0")]
        action = "block" if st.get("action") == "block" else "escalate"
        return {"summary": summary, "reason": reason, "action": action, "rows": rows}

    def n_finalise(st: State) -> dict:
        t, route = st["ticket"], st.get("route")
        action = st.get("action", "escalate")
        d = st.get("draft")
        latency = time.perf_counter() - st["t0"]
        if action == "auto_respond":
            status, reason = "answered", route.reason if route else "answered"
            text = d.text if d else ""
            cites = sorted({c for x in d.sentences for c in x.citations}) if d else []
        else:
            status = "blocked_escalated" if action == "block" else "escalated"
            reason, text, cites = st.get("reason") or "escalated", "", []
        guards = (st.get("input_checks") or []) + (st.get("output_checks") or [])
        outcome = Outcome(
            ticket_id=t.ticket_id, run_id=st["run_id"], action=action, final_status=status, reason=reason,
            response_text=text, citations=cites, escalation_summary=st.get("summary"),
            classification=st.get("classification"), retrieval=st.get("retrieval"), route=route, guardrails=guards,
            generation_mode=d.mode if d else "none", latency_s=round(latency, 4), channel=t.channel,
            requirement_ids=sorted({r for row in st["rows"] for r in row.get("requirement_ids", [])} | set(REQ["final"])),
            errors=st.get("errors", []),
            provider_error=d.provider_error if d else None,
        )
        rows = st["rows"] + [_row(st["run_id"], t, 9, "final", action, reason, prediction=status,
                                  confidence=route.confidence if route else None,
                                  threshold=route.threshold if route else None,
                                  sources_used=cites,
                                  guardrail_results={g.name: g.status for g in guards},
                                  prompt_version=d.prompt_version if d else None,
                                  model_name=d.model if d else None)]
        s.decisions.write(rows)
        mon.TICKETS.labels(channel=t.channel, outcome=status).inc()
        mon.LATENCY.observe(latency)
        return {"outcome": outcome, "rows": rows, "final_status": status}

    # node names must differ from state keys (LangGraph requirement)
    nodes = {"ingest": n_ingest, "classify": n_classify, "retrieve": n_retrieve, "decide_route": n_route,
             "generate": n_generate, "validate": n_validate, "escalate": n_escalate, "finalise": n_finalise}
    linear = [("ingest", "classify"), ("classify", "retrieve"), ("retrieve", "decide_route"), ("escalate", "finalise")]
    conditional = {"decide_route": (after_route, ["generate", "escalate"]),
                   "generate": (after_generate, ["validate", "escalate"]),
                   "validate": (after_validate, ["finalise", "escalate"])}
    try:
        from langgraph.graph import END, StateGraph

        class _LGState(State, total=False):
            outcome: Outcome

        g = StateGraph(_LGState)
        for name, fn in nodes.items():
            g.add_node(name, fn)
        g.set_entry_point("ingest")
        for a, b in linear:
            g.add_edge(a, b)
        for name, (fn, targets) in conditional.items():
            g.add_conditional_edges(name, fn, {t: t for t in targets})
        g.add_edge("finalise", END)
        compiled = g.compile()
        compiled.engine = "langgraph"  # type: ignore[attr-defined]
        return compiled
    except Exception as exc:
        log.warning("LangGraph unavailable (%s); using the built-in sequential executor", exc)
        return _SimpleGraph(nodes, dict(linear), conditional)


class _SimpleGraph:
    """Minimal executor with the same nodes and edges as the LangGraph graph."""

    engine = "builtin"

    def __init__(self, nodes, linear, conditional):
        self.nodes, self.linear, self.conditional = nodes, linear, conditional

    def invoke(self, state: dict) -> dict:
        node = "ingest"
        for _ in range(20):
            state = {**state, **self.nodes[node](state)}
            if node == "finalise":
                return state
            node = self.conditional[node][0](state) if node in self.conditional else self.linear[node]
        raise RuntimeError("graph did not terminate")
