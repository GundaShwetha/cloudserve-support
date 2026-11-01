# Metrics report - run-20261101T180745Z-1d5629

Input: `data/validation_tickets.json` | started 2026-11-01T18:07:40+00:00 | finished 2026-11-01T18:22:57+00:00 | wall clock 912.5 s

System 1.0.0 | orchestration: langgraph | retrieval: chroma-minilm (min score 0.4991) | classifier: tfidf-lr-ca1a7c2528 | generation: llm+extractive-fallback (nvidia/nemotron-3-ultra-550b-a55b:free)

Thresholds: answerability >= 0.54, intent confidence >= 0.3 - 5-fold out-of-fold simulation on development_tickets.json: minimum expected cost with a wrong automatic reply costing 2x a missed automation, zero never-auto violations

## Results against targets

| Measure | Baseline | Target | Achieved | Notes |
|---|---|---|---|---|
| First contact resolution (sent automatically) | 46.2% (37/80) (95% CI 35.8%-57.1%) historical | >= 60% | 65.0% (52/80) (95% CI 54.1%-74.6%) | share of tickets closed with no human |
| First contact resolution (sent AND correct per labels) | - | >= 60% | 48.8% (39/80) (95% CI 38.1%-59.5%) | route label auto_respond and an expected document cited |
| Escalation rate | 53.8% (43/80) (95% CI 42.9%-64.2%) historical | <= 30% | 35.0% (28/80) (95% CI 25.4%-45.9%) | includes guardrail blocks |
| Time to first reply, automated replies | 8-12 h | < 5 min | mean 14.364 s, median 10.969 s, p95 48.388 s | measured |
| Time to first substantive reply, all tickets | 8-12 h | < 5 min | mean 282.6 min, median 0.4 min | modelled - see note |
| Satisfaction proxy | 2.6 / 5 | >= 4.0 | not measured automatically | human rubric on review_sample.csv |
| Repeat-contact risk (auto reply to a ticket the docs do not answer) | 21.2% (17/80) (95% CI 13.7%-31.4%) historical repeat rate | halve | 15.0% (12/80) (95% CI 8.8%-24.4%) | proxy |
| Intent classification precision (macro) | - | >= 85% | 100.0% | recall 100.0% |
| Routing accuracy vs expected_route | - | - | 75.0% (60/80) (95% CI 64.5%-83.2%) | wrong auto 12, missed 8 |
| Citation accuracy (cited doc is an expected doc) | - | >= 95% | 97.5% (39/40) (95% CI 87.1%-99.6%) | every citation resolves to a retrieved passage |
| Hallucination rate | - | <= 5% | 0 released replies failed the automated grounding check | human two-assessor review pending |
| Latency p95, all tickets | - | < 3 s | 45.204 s | end to end incl. retrieval |
| Private data in sent replies | - | 0 | 0 | automated scan of every sent reply |
| Auto replies to never-auto tickets | - | 0 | 0 | security, compliance, feature, unclear |
| Cross-group quality variation (worst dimension) | - | < 5 pts | 21.7 pts | see fairness section |
| Confidence calibration (intent, mean stated - observed) | - | within 5 pts | -0.2 pts (ECE 0.2 pts) | |
| Decision log coverage | - | complete | 80/80 reconciled = True | |

Note on modelled reply time: escalated tickets still wait for a person; modelled at the historical median of 807 minutes for escalated tickets (history block of the development set). This is an upper bound: escalations now arrive with a summary and sources attached.

## Volume

| | count |
|---|---|
| tickets processed | 80 |
| answered automatically | 52 |
| escalated | 28 |
| of which blocked by guardrails | 6 |
| of which internal errors | 0 |
| labelled tickets | 80 |

## Intent classification, per class

