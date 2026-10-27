"""Shared fixtures. Tests never touch the real storage/ directory or the committed thresholds file:
each session works in a temporary directory, and no test calls a real model provider."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def tmp_env(tmp_path_factory):
    base = tmp_path_factory.mktemp("cloudserve")
    thresholds = base / "thresholds.json"
    src = ROOT / "config" / "thresholds.json"
    if src.exists():
        shutil.copy(src, thresholds)
    env = {
        "STORAGE_DIR": str(base / "storage"),
        "CHROMA_PATH": str(base / "storage" / "chroma"),
        "DECISION_DB": str(base / "storage" / "decisions.db"),
        "MODEL_DIR": str(base / "storage" / "models"),
        "KILL_SWITCH_PATH": str(base / "storage" / "KILL_SWITCH"),
        "LLM_CACHE_PATH": str(base / "storage" / "llm_cache.sqlite"),
        "THRESHOLDS_PATH": str(thresholds),
        "RETRIEVAL_BACKEND": "tfidf",      # deterministic and offline in CI
        "GENERATION_MODE": "extractive",   # no network calls from the test suite
        "OPENROUTER_API_KEY": "",
        "CONFIDENCE_THRESHOLD": "",
    }
    mp = pytest.MonkeyPatch()
    for k, v in env.items():
        mp.setenv(k, v)
    yield base
    mp.undo()


@pytest.fixture(scope="session")
def settings(tmp_env):
    from src.config import Settings

    return Settings()


@pytest.fixture(scope="session")
def system(settings):
    from src.pipeline import SupportSystem

    return SupportSystem(settings, provider=None)


@pytest.fixture(scope="session")
def dev_tickets():
    return json.loads((ROOT / "data" / "development_tickets.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def by_channel(dev_tickets):
    out = {}
    for t in dev_tickets:
        out.setdefault(t["channel"], t)
    return out


class FakeProvider:
    """Stands in for the model provider. `script` is a list of responses or exceptions."""

    name = "fake"
    model = "fake-model"

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def complete(self, messages, cache_key_extra=""):
        self.calls.append(messages)
        item = self.script.pop(0) if self.script else self.script_default()
        if isinstance(item, Exception):
            raise item
        return item(messages) if callable(item) else item

    def script_default(self):
        from src.provider import ProviderError

        return ProviderError("script exhausted")


@pytest.fixture
def fake_provider():
    return FakeProvider
