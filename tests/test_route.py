"""A5 - routing applies thresholds deterministically and explains itself."""
from src.ingest import normalise
from src.route import decide
from src.schemas import Classification, Passage, Retrieval

TH = {"intent_confidence_min": 0.5, "answerable_probability_min": 0.6}
HIT = Retrieval([Passage("DOC-API-001#resolution", "DOC-API-001", "t", "Resolution", "x", 0.9)], "tfidf", "q", True, 0.9, 0.3)
MISS = Retrieval([], "tfidf", "q", False, 0.1, 0.3)


def C(intent="rate_limit", conf=0.95, urg="medium", p=0.9, fb=False):
    return Classification(intent, conf, urg, 0.6, p, [], "test", fb)


def test_same_input_same_decision(system, dev_tickets):
    for raw in dev_tickets[:30]:
        a = system.process(raw, "determinism-a")
        b = system.process(raw, "determinism-b")
        assert (a.action, a.route.rule, a.citations) == (b.action, b.route.rule, b.citations)


def test_rules():
    assert decide(C(), HIT, TH).action == "auto_respond"
    assert decide(C("security_incident"), HIT, TH).rule == "policy:never_auto_intent"
    assert decide(C("feature_request"), HIT, TH).action == "escalate"
    assert decide(C("database_issue", urg="high"), HIT, TH).rule == "policy:urgent_incident"
    assert decide(C("database_issue", urg="low"), HIT, TH).action == "auto_respond"
    assert decide(C(conf=0.3), HIT, TH).rule == "low_intent_confidence"
    assert decide(C(), MISS, TH).rule == "no_relevant_documentation"
    assert decide(C(p=0.59), HIT, TH).rule == "not_answerable_from_docs"
    assert decide(C(fb=True, conf=0.0), HIT, TH).rule == "confidence_floor"
    assert decide(C(), HIT, TH, automation_enabled=False).rule == "kill_switch"


def test_reasons_are_readable():
    for c, r in [(C(), HIT), (C("security_incident"), HIT), (C(p=0.1), HIT)]:
        reason = decide(c, r, TH).reason
        assert len(reason) > 30 and "_" not in reason.split("(")[0]
