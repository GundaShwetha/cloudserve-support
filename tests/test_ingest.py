"""A2 - four channels into one representation; bad input never raises (A11 malformed input)."""
import json

from src.ingest import load_records, normalise
from src.schemas import Ticket


def test_all_four_channels_normalise(by_channel):
    assert set(by_channel) == {"email", "chat", "docs_comment", "forum"}
    for ch, raw in by_channel.items():
        t = normalise(raw)
        assert isinstance(t, Ticket)
        assert t.channel == ch
        assert t.body and t.text.startswith(t.body)
        assert t.original is raw  # original text and channel preserved for downstream use


def test_chat_has_no_subject(by_channel):
    assert normalise(by_channel["chat"]).subject == ""


def test_missing_fields_and_odd_types_do_not_raise():
    for raw in [{}, {"channel": "carrier pigeon"}, {"body": None}, {"body": 12345}, None, "just text", ["a", "b"],
                {"body": {"nested": True}}, {"ticket_id": "X", "body": "\x00\x07 bell ​ zero width"}]:
        t = normalise(raw, 3)
        assert t.channel in {"email", "chat", "docs_comment", "forum"}
        assert isinstance(t.text, str)


def test_empty_body_recorded_as_warning():
    t = normalise({"ticket_id": "E1", "channel": "chat", "body": "   "})
    assert "empty ticket body" in t.ingest_warnings


def test_channel_aliases_and_forum_quotes():
    assert normalise({"channel": "Live Chat", "body": "x"}).channel == "chat"
    assert normalise({"channel": "API_DOCS", "body": "x"}).channel == "docs_comment"
    t = normalise({"channel": "community", "body": "> someone else's problem\nmy real question"})
    assert t.channel == "forum" and "someone else's" not in t.body and "my real question" in t.body


def test_alternative_field_names():
    t = normalise({"id": "A-1", "channel": "email", "title": "Subj", "message": "Hello", "created_at": "2026-01-01"})
    assert (t.ticket_id, t.subject, t.body, t.received_at) == ("A-1", "Subj", "Hello", "2026-01-01")


def test_unicode_and_very_long_text():
    t = normalise({"channel": "email", "body": "naïve café 日本語 " * 2000})
    assert len(t.body) <= 8000 and "café" in t.body


def test_load_records_formats(tmp_path):
    p = tmp_path / "a.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"tickets": [{"body": "x"}]}).encode())
    assert len(load_records(p)) == 1
    p.write_text('{"body": "one"}\nnot json at all\n{"body": "three"}\n', encoding="utf-8")
    recs = load_records(p)
    assert len(recs) == 3 and recs[1]["ticket_id"].startswith("MALFORMED-LINE")
