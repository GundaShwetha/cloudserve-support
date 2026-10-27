"""Ingest: normalise tickets from email, live chat, documentation comments and the forum (FR-01, A2).

Channel quirks found in the development data and handled here so they do not leak downstream:
  * chat tickets have an empty subject;
  * subjects are sometimes misleading templates (e.g. "Key committed to a public repo" over a body
    about a breach elsewhere), so the body is always kept and placed first in `text`;
  * forum posts may contain quoted earlier replies ("> ..."), which describe someone else's problem;
  * external feeds use different field names (message/content/text, created_at/timestamp, ...).
Nothing in this module raises on bad input: problems become `ingest_warnings` instead.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from .schemas import CHANNELS, Ticket

_CHANNEL_ALIASES = {
    "email": "email", "e-mail": "email", "mail": "email",
    "chat": "chat", "live_chat": "chat", "livechat": "chat", "live chat": "chat",
    "docs_comment": "docs_comment", "docs": "docs_comment", "documentation": "docs_comment",
    "doc_comment": "docs_comment", "api_docs": "docs_comment", "documentation_comment": "docs_comment",
    "docs comment": "docs_comment",
    "forum": "forum", "community": "forum", "community_forum": "forum",
}
_BODY_KEYS = ("body", "message", "content", "text", "description", "comment")
_SUBJECT_KEYS = ("subject", "title", "topic")
_TIME_KEYS = ("received_at", "created_at", "timestamp", "date")
_MAX_CHARS = 8000  # protects the classifier and the model context from pathological inputs
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_QUOTE_LINE = re.compile(r"^\s*>.*$", re.MULTILINE)
_WS = re.compile(r"[ \t]+")


def _first(d: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def clean_text(value: Any) -> str:
    """Make any value into safe, readable text without ever raising."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False)
        except Exception:
            value = str(value)
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _CONTROL.sub(" ", value)
    value = re.sub(r"<[^>]{1,200}>", " ", value)  # strip stray HTML tags from email/forum bodies
    value = _WS.sub(" ", value)
    return value.strip()[:_MAX_CHARS]


def normalise_channel(raw: Any) -> tuple[str, list[str]]:
    if raw is None:
        return "email", ["missing channel; treated as email"]
    key = str(raw).strip().lower()
    if key in _CHANNEL_ALIASES:
        return _CHANNEL_ALIASES[key], []
    return "email", [f"unknown channel '{raw}'; treated as email"]


def normalise(raw: Any, index: int = 0) -> Ticket:
    """Convert one raw record from any channel into a Ticket. Never raises."""
    warnings: list[str] = []
    if not isinstance(raw, dict):
        warnings.append(f"record was {type(raw).__name__}, not an object")
        raw = {"body": raw}

    channel, w = normalise_channel(raw.get("channel"))
    warnings += w

    ticket_id = clean_text(raw.get("ticket_id") or raw.get("id")) or f"UNKNOWN-{index:05d}"
    if ticket_id.startswith("UNKNOWN-"):
        warnings.append("missing ticket_id")

    subject = clean_text(_first(raw, _SUBJECT_KEYS))
    body = clean_text(_first(raw, _BODY_KEYS))

    if channel == "forum":
        unquoted = _QUOTE_LINE.sub(" ", body).strip()
        if unquoted and unquoted != body:
            warnings.append("removed quoted forum text")
            body = _WS.sub(" ", unquoted)
    if channel == "chat" and subject:
        # chat has no subject line in CloudServe's feed; keep it but do not rely on it
        warnings.append("chat ticket carried a subject")

    if not body and not subject:
        warnings.append("empty ticket body")
    text = body if not subject else f"{body}\n(Subject: {subject})"

    labels = raw.get("labels") if isinstance(raw.get("labels"), dict) else {}
    history = raw.get("history") if isinstance(raw.get("history"), dict) else {}

    def _choice(key: str, allowed: set[str], default: str) -> str:
        v = clean_text(raw.get(key)).lower()
        if v in allowed:
            return v
        if v:
            warnings.append(f"unexpected {key} '{v}'")
        return default

    return Ticket(
        ticket_id=ticket_id,
        channel=channel,
        subject=subject,
        body=body,
        text=text,
        received_at=clean_text(_first(raw, _TIME_KEYS)) or None,
        customer_id=clean_text(raw.get("customer_id")) or "unknown",
        customer_name=clean_text(raw.get("customer_name")),
        customer_tier=_choice("customer_tier", {"enterprise", "business", "standard"}, "unknown"),
        customer_region=_choice(
            "customer_region", {"north_america", "europe", "asia_pacific", "latin_america"}, "unknown"
        ),
        language_fluency=_choice("language_fluency", {"fluent", "non_fluent"}, "unknown"),
        original=raw,
        ingest_warnings=warnings,
        labels=labels,
        history=history,
    )


def load_records(path: str | Path) -> list[Any]:
    """Read a ticket file: a JSON list, an object holding a list, or JSON Lines. Tolerates a BOM
    and bad bytes. Raises only if the file is missing or unreadable as any of those formats."""
    raw = Path(path).read_bytes().decode("utf-8-sig", errors="replace")
    stripped = raw.strip()
    if not stripped:
        return []
    try:
        data = json.loads(stripped)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("tickets", "data", "items", "records"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
    except json.JSONDecodeError:
        pass
    records = []
    for n, line in enumerate(stripped.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"ticket_id": f"MALFORMED-LINE-{n + 1:05d}", "body": line[:2000]})
    return records


def load_tickets(path: str | Path) -> list[Ticket]:
    return [normalise(r, i) for i, r in enumerate(load_records(path))]


__all__ = ["CHANNELS", "normalise", "load_tickets", "load_records", "clean_text"]
