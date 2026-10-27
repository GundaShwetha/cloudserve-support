"""Classify: intent, urgency and answerability, each with a calibrated confidence (FR-02, A3).

Design choice (see docs/architecture.md, ADR-02): a supervised TF-IDF + logistic regression model
trained on the 500 development tickets rather than a language-model prompt, because
  * it is deterministic (A5), fast (p95 latency target) and costs nothing per ticket;
  * its probabilities can be calibrated and checked against observed accuracy (governance
    condition: stated confidence within five points of observed accuracy);
  * it records every alternative it considered, not only the winner.
Probabilities are calibrated with cross-validation: isotonic for intent (sigmoid scaling left it
~26 points under-confident), sigmoid (Platt) for urgency and answerability.

If the model cannot be loaded or the text is empty, a defined fallback is returned
(`unclear_request`, confidence 0.0) instead of raising - which the router always escalates.
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .config import Settings
from .schemas import FALLBACK_INTENT, Alternative, Classification, Ticket

log = logging.getLogger(__name__)
MODEL_FILE = "classifier.pkl"
SEED = 42


def _features():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import make_union

    return make_union(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, lowercase=True),
        TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2),
    )


def build_model(C: float = 10.0, calibrate: bool = True, cv: int = 5, method: str = "sigmoid"):
    """A text classifier whose predict_proba output is calibrated (cross-validated Platt or isotonic)."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    base = LogisticRegression(C=C, max_iter=4000, random_state=SEED)
    if calibrate:
        base = CalibratedClassifierCV(base, method=method, cv=cv)
    return make_pipeline(_features(), base)


def ticket_text(t: Ticket) -> str:
    return t.text or ""


@dataclass
class TrainedModels:
    intent: object
    urgency: object
    answerable: object
    version: str
    trained_on: str
    n_train: int


def train_models(tickets: list[Ticket], source: str = "development_tickets.json") -> TrainedModels:
    texts = [ticket_text(t) for t in tickets]
    y_int = [t.labels.get("intent", FALLBACK_INTENT) for t in tickets]
    y_urg = [t.labels.get("urgency", "medium") for t in tickets]
    y_ans = [bool(t.labels.get("answerable_from_docs", False)) for t in tickets]
    digest = hashlib.sha256(
        json.dumps([texts, y_int, y_urg, y_ans], sort_keys=True).encode("utf-8")
    ).hexdigest()[:10]
    intent = build_model(C=10.0, method="isotonic", cv=3).fit(texts, y_int)
    urgency = build_model(C=1.0).fit(texts, y_urg)
    answerable = build_model(C=3.0).fit(texts, y_ans)
    return TrainedModels(intent, urgency, answerable, f"tfidf-lr-{digest}", source, len(tickets))


def save_models(models: TrainedModels, settings: Settings) -> Path:
    settings.model_dir.mkdir(parents=True, exist_ok=True)
    path = settings.model_dir / MODEL_FILE
    with path.open("wb") as f:
        pickle.dump(models, f)
    return path


def load_models(settings: Settings) -> Optional[TrainedModels]:
    path = settings.model_dir / MODEL_FILE
    if not path.exists():
        return None
    try:
        # The pickle is produced locally by `python -m src.train` from the repository's own data;
        # it is never downloaded or accepted from users.
        with path.open("rb") as f:
            return pickle.load(f)
    except Exception as exc:  # corrupt or incompatible artefact -> retrain
        log.warning("could not load classifier (%s); it will be retrained", exc)
        return None


def _ranked(model, text: str, k: int = 3) -> list[tuple[str, float]]:
    proba = model.predict_proba([text])[0]
    classes = list(model.classes_)
    order = np.argsort(-proba)[:k]
    return [(str(classes[i]), float(proba[i])) for i in order]


class Classifier:
    def __init__(self, models: Optional[TrainedModels]):
        self.models = models

    @property
    def version(self) -> str:
        return self.models.version if self.models else "unavailable"

    def classify(self, ticket: Ticket) -> Classification:
        text = ticket_text(ticket)
        if self.models is None:
            return self._fallback("classifier model unavailable")
        if len(text.strip()) < 3:
            return self._fallback("ticket has no readable text")
        try:
            intents = _ranked(self.models.intent, text, k=3)
            urg = _ranked(self.models.urgency, text, k=3)
            ans_classes = list(self.models.answerable.classes_)
            ans_proba = self.models.answerable.predict_proba([text])[0]
            p_ans = float(ans_proba[ans_classes.index(True)]) if True in ans_classes else 0.0
        except Exception as exc:  # never raise out of classification
            log.exception("classification failed")
            return self._fallback(f"classifier error: {exc.__class__.__name__}")
        top_intent, top_conf = intents[0]
        return Classification(
            intent=top_intent,
            intent_confidence=round(top_conf, 4),
            urgency=urg[0][0],
            urgency_confidence=round(urg[0][1], 4),
            answerable_probability=round(p_ans, 4),
            alternatives=[Alternative(v, round(c, 4)) for v, c in intents[1:]],
            model_version=self.version,
            reason=(
                f"intent '{top_intent}' ({top_conf:.2f}); next best "
                + ", ".join(f"'{v}' ({c:.2f})" for v, c in intents[1:])
                + f"; urgency '{urg[0][0]}' ({urg[0][1]:.2f}); P(answerable from docs)={p_ans:.2f}"
            ),
        )

    def _fallback(self, why: str) -> Classification:
        return Classification(
            intent=FALLBACK_INTENT,
            intent_confidence=0.0,
            urgency="medium",
            urgency_confidence=0.0,
            answerable_probability=0.0,
            alternatives=[],
            model_version=self.version,
            fallback_used=True,
            reason=f"fallback: {why}",
        )
