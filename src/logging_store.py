"""Decision log: every automated decision, reconstructable months later (FR-16, NFR-05, A8).

Schema follows the Governance Framework minimum record. One row per decision stage
(ingest, classification, retrieval, routing, generation, validation) plus exactly one `final` row per
ticket, so `count(final rows) == tickets processed` is the reconciliation check (A8).

Privacy: the log stores a masked, truncated input summary and a hash of the full text, not the raw
ticket - enough to audit and to re-find the ticket in the source system, without copying customer
secrets into a second database.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .guardrails import _CARD, _EMAIL, _KEY, _PASSWORD, _PHONE

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    decision_id      TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    ticket_id        TEXT NOT NULL,
    seq              INTEGER NOT NULL,
    stage            TEXT NOT NULL,
    input_summary    TEXT,
    input_sha256     TEXT,
    model_name       TEXT,
    model_version    TEXT,
    prediction       TEXT,
    confidence       REAL,
    alternatives     TEXT,
    sources_used     TEXT,
    threshold        REAL,
    action_taken     TEXT NOT NULL,
    reason           TEXT NOT NULL,
    guardrail_results TEXT,
    prompt_version   TEXT,
    requirement_ids  TEXT
);
CREATE INDEX IF NOT EXISTS ix_decisions_run ON decisions(run_id, stage);
CREATE INDEX IF NOT EXISTS ix_decisions_ticket ON decisions(ticket_id);
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    input_path   TEXT,
    system_version TEXT,
    config       TEXT
);
"""


def mask(text: str, limit: int = 240) -> str:
    text = _EMAIL.sub("[email]", text or "")
    text = _KEY.sub("[secret]", text)
    text = _PASSWORD.sub("[password]", text)
    text = _CARD.sub("[number]", text)
    text = _PHONE.sub("[phone]", text)
    return text[:limit]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DecisionLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        """One short-lived connection per operation: commit on success, roll back on error, always close."""
        con = sqlite3.connect(self.path, timeout=30)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def start_run(self, input_path: str, system_version: str, config: dict, run_id: Optional[str] = None) -> str:
        run_id = run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        with self._lock, self._connect() as con:
            con.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
                        (run_id, now(), input_path, system_version, json.dumps(config, default=str)))
        return run_id

    def write(self, rows: Iterable[dict[str, Any]]) -> int:
        """Write all decisions for one ticket in a single transaction (all or nothing)."""
        prepared = []
        for r in rows:
            prepared.append((
                r.get("decision_id") or uuid.uuid4().hex,
                r["run_id"], r.get("created_at") or now(), r["ticket_id"], int(r.get("seq", 0)), r["stage"],
                mask(r.get("input_summary", "")), r.get("input_sha256"),
                r.get("model_name"), r.get("model_version"),
                None if r.get("prediction") is None else str(r.get("prediction")),
                r.get("confidence"),
                json.dumps(r.get("alternatives") or [], default=str),
                json.dumps(r.get("sources_used") or [], default=str),
                r.get("threshold"), r["action_taken"], r["reason"],
                json.dumps(r.get("guardrail_results") or {}, default=str),
                r.get("prompt_version"), json.dumps(r.get("requirement_ids") or []),
            ))
        with self._lock, self._connect() as con:
            con.executemany(f"INSERT INTO decisions VALUES ({','.join('?' * 20)})", prepared)
        return len(prepared)

    # ----------------------------------------------------------------------------- queries
    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(sql, params).fetchall()]

    def for_ticket(self, ticket_id: str, run_id: Optional[str] = None) -> list[dict]:
        if run_id:
            return self.query("SELECT * FROM decisions WHERE ticket_id=? AND run_id=? ORDER BY seq", (ticket_id, run_id))
        return self.query("SELECT * FROM decisions WHERE ticket_id=? ORDER BY created_at, seq", (ticket_id,))

    def reconcile(self, run_id: str, processed: int) -> dict:
        finals = self.query("SELECT COUNT(*) AS n FROM decisions WHERE run_id=? AND stage='final'", (run_id,))[0]["n"]
        by_stage = {r["stage"]: r["n"] for r in self.query(
            "SELECT stage, COUNT(*) AS n FROM decisions WHERE run_id=? GROUP BY stage", (run_id,))}
        by_action = {r["action_taken"]: r["n"] for r in self.query(
            "SELECT action_taken, COUNT(*) AS n FROM decisions WHERE run_id=? AND stage='final' GROUP BY action_taken", (run_id,))}
        return {"tickets_processed": processed, "final_decisions_logged": finals, "reconciles": finals == processed,
                "decisions_by_stage": by_stage, "final_actions": by_action,
                "total_decision_rows": sum(by_stage.values())}


def sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
