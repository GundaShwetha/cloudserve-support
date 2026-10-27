"""A11 - no retrieval hit, provider timeout/outage, rate limiting and malformed input: the system
degrades and continues; it never crashes and never drops a ticket."""
import requests

from src.config import Settings
from src.provider import OpenAICompatibleProvider, ProviderError


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._p, self.headers = status, payload, headers or {}

    def json(self):
        return self._p


class _Session:
    def __init__(self, script):
        self.script, self.calls = list(script), 0

    def post(self, *a, **k):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _provider(tmp_path, script, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)  # no real waiting in tests
    s = Settings()
    s.openrouter_api_key = "test-key-not-real"
    s.llm_cache_path = tmp_path / "cache.sqlite"
    s.llm_requests_per_minute = 100000
    return OpenAICompatibleProvider(s, session=_Session(script))


OK = _Resp(200, {"choices": [{"message": {"content": '{"cannot_answer": true, "sentences": []}'}}]})


def test_rate_limit_is_retried(tmp_path, monkeypatch):
    p = _provider(tmp_path, [_Resp(429, headers={"Retry-After": "1"}), _Resp(503), OK], monkeypatch)
    assert "cannot_answer" in p.complete([{"role": "user", "content": "x"}])
    assert p.session.calls == 3


def test_timeouts_exhaust_then_raise_and_open_circuit(tmp_path, monkeypatch):
    p = _provider(tmp_path, [requests.Timeout()] * 20, monkeypatch)
    for i in range(3):
        try:
            p.complete([{"role": "user", "content": f"x{i}"}])
        except ProviderError:
            pass
    calls = p.session.calls
    try:
        p.complete([{"role": "user", "content": "after"}])
    except ProviderError as e:
        assert "circuit open" in str(e)
    assert p.session.calls == calls  # circuit open: no further calls while the provider is down


def test_cache_makes_repeat_calls_free(tmp_path, monkeypatch):
    p = _provider(tmp_path, [OK], monkeypatch)
    m = [{"role": "user", "content": "same"}]
    assert p.complete(m) == p.complete(m) and p.session.calls == 1


def test_provider_disconnected_entirely_pipeline_still_answers(settings, fake_provider, dev_tickets):
    from src.pipeline import SupportSystem

    s = SupportSystem(settings, provider=fake_provider([requests.ConnectionError("network down")] * 50))
    run = s.start_run("test-outage")
    outs = [s.process(t, run, i) for i, t in enumerate(dev_tickets[:20])]
    assert len(outs) == 20 and s.decisions.reconcile(run, 20)["reconciles"]
    answered = [o for o in outs if o.action == "auto_respond"]
    assert answered and all(o.generation_mode == "extractive" and o.provider_error for o in answered)


def test_malformed_and_hostile_input_never_crashes(system):
    run = system.start_run("test-malformed")
    weird = [None, 42, "plain string", [], {}, {"body": ""}, {"channel": 7, "body": ["x"]},
             {"body": "\x00" * 50}, {"body": "a" * 100000}, {"body": "{{format}} %s %d \\u0000"}]
    outs = [system.process(w, run, i) for i, w in enumerate(weird)]
    assert len(outs) == len(weird)
    assert all(o.action in {"escalate", "block", "auto_respond"} for o in outs)
    assert system.decisions.reconcile(run, len(weird))["reconciles"]


def test_no_retrieval_hit_escalates(system):
    o = system.process({"channel": "email", "body": "Can you recommend a good banana bread recipe with walnuts?"},
                       system.start_run("test-nohit"))
    assert o.action == "escalate"


def test_kill_switch_takes_effect_on_next_ticket(system, dev_tickets):
    from src import killswitch

    run = system.start_run("test-kill")
    killswitch.engage(system.settings, "test")
    try:
        o = system.process(dev_tickets[0], run)
        assert o.action == "escalate" and o.route.rule == "kill_switch"
    finally:
        killswitch.release(system.settings)
    assert system.process(dev_tickets[0], run).route.rule != "kill_switch"