| intent | precision | recall | support |
|---|---|---|---|
| account_access | 1.000 | 1.000 | 4 |
| api_key_issue | 1.000 | 1.000 | 6 |
| api_usage_question | 1.000 | 1.000 | 4 |
| authentication_failure | 1.000 | 1.000 | 3 |
| billing_query | 1.000 | 1.000 | 10 |
| compliance_request | 1.000 | 1.000 | 1 |
| configuration_help | 1.000 | 1.000 | 3 |
| data_export | 1.000 | 1.000 | 1 |
| data_residency | 1.000 | 1.000 | 6 |
| database_issue | 1.000 | 1.000 | 1 |
| deployment_failure | 1.000 | 1.000 | 5 |
| feature_request | 1.000 | 1.000 | 3 |
| integration_help | 1.000 | 1.000 | 3 |
| onboarding | 1.000 | 1.000 | 4 |
| performance_degradation | 1.000 | 1.000 | 3 |
| quota_or_overage | 1.000 | 1.000 | 2 |
| rate_limit | 1.000 | 1.000 | 1 |
| rollback_request | 1.000 | 1.000 | 6 |
| security_incident | 1.000 | 1.000 | 4 |
| sso_configuration | 1.000 | 1.000 | 1 |
| unclear_request | 1.000 | 1.000 | 6 |
| webhook_issue | 1.000 | 1.000 | 3 |

Urgency accuracy: 41.2% (macro precision 35.5%).

## Routing

| expected \ actual | auto_respond | escalate |
|---|---|---|
| auto_respond | 40 | 8 |
| escalate | 12 | 20 |

Automation precision: 76.9% (40/52) (95% CI 63.9%-86.3%)

## Retrieval and citations

- Backend: chroma-minilm
- Hit rate (an expected document among retrieved passages, answerable tickets): 92.5% (49/53) (95% CI 82.1%-97.0%)
- Top-1 accuracy (answerable tickets): 92.5% (49/53) (95% CI 82.1%-97.0%)
- Returned nothing (below relevance threshold): 17.5% (14/80) (95% CI 10.7%-27.3%)
- Answers citing an expected document: 97.5% (39/40) (95% CI 87.1%-99.6%)
- Automatic answers sent to tickets with no documented answer (a routing error): 23.1% (12/52) (95% CI 13.7%-36.1%)

## Calibration intent

| band | n | stated | observed | gap (pts) |
|---|---|---|---|---|
| 0.8-1.0 | 80 | 0.998 | 1.000 | -0.2 |

Expected calibration error: 0.2 points.

## Calibration answerability

| band | n | stated | observed | gap (pts) |
|---|---|---|---|---|
| 0.2-0.4 | 6 | 0.346 | 0.000 | +34.7 |
| 0.4-0.6 | 9 | 0.504 | 0.556 | -5.2 |
| 0.6-0.8 | 49 | 0.710 | 0.714 | -0.5 |
| 0.8-1.0 | 16 | 0.847 | 0.812 | +3.4 |

Expected calibration error: 4.2 points.

## Latency (seconds, all tickets)

p50 0.1355, p95 45.2043, max 76.446

Replies by generator: {'llm': 34, 'extractive': 18}; provider fallbacks to extractive: 18

## Governance

- Decision log: {'tickets_processed': 80, 'final_decisions_logged': 80, 'reconciles': True, 'decisions_by_stage': {'classification': 80, 'escalation': 28, 'final': 80, 'generation': 58, 'ingest': 80, 'retrieval': 80, 'routing': 80, 'validation': 58}, 'final_actions': {'auto_respond': 52, 'block': 6, 'escalate': 22}, 'total_decision_rows': 544}
- Guardrail activations by type: {'grounding': 6}
- Replies blocked by guardrails: 6
- Private data detections in sent replies: 0
- Incoming tickets containing private data (blocked): 0
- Automatic replies to never-auto tickets: 0

## Fairness: quality by customer group

Quality = ticket handled correctly (routing matches the label and, if answered, an expected document was cited).

