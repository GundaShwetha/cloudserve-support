"""FastAPI service.  Start with:  python -m src.api   (docs at http://127.0.0.1:8000/docs)

Endpoints
  POST /tickets              process one ticket from any channel
  POST /tickets/batch        process a list of tickets
  GET  /decisions/{id}       the decision log for a ticket (audit / "why did it do that?")
  GET  /health               liveness plus which backends are active
  GET  /metrics              Prometheus metrics
  GET  /kill-switch          is automatic replying switched off?
  POST /kill-switch          switch automatic replies off/on (requires ADMIN_TOKEN)
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from . import killswitch
from .config import Settings
from .pipeline import SupportSystem

log = logging.getLogger(__name__)


class TicketIn(BaseModel):
    """Any of the four channels. Unknown extra fields are accepted and preserved."""

    model_config = {"extra": "allow"}
    ticket_id: Optional[str] = None
    channel: Optional[str] = Field(None, description="email | chat | docs_comment | forum")
    subject: Optional[str] = ""
    body: Optional[str] = ""
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_tier: Optional[str] = None
    customer_region: Optional[str] = None
    language_fluency: Optional[str] = None
    received_at: Optional[str] = None


class KillSwitchIn(BaseModel):
    engaged: bool
    reason: str = ""


@lru_cache(maxsize=1)
def system() -> SupportSystem:
    return SupportSystem()


@lru_cache(maxsize=1)
def api_run_id() -> str:
    return system().start_run("api")


def _out(o) -> dict[str, Any]:
    return {
        "ticket_id": o.ticket_id,
        "status": o.final_status,
        "action": o.action,
        "reason": o.reason,
        "reply": o.response_text or None,
        "citations": o.citations,
        "handover_summary_for_agent": o.escalation_summary,
        "intent": o.classification.intent if o.classification else None,
        "intent_confidence": o.classification.intent_confidence if o.classification else None,
        "urgency": o.classification.urgency if o.classification else None,
        "route_confidence": o.route.confidence if o.route else None,
        "guardrails": [{"name": g.name, "status": g.status, "detail": g.detail} for g in o.guardrails],
        "generation_mode": o.generation_mode,
        "latency_seconds": o.latency_s,
        "run_id": o.run_id,
    }


app = FastAPI(title="CloudServe support triage", version=__version__,
              description="Classifies, retrieves, routes, drafts grounded answers and escalates with context.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", **{k: v for k, v in system().describe().items() if k != "thresholds"}}


@app.post("/tickets")
def post_ticket(ticket: TicketIn) -> dict:
    return _out(system().process(ticket.model_dump(), api_run_id()))


@app.post("/tickets/batch")
def post_batch(tickets: list[TicketIn]) -> list[dict]:
    return [_out(system().process(t.model_dump(), api_run_id(), i)) for i, t in enumerate(tickets)]


@app.get("/decisions/{ticket_id}")
def decisions(ticket_id: str) -> list[dict]:
    rows = system().decisions.for_ticket(ticket_id)
    if not rows:
        raise HTTPException(404, "no decisions logged for this ticket")
    return rows


@app.get("/kill-switch")
def get_kill() -> dict:
    return killswitch.status(Settings())


@app.post("/kill-switch")
def set_kill(body: KillSwitchIn, x_admin_token: str = Header(default="")) -> dict:
    settings = Settings()
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(403, "admin token required (set ADMIN_TOKEN in .env and send it as X-Admin-Token)")
    return killswitch.engage(settings, body.reason or "via API") if body.engaged else killswitch.release(settings)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    try:
        from prometheus_client import generate_latest

        return generate_latest().decode("utf-8")
    except Exception:
        return "# prometheus_client not installed\n"


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    system()  # load models and index before accepting traffic
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
