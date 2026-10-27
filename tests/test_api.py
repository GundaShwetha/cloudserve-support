"""The FastAPI service: one ticket per channel, decision lookup, health."""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_env):
    from src import api

    api.system.cache_clear()
    api.api_run_id.cache_clear()
    return TestClient(api.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_post_ticket_and_audit(client, by_channel):
    for ch, raw in by_channel.items():
        r = client.post("/tickets", json=raw)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in {"answered", "escalated", "blocked_escalated"}
        assert 0 <= (body["intent_confidence"] or 0) <= 1
    d = client.get(f"/decisions/{raw['ticket_id']}")
    assert d.status_code == 200 and any(row["stage"] == "final" for row in d.json())


def test_kill_switch_needs_token(client):
    assert client.post("/kill-switch", json={"engaged": True}).status_code == 403
