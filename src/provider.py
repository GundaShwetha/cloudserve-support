"""Model provider client with the failure handling A11 requires.

* OpenAI-compatible chat completions (OpenRouter by default, Groq supported).
* Client-side rate limiting so the free tier is not exceeded in the first place.
* Retries with exponential backoff for timeouts, 429 and 5xx, honouring Retry-After.
* A circuit breaker: after repeated failures the provider is skipped for a cool-off period, so an
  outage costs one timeout rather than one timeout per ticket.
* A response cache (SQLite) keyed on prompt version, model and input, which makes runs reproducible
  and keeps re-runs inside the free allowance.
The key is read from the environment only; it is never logged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from .config import Settings

log = logging.getLogger(__name__)

ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
}


class ProviderError(Exception):
    """Any failure to get usable text from the model provider."""


class ChatProvider(Protocol):
    name: str
    model: str

    def complete(self, messages: list[dict], cache_key_extra: str = "") -> str: ...


@dataclass
class _Breaker:
    failures: int = 0
    open_until: float = 0.0
    threshold: int = 3
    cooloff_s: float = 60.0

    def allow(self) -> bool:
        return time.monotonic() >= self.open_until

    def record(self, ok: bool) -> None:
        if ok:
            self.failures = 0
            return
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = time.monotonic() + self.cooloff_s
            log.warning("model provider circuit opened for %.0fs after %d failures", self.cooloff_s, self.failures)


class _Cache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as con, con:
            con.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, created REAL)")

    def get(self, k: str) -> Optional[str]:
        try:
            with closing(sqlite3.connect(self.path)) as con:
                row = con.execute("SELECT v FROM cache WHERE k=?", (k,)).fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def put(self, k: str, v: str) -> None:
        try:
            with closing(sqlite3.connect(self.path)) as con, con:
                con.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (k, v, time.time()))
        except sqlite3.Error:
            pass


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, session=None):
        import requests  # local import keeps module import cheap

        self.settings = settings
        self.name = settings.llm_provider
        self.model = settings.model_name
        self.url = ENDPOINTS.get(self.name, ENDPOINTS["openrouter"])
        self.session = session or requests.Session()
        self.breaker = _Breaker()
        self.cache = _Cache(settings.llm_cache_path)
        self._lock = threading.Lock()
        self._min_interval = 60.0 / max(1, settings.llm_requests_per_minute)
        self._last_call = 0.0

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_call + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def complete(self, messages: list[dict], cache_key_extra: str = "") -> str:
        key = hashlib.sha256(json.dumps([self.name, self.model, messages, cache_key_extra]).encode()).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if not self.settings.api_key:
            raise ProviderError("no API key configured")
        if not self.breaker.allow():
            raise ProviderError("provider circuit open after repeated failures")

        import requests

        last = "unknown error"
        for attempt in range(self.settings.llm_max_retries + 1):
            self._throttle()
            try:
                resp = self.session.post(
                    self.url,
                    headers={
                        "Authorization": f"Bearer {self.settings.api_key}",
                        "Content-Type": "application/json",
                        "X-Title": "CloudServe support capstone",
                    },
                    json={"model": self.model, "messages": messages, "temperature": 0, "max_tokens": 2500},
                    timeout=self.settings.llm_timeout_s,
                )
            except requests.RequestException as exc:
                last = f"{type(exc).__name__}"
                self._backoff(attempt, None)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            if resp.status_code >= 400:
                self.breaker.record(False)
                raise ProviderError(f"HTTP {resp.status_code}")  # auth/model errors are not retried
            try:
                text = resp.json()["choices"][0]["message"]["content"]
            except Exception:
                last = "malformed provider response"
                self._backoff(attempt, None)
                continue
            if not isinstance(text, str) or not text.strip():
                last = "empty provider response"
                self._backoff(attempt, None)
                continue
            self.breaker.record(True)
            self.cache.put(key, text)
            return text
        self.breaker.record(False)
        raise ProviderError(f"provider failed after retries: {last}")

    @staticmethod
    def _backoff(attempt: int, retry_after: Optional[str]) -> None:
        try:
            delay = float(retry_after) if retry_after else 0.0
        except ValueError:
            delay = 0.0
        time.sleep(min(20.0, max(delay, 1.5 * (2 ** attempt))))


def make_provider(settings: Settings) -> Optional[ChatProvider]:
    mode = settings.generation_mode.lower()
    if mode == "extractive":
        return None
    if mode == "auto" and not settings.api_key:
        return None
    return OpenAICompatibleProvider(settings)
