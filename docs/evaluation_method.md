# Evaluation method

## Data and protocol
* **Development set (500)**: training, threshold selection (5-fold out-of-fold), chunking experiment, discovery.
* **Validation set (80)**: run once through the harness after the system was frozen. The run date, system
  version and settings are in `evaluation/results/validation_run/metrics_report.md`. Nothing was tuned on it.
* **Hidden set (120)**: run by the assessors with the same command.

Record in the report: date of each validation/hidden run and the number of runs. Repository record:

| Run | Date (UTC) | Set | Retrieval | Generation | Purpose |
|---|---|---|---|---|---|
| run-20261027T131617Z-2ac3fe | 2026-10-27 | validation (80) | tfidf (build sandbox had no access to the embedding model) | extractive (no provider key) | first and only validation run of v1.0 |
| (add yours) | | | chroma-minilm | llm | run on your machine with the full stack |

## Measures and how each is computed (all by `evaluation/metrics.py`)

| Tier | Measure | Definition |
|---|---|---|
| Business | First contact resolution (claimed) | tickets answered automatically / all tickets |
| Business | First contact resolution (correct) | answered automatically AND label says auto_respond AND an expected article cited / labelled tickets |
| Business | Escalation rate | escalated (incl. guardrail blocks) / all tickets |
| Business | Time to first reply (automated) | processing time per answered ticket (measured) |
| Business | Time to first substantive reply (all) | answered: measured; escalated: historical median for escalated tickets (modelled, upper bound) |
| Business | Repeat-contact risk | automatic replies to tickets labelled not answerable from docs / labelled tickets (proxy: those customers will write again) |
| Business | Satisfaction proxy | human rubric PR-06 on `review_sample.csv` (below) |
| Technical | Intent precision/recall | per class, macro average, confusion matrix in metrics_report.json |
| Technical | Routing accuracy, automation precision | against `expected_route` |
| Technical | Retrieval hit rate / top-1 | an expected article among / first in the retrieved passages, answerable tickets |
| Technical | Citation accuracy | cited articles that are expected articles, over replies to tickets that have expected articles |
| Technical | Hallucination rate | automated: released replies failing grounding (0 by construction); human: two assessors on 50 replies |
| Technical | Latency | p50/p95/max end-to-end per ticket |
| Technical | Calibration | stated vs observed per confidence band; expected calibration error in points |
| Governance | Decision coverage | final decision rows == tickets processed |
| Governance | Private data | automated scan of every sent reply |
| Governance | Never-auto violations | automatic replies to tickets labelled must_not_auto_respond |
| Fairness | Quality gap | max difference in correct-handling rate between groups (n >= 5) per dimension |

## Human review (to be done by the author and a second assessor)
1. Open `evaluation/results/<run>/review_sample.csv` (50 sent replies, fixed seed).
2. Each assessor, independently, fills: unsupported claims (0/1), citations support their sentences (0/1),
   rubric score 1-5 (prompts/evaluation/PR-06_reply_quality_rubric.md).
3. Report: hallucination rate = replies with >= 1 unsupported claim / 50 (per assessor and agreed),
   agreement rate between assessors, mean rubric score and share of 4-5 scores as the satisfaction proxy.
4. Optional third opinion: `python -m evaluation.judge --sample <file>` (PR-05, needs a provider key).

## Known limits of these figures
* Labels are noisy: identical texts carry different answerability/route labels (E9), which caps routing
  accuracy at ~89 % for any text-only system and depresses automation precision.
* The validation set is small (80): most proportions have 95 % intervals 15-25 points wide; fairness
  groups (e.g. 8 enterprise tickets) are smaller still.
* Reply time for escalations is modelled, not observed; satisfaction is a rubric proxy, not customer data.
* The recorded validation run used TF-IDF retrieval and extractive replies; the MiniLM + model
  configuration must be measured on the author's machine and reported separately.