### customer_tier - max gap 16.1 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| business | 30 | 70.0% (21/30) (95% CI 52.1%-83.3%) | 73.3% (22/30) (95% CI 55.5%-85.8%) | 90.9% (20/22) (95% CI 72.2%-97.5%) |
| enterprise | 8 | 62.5% (5/8) (95% CI 30.6%-86.3%) | 62.5% (5/8) (95% CI 30.6%-86.3%) | 100.0% (6/6) (95% CI 61.0%-100.0%) |
| standard | 42 | 78.6% (33/42) (95% CI 64.1%-88.3%) | 59.5% (25/42) (95% CI 44.5%-73.0%) | 92.0% (23/25) (95% CI 75.0%-97.8%) |

### language_fluency - max gap 20.8 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| fluent | 61 | 78.7% (48/61) (95% CI 66.9%-87.1%) | 65.6% (40/61) (95% CI 53.0%-76.2%) | 90.9% (40/44) (95% CI 78.8%-96.4%) |
| non_fluent | 19 | 57.9% (11/19) (95% CI 36.3%-76.9%) | 63.2% (12/19) (95% CI 41.0%-80.8%) | 100.0% (9/9) (95% CI 70.1%-100.0%) |

### customer_region - max gap 21.7 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| asia_pacific | 21 | 85.7% (18/21) (95% CI 65.4%-95.0%) | 66.7% (14/21) (95% CI 45.4%-82.8%) | 100.0% (17/17) (95% CI 81.6%-100.0%) |
| europe | 25 | 64.0% (16/25) (95% CI 44.5%-79.8%) | 64.0% (16/25) (95% CI 44.5%-79.8%) | 89.5% (17/19) (95% CI 68.6%-97.1%) |
| latin_america | 7 | 85.7% (6/7) (95% CI 48.7%-97.4%) | 57.1% (4/7) (95% CI 25.1%-84.2%) | 100.0% (3/3) (95% CI 43.9%-100.0%) |
| north_america | 27 | 70.4% (19/27) (95% CI 51.5%-84.2%) | 66.7% (18/27) (95% CI 47.8%-81.4%) | 85.7% (12/14) (95% CI 60.1%-96.0%) |

### channel - max gap 13.5 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| chat | 22 | 77.3% (17/22) (95% CI 56.6%-89.9%) | 50.0% (11/22) (95% CI 30.7%-69.3%) | 69.2% (9/13) (95% CI 42.4%-87.3%) |
| docs_comment | 16 | 81.2% (13/16) (95% CI 57.0%-93.4%) | 68.8% (11/16) (95% CI 44.4%-85.8%) | 100.0% (10/10) (95% CI 72.2%-100.0%) |
| email | 31 | 67.7% (21/31) (95% CI 50.1%-81.4%) | 74.2% (23/31) (95% CI 56.8%-86.3%) | 100.0% (22/22) (95% CI 85.1%-100.0%) |
| forum | 11 | 72.7% (8/11) (95% CI 43.4%-90.2%) | 63.6% (7/11) (95% CI 35.4%-84.8%) | 100.0% (8/8) (95% CI 67.6%-100.0%) |

### length - max gap 6.5 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| long | 37 | 70.3% (26/37) (95% CI 54.2%-82.5%) | 75.7% (28/37) (95% CI 59.9%-86.6%) | 96.0% (24/25) (95% CI 80.5%-99.3%) |
| short | 43 | 76.7% (33/43) (95% CI 62.3%-86.9%) | 55.8% (24/43) (95% CI 41.1%-69.6%) | 89.3% (25/28) (95% CI 72.8%-96.3%) |

## Method notes

- Every figure above is computed by `evaluation/metrics.py` from this run; nothing is entered by hand.
- 'Sent' means released after all guardrails passed. Escalations include guardrail blocks.
- Figures should be treated with caution because the labels themselves are noisy (identical ticket texts carry different routing and answerability labels in the development data), the satisfaction proxy and hallucination rate need human review, and reply-time figures for escalated tickets are modelled rather than observed.
