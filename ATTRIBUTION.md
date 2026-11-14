# Attribution

## Third-party software (installed from PyPI, not vendored)
LangGraph and langchain-core (MIT), Chroma (Apache-2.0) with its ONNX build of
sentence-transformers/all-MiniLM-L6-v2 (Apache-2.0), scikit-learn (BSD-3), NumPy (BSD-3), FastAPI (MIT),
Uvicorn (BSD-3), Pydantic (MIT), httpx (BSD-3), requests (Apache-2.0), python-dotenv (BSD-3),
prometheus-client (Apache-2.0), pytest (MIT). Monitoring images: Prometheus (Apache-2.0), Grafana (AGPL-3.0).

## Data
`data/*.json` are the CloudServe capstone datasets supplied with the course pack (fictional client).
`data/samples/demo_tickets.json` was written for this project; its names, keys and e-mail addresses are fictitious.

## Code adapted from the course pack
The Prometheus metric names, the decision-log fields and the calibration-table approach follow the
Setup Guide, Governance Framework and Evaluation Framework of the course pack.

## AI assistance (declaration)
Substantial parts of this repository - the initial implementation of `src/`, `evaluation/`, `tests/`, the
monitoring configuration and drafts of the documentation in `docs/` - were generated with Claude
(Anthropic) in a working session directed by the author. The author must review, run and be able to
explain every file before submission, and should record here where the generated output was changed
or overridden, for example:

Where the author changed, overrode or decided:

| File / area | What the AI produced | What the author changed or decided, and why |
|---|---|---|
| `.env` / `src/config.py` | Default model meta-llama free tier | Switched to nvidia/nemotron-3-ultra-550b-a55b:free after Llama was no longer free and Nano returned 404; raised timeout and max tokens after JSON was cut off |
| `src/guardrails.py` (grounding) | Digits-only number check | "30 seconds" was blocked against "Thirty seconds" in run 2; number words now count as supported |
| `prompts/build/PR-03` | Version 1.0 | Added rule 8 (v1.1) instead of loosening the guardrail when framing sentences were blocked |
| `.github/workflows`, `.gitignore` | CI file, results folder ignored | CI YAML error fixed (with Claude's help); results folder un-ignored so run evidence is committed |
| Routing thresholds | Fairness option A proposed | Development-data check run; decided not to change the threshold (docs/fairness_development.md) |
| `README.md`, `requirements.txt` | Python 3.10-3.12 stated | Clean-checkout test on 14 Nov failed on Windows with Python 3.12; documented Python 3.10/3.11 |

The discovery figures in docs/discovery_evidence.md are computed by code from the supplied data; the
problem statement, the interpretation of the evaluation results and the reflection are the author's own.
