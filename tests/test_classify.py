"""A3 - every ticket gets intent and urgency with a numeric confidence in [0, 1]."""
from src.classify import Classifier
from src.ingest import normalise


def test_classification_has_confidences(system, dev_tickets):
    for raw in dev_tickets[:25]:
        c = system.classifier.classify(normalise(raw))
        assert c.intent and c.urgency in {"high", "medium", "low"}
        for v in (c.intent_confidence, c.urgency_confidence, c.answerable_probability):
            assert 0.0 <= v <= 1.0
        assert len(c.alternatives) == 2  # alternatives considered are recorded


def test_defined_fallback_instead_of_exception(system):
    c = system.classifier.classify(normalise({"channel": "chat", "body": ""}))
    assert c.fallback_used and c.intent == "unclear_request" and c.intent_confidence == 0.0
    c2 = Classifier(None).classify(normalise({"body": "my deployment fails"}))
    assert c2.fallback_used and "unavailable" in c2.reason
