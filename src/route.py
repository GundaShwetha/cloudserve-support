"""Route: answer automatically or escalate, and say why in plain language (FR-04..FR-07, A5).

The decision is a pure function of (classification, retrieval, thresholds, kill switch), so the
same ticket always produces the same decision (A5). Rules are checked in a fixed order; the first
that fires decides, and its name and a sentence a support manager can read are recorded.

    1. kill switch / automation disabled                    -> escalate
    2. classifier fell back or gave no confidence           -> escalate  (confidence floor guardrail)
    3. intent is one that must never be auto-answered       -> escalate  (policy)
    4. urgent production incident (performance / database) -> escalate  (policy)
    5. intent confidence below threshold                    -> escalate
    6. no documentation passage cleared the relevance bar  -> escalate
    7. P(answerable from docs) below threshold              -> escalate
    otherwise                                               -> auto_respond

Thresholds in rules 5-7 are chosen from cross-validated development data by `python -m src.train`
(see config/thresholds.json and docs/threshold_analysis.md), not picked because they looked right.
"""
from __future__ import annotations

from .schemas import INCIDENT_INTENTS, NEVER_AUTO_INTENTS, Classification, Retrieval, RouteDecision

_PRETTY = lambda s: s.replace("_", " ")  # noqa: E731


def decide(c: Classification, r: Retrieval, thresholds: dict, automation_enabled: bool = True) -> RouteDecision:
    t_int = float(thresholds.get("intent_confidence_min", 0.5))
    t_ans = float(thresholds.get("answerable_probability_min", 0.75))
    # Probability that answering automatically is right: answerable AND intent correct.
    conf = round(float(c.answerable_probability) * float(c.intent_confidence), 4)

    def esc(rule: str, reason: str) -> RouteDecision:
        return RouteDecision("escalate", reason, conf, rule, t_ans)

    if not automation_enabled:
        return esc("kill_switch", "Automatic replies are switched off (kill switch), so every ticket goes to an agent.")
    if c.fallback_used or c.intent_confidence is None or c.intent_confidence <= 0:
        return esc("confidence_floor", "The system could not classify this ticket with any confidence, so a person should read it.")
    if c.intent in NEVER_AUTO_INTENTS:
        return esc(
            "policy:never_auto_intent",
            f"This looks like a {_PRETTY(c.intent)} ticket. Company policy is that these are always handled by a person.",
        )
    if c.intent in INCIDENT_INTENTS and c.urgency == "high":
        return esc(
            "policy:urgent_incident",
            f"This looks like an urgent {_PRETTY(c.intent)} affecting production, so it goes straight to an engineer.",
        )
    if c.intent_confidence < t_int:
        return esc(
            "low_intent_confidence",
            f"The system is only {c.intent_confidence:.0%} sure what this ticket is about (needs {t_int:.0%}).",
        )
    if not r.hit:
        return esc(
            "no_relevant_documentation",
            "No documentation article was a close enough match to answer from, so a person should reply.",
        )
    if c.answerable_probability < t_ans:
        return esc(
            "not_answerable_from_docs",
            f"The documentation probably does not fully answer this (estimated {c.answerable_probability:.0%} chance it does; "
            f"needs {t_ans:.0%}), so it goes to an agent with the closest articles attached.",
        )
    return RouteDecision(
        "auto_respond",
        f"Clear '{_PRETTY(c.intent)}' ticket ({c.intent_confidence:.0%} sure) that the documentation answers "
        f"({c.answerable_probability:.0%} likely); answered automatically with citations.",
        conf,
        "auto:answerable",
        t_ans,
    )
