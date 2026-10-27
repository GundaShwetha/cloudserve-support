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

| File / area | What the AI produced | What the author changed or decided, and why |
|---|---|---|
| | | |

The discovery figures in docs/discovery_evidence.md are computed by code from the supplied data; the
problem statement, the interpretation of the evaluation results and the reflection are the author's own.
