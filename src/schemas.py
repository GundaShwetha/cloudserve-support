"""Internal data structures shared by every component.

Plain dataclasses keep the core independent of the web framework; the API layer converts them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

CHANNELS = ("email", "chat", "docs_comment", "forum")
URGENCIES = ("high", "medium", "low")

# Classes that must never receive an automated reply (Dataset Guide: labels.must_not_auto_respond;
# interviews: Daniel and Sofia on security, Ines on feature requests / roadmap). Requirement FR-05.
NEVER_AUTO_INTENTS = frozenset({"security_incident", "compliance_request", "feature_request", "unclear_request"})

# Intents that describe live production incidents; when urgent they go to a human (Ravi interview,
# development data: every high-urgency performance/database ticket is labelled escalate). FR-06.
INCIDENT_INTENTS = frozenset({"performance_degradation", "database_issue"})

FALLBACK_INTENT = "unclear_request"


@dataclass
class Ticket:
    """One normalised internal representation for all four channels (FR-01)."""

    ticket_id: str
    channel: str
    subject: str
    body: str
    text: str  # what downstream components read: subject + body, cleaned
    received_at: Optional[str]
    customer_id: str
    customer_name: str
    customer_tier: str
    customer_region: str
    language_fluency: str
    original: dict[str, Any] = field(repr=False, default_factory=dict)
    ingest_warnings: list[str] = field(default_factory=list)
    labels: dict[str, Any] = field(default_factory=dict, repr=False)
    history: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self, include_original: bool = False) -> dict:
        d = asdict(self)
        if not include_original:
            d.pop("original", None)
        return d


@dataclass
class Alternative:
    value: str
    confidence: float


@dataclass
class Classification:
    intent: str
    intent_confidence: float
    urgency: str
    urgency_confidence: float
    answerable_probability: float
    alternatives: list[Alternative] = field(default_factory=list)
    model_version: str = "unknown"
    fallback_used: bool = False
    reason: str = ""


@dataclass
class Passage:
    chunk_id: str  # e.g. DOC-AUTH-001#resolution - resolves to a real passage in the corpus
    doc_id: str
    title: str
    section: str
    text: str
    score: float


@dataclass
class Retrieval:
    passages: list[Passage]
    backend: str
    query: str
    hit: bool
    best_score: float
    threshold: float


@dataclass
class RouteDecision:
    action: str  # "auto_respond" | "escalate"
    reason: str
    confidence: float  # calibrated probability that answering automatically is the right call
    rule: str  # which rule decided, e.g. "policy:never_auto_intent"
    threshold: float


@dataclass
class Sentence:
    text: str
    citations: list[str]


@dataclass
class Draft:
    sentences: list[Sentence]
    mode: str  # "llm" | "extractive" | "escalation_summary"
    model: str
    prompt_version: str
    said_unknown: bool = False
    provider_error: Optional[str] = None
    latency_s: float = 0.0

    @property
    def text(self) -> str:
        return render(self.sentences)


def render(sentences: list[Sentence]) -> str:
    parts = []
    for s in sentences:
        cites = "".join(f" [{c}]" for c in s.citations)
        parts.append(f"{s.text.strip()}{cites}")
    return "\n".join(parts)


@dataclass
class GuardrailResult:
    name: str
    status: str  # "pass" | "fail" | "skipped"
    detail: str = ""


@dataclass
class Outcome:
    """What happened to one ticket. Every ticket ends in exactly one of these (A9, A8)."""

    ticket_id: str
    run_id: str
    action: str  # "auto_respond" | "escalate" | "block"
    final_status: str  # "answered" | "escalated" | "blocked_escalated" | "error_escalated"
    reason: str
    response_text: str
    citations: list[str]
    escalation_summary: Optional[str]
    classification: Optional[Classification]
    retrieval: Optional[Retrieval]
    route: Optional[RouteDecision]
    guardrails: list[GuardrailResult]
    generation_mode: str
    latency_s: float
    channel: str
    requirement_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    provider_error: Optional[str] = None

    @property
    def escalated(self) -> bool:
        return self.action != "auto_respond"

    def to_dict(self) -> dict:
        return asdict(self)
