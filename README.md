# CloudServe support triage and grounded-answer system

Forward Deployed AI Engineering capstone. CloudServe asked for a chatbot. Discovery showed that about
seven in ten tickets are already answered in CloudServe's own documentation, that agents cannot find
it, and that escalations reach tier two with no context. This system therefore:

1. answers, with citations, the tickets the documentation genuinely answers, and says so when it is a machine;
2. escalates everything else to a person **with a handover note** (what it seems to be, why it escalated,
   what it was unsure about, and the articles it found);
3. never answers security, compliance, feature-request or unclear tickets automatically, and blocks any
   reply containing private data, unsupported claims or commitments;
4. logs every decision so it can be reconstructed and explained later.

```
ticket (email | chat | docs comment | forum)
   -> ingest -> classify -> retrieve -> route --auto--> generate -> validate --pass--> reply sent
                                          |                           |
                                          +--escalate--------------- block --> handover note to an agent
   every step -> decision log (SQLite)        metrics -> Prometheus / Grafana        kill switch
```

---

## 1. Run it (tested from a clean checkout)

Requirements: **Python 3.10, 3.11 or 3.12** and git. About 1.5 GB free disk for dependencies.
No API key is needed to run anything below; with a key, replies are drafted by the model instead of
extracted from the documentation.

### 1.1 Get the code and create an environment

macOS / Linux:
```bash
git clone <repository-url> cloudserve-support
cd cloudserve-support
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows (PowerShell or Command Prompt):
```bat
git clone <repository-url> cloudserve-support
cd cloudserve-support
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
```

Optional: put your OpenRouter (or Groq) key into `.env` as `OPENROUTER_API_KEY=...`.
Leave it as `your_key_here` to run without a model.

### 1.2 Run the full evaluation, unattended (the gate)

```bash
python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results/my_run
```

* Works on any ticket file with the published schema (JSON list or JSON Lines): point `--input` at it.
* The first run trains the classifier on `data/development_tickets.json` (about 15 s), builds the Chroma
  index and downloads the all-MiniLM-L6-v2 ONNX model (~80 MB, once). If the model cannot be downloaded
  it falls back to local TF-IDF retrieval automatically and says so in the report.
* Output in the `--output` folder: `metrics_report.md` (read this), `metrics_report.json`, `results.jsonl`
  (one line per ticket), `decision_log.csv` (this run's decisions, for reconciliation), `escalations.jsonl`
  (handover notes) and `review_sample.csv` (50 sent replies for the two-person human review).

### 1.3 Start the API and try one ticket per channel

```bash
python -m src.api
```
Open http://127.0.0.1:8000/docs and use `POST /tickets`, or from a second terminal:
```bash
curl -X POST http://127.0.0.1:8000/tickets -H "Content-Type: application/json" -d "{\"channel\": \"chat\", \"body\": \"we keep getting 429 too many requests even with three api keys\"}"
```
`GET /decisions/{ticket_id}` returns every logged decision for a ticket. `GET /metrics` is the Prometheus endpoint.

### 1.4 Live demonstration (success, escalation, guardrails)

```bash
python -m src.demo
```
Runs `data/samples/demo_tickets.json`: one ticket per channel (answered with citations), a security
incident (escalated with a handover note), a prompt-injection attempt and a ticket containing an API key
and someone else's e-mail address (both **blocked** before any reply is drafted).

### 1.5 Tests

```bash
python -m pytest tests/ -v
```
48 tests; they run offline (TF-IDF retrieval, no model calls) in under a minute.

### 1.6 Kill switch (stop all automatic replies immediately, no redeploy)

```bash
python -m src.killswitch on --reason "wrong answers reported"
python -m src.killswitch status
python -m src.killswitch off
```
Takes effect on the next ticket. Also available as `POST /kill-switch` (needs `ADMIN_TOKEN` in `.env`)
and as `AUTO_RESPOND_ENABLED=false` in `.env`. Procedure: `docs/governance.md`.

### 1.7 Retrain and re-derive thresholds (optional)

```bash
python -m src.train
python -m evaluation.retrieval_experiment
```
`src.train` uses only the development tickets and rewrites `config/thresholds.json` and
`docs/threshold_analysis.md`. The thresholds in the repository were produced this way.

### 1.8 Monitoring (optional, needs Docker)

```bash
python -m src.api                                   # terminal 1
docker compose -f monitoring/docker-compose.yml up  # terminal 2
```
Prometheus: http://localhost:9090, Grafana: http://localhost:3000 (dashboard "CloudServe support system":
volume by channel and outcome, answered vs escalated share, latency p50/p95, guardrail blocks, confidence
distribution, provider failures, kill switch).

---

## 2. Repository layout

| Path | What it is |
|---|---|
| `src/ingest.py` | Normalises all four channels into one `Ticket` (A2) |
| `src/classify.py` | Intent, urgency, answerability with calibrated confidences (A3) |
| `src/retrieve.py` | Section chunking, Chroma + MiniLM (TF-IDF fallback), relevance threshold (A4) |
| `src/route.py` | Deterministic routing rules with plain-language reasons (A5) |
| `src/generate.py` | Model drafting (PR-03) with extractive fallback; escalation handover (PR-04) (A6) |
| `src/guardrails.py` | Input and output guardrails that block (A7) |
| `src/logging_store.py` | SQLite decision log, masked inputs, reconciliation (A8) |
| `src/pipeline.py` | LangGraph orchestration; `process()` never raises (A9, A11) |
| `src/provider.py` | Model client: rate limiting, retries, circuit breaker, cache (A11) |
| `src/api.py`, `src/demo.py`, `src/killswitch.py`, `src/train.py` | Service, demo, kill switch, training |
| `evaluation/harness.py`, `metrics.py`, `report.py` | Unattended run and automatic metrics report (A9, A10) |
| `evaluation/results/validation_run/` | The recorded validation run |
| `prompts/` | Versioned prompt library and register |
| `config/thresholds.json` | Thresholds chosen from development data |
| `docs/` | Architecture and decisions, governance, evaluation method, discovery evidence, traceability |
| `tests/` | Test suite (A12) |
| `monitoring/` | Prometheus, Grafana dashboard, docker compose |
| `data/` | Development, validation, documentation and reference datasets; demo samples |

Acceptance-criteria and requirement traceability: `docs/traceability.md`.

## 3. Troubleshooting

| Symptom | Fix |
|---|---|
| `pip install` fails on `chromadb` or `langgraph` (unusual platform) | `python -m pip install -r requirements-core.txt`. The system detects the missing packages and uses TF-IDF retrieval and its built-in executor; the report records which were used. |
| `ModuleNotFoundError` | The virtual environment is not active in this terminal: run the activate command again. |
| Python 3.13 | Use 3.10-3.12 (`py -3.11` on Windows); pinned wheels are not published for 3.13 yet. |
| First run is slow | Model training (~15 s) and the one-off embedding model download. Later runs reuse both from `storage/`. |
| Every reply says "drafted automatically from CloudServe's support documentation" and `generation: extractive` | No API key configured (expected), or the provider is failing: the report counts provider fallbacks. |
| HTTP 401 from the provider | Key wrong or has stray whitespace; check `.env`. The run still completes with extractive replies. |
| Start again from nothing | Delete the `storage/` folder. It is regenerated on the next run. |

## 4. Attribution

See `ATTRIBUTION.md` for third-party libraries, data, and the declaration of AI-assisted code.
