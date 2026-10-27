"""Prometheus metrics (monitoring cross-cutting concern). No-ops if prometheus_client is absent,
so monitoring can never stop the support pipeline."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    TICKETS = Counter("tickets_processed_total", "Tickets processed", ["channel", "outcome"])
    LATENCY = Histogram("response_seconds", "End to end processing time per ticket",
                        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 30))
    GUARDRAIL = Counter("guardrail_blocks_total", "Responses blocked", ["guardrail"])
    CONFIDENCE = Histogram("route_confidence", "Routing confidence distribution",
                           buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0))
    PROVIDER_FAIL = Counter("provider_failures_total", "Model provider failures (fell back to extractive)")
    KILL = Gauge("kill_switch_engaged", "1 when automatic replies are switched off")
    ENABLED = True
except Exception:  # pragma: no cover - exercised only when the package is missing
    ENABLED = False

    class _Noop:
        def labels(self, *a, **k):
            return self

        def inc(self, *a, **k):
            pass

        def observe(self, *a, **k):
            pass

        def set(self, *a, **k):
            pass

    TICKETS = LATENCY = GUARDRAIL = CONFIDENCE = PROVIDER_FAIL = KILL = _Noop()

    def start_http_server(*a, **k):  # type: ignore
        log.warning("prometheus_client not installed; metrics server not started")

_started = False


def serve(port: int) -> None:
    global _started
    if port and not _started:
        try:
            start_http_server(port)
            _started = True
            log.info("metrics on :%d/metrics", port)
        except OSError as exc:
            log.warning("metrics server not started: %s", exc)
