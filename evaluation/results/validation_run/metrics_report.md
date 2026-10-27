# Metrics report - run-20261027T131617Z-2ac3fe

Input: `data/validation_tickets.json` | started 2026-10-27T13:16:14+00:00 | finished 2026-10-27T13:16:20+00:00 | wall clock 2.2 s

System 1.0.0 | orchestration: langgraph | retrieval: tfidf (min score 0.336) | classifier: tfidf-lr-ca1a7c2528 | generation: extractive

Thresholds: answerability >= 0.54, intent confidence >= 0.3 - 5-fold out-of-fold simulation on development_tickets.json: minimum expected cost with a wrong automatic reply costing 2x a missed automation, zero never-auto violations

## Results against targets

| Measure | Baseline | Target | Achieved | Notes |
|---|---|---|---|---|
| First contact resolution (sent automatically) | 46.2% (37/80) (95% CI 35.8%-57.1%) historical | >= 60% | 73.8% (59/80) (95% CI 63.2%-82.1%) | share of tickets closed with no human |
| First contact resolution (sent AND correct per labels) | - | >= 60% | 56.2% (45/80) (95% CI 45.3%-66.6%) | route label auto_respond and an expected document cited |
| Escalation rate | 53.8% (43/80) (95% CI 42.9%-64.2%) historical | <= 30% | 26.2% (21/80) (95% CI 17.9%-36.8%) | includes guardrail blocks |
| Time to first reply, automated replies | 8-12 h | < 5 min | mean 0.025 s, median 0.025 s, p95 0.031 s | measured |
| Time to first substantive reply, all tickets | 8-12 h | < 5 min | mean 211.8 min, median 0.0 min | modelled - see note |
| Satisfaction proxy | 2.6 / 5 | >= 4.0 | not measured automatically | human rubric on review_sample.csv |
| Repeat-contact risk (auto reply to a ticket the docs do not answer) | 21.2% (17/80) (95% CI 13.7%-31.4%) historical repeat rate | halve | 16.2% (13/80) (95% CI 9.8%-25.8%) | proxy |
| Intent classification precision (macro) | - | >= 85% | 100.0% | recall 100.0% |
| Routing accuracy vs expected_route | - | - | 78.8% (63/80) (95% CI 68.6%-86.3%) | wrong auto 14, missed 3 |
| Citation accuracy (cited doc is an expected doc) | - | >= 95% | 100.0% (46/46) (95% CI 92.3%-100.0%) | every citation resolves to a retrieved passage |
| Hallucination rate | - | <= 5% | 0 released replies failed the automated grounding check | human two-assessor review pending |
| Latency p95, all tickets | - | < 3 s | 0.030 s | end to end incl. retrieval |
| Private data in sent replies | - | 0 | 0 | automated scan of every sent reply |
| Auto replies to never-auto tickets | - | 0 | 0 | security, compliance, feature, unclear |
| Cross-group quality variation (worst dimension) | - | < 5 pts | 20.8 pts | see fairness section |
| Confidence calibration (intent, mean stated - observed) | - | within 5 pts | -0.2 pts (ECE 0.2 pts) | |
| Decision log coverage | - | complete | 80/80 reconciled = True | |

Note on modelled reply time: escalated tickets still wait for a person; modelled at the historical median of 807 minutes for escalated tickets (history block of the development set). This is an upper bound: escalations now arrive with a summary and sources attached.

## Volume

| | count |
|---|---|
| tickets processed | 80 |
| answered automatically | 59 |
| escalated | 21 |
| of which blocked by guardrails | 0 |
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
| auto_respond | 45 | 3 |
| escalate | 14 | 18 |

Automation precision: 76.3% (45/59) (95% CI 64.0%-85.3%)

## Retrieval and citations

- Backend: tfidf
- Hit rate (an expected document among retrieved passages, answerable tickets): 96.2% (51/53) (95% CI 87.2%-99.0%)
- Top-1 accuracy (answerable tickets): 96.2% (51/53) (95% CI 87.2%-99.0%)
- Returned nothing (below relevance threshold): 18.8% (15/80) (95% CI 11.7%-28.7%)
- Answers citing an expected document: 100.0% (46/46) (95% CI 92.3%-100.0%)
- Automatic answers sent to tickets with no documented answer (a routing error): 22.0% (13/59) (95% CI 13.4%-34.1%)

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

p50 0.0245, p95 0.0304, max 0.036

Replies by generator: {'extractive': 59}; provider fallbacks to extractive: 0

## Governance

- Decision log: {'tickets_processed': 80, 'final_decisions_logged': 80, 'reconciles': True, 'decisions_by_stage': {'classification': 80, 'escalation': 21, 'final': 80, 'generation': 59, 'ingest': 80, 'retrieval': 80, 'routing': 80, 'validation': 59}, 'final_actions': {'auto_respond': 59, 'escalate': 21}, 'total_decision_rows': 539}
- Guardrail activations by type: none
- Replies blocked by guardrails: 0
- Private data detections in sent replies: 0
- Incoming tickets containing private data (blocked): 0
- Automatic replies to never-auto tickets: 0

## Fairness: quality by customer group

Quality = ticket handled correctly (routing matches the label and, if answered, an expected document was cited).

### customer_tier - max gap 10.8 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| business | 30 | 76.7% (23/30) (95% CI 59.1%-88.2%) | 86.7% (26/30) (95% CI 70.3%-94.7%) | 95.5% (21/22) (95% CI 78.2%-99.2%) |
| enterprise | 8 | 87.5% (7/8) (95% CI 52.9%-97.8%) | 87.5% (7/8) (95% CI 52.9%-97.8%) | 100.0% (6/6) (95% CI 61.0%-100.0%) |
| standard | 42 | 78.6% (33/42) (95% CI 64.1%-88.3%) | 61.9% (26/42) (95% CI 46.8%-75.0%) | 96.0% (24/25) (95% CI 80.5%-99.3%) |

### language_fluency - max gap 20.4 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| fluent | 61 | 83.6% (51/61) (95% CI 72.4%-90.8%) | 72.1% (44/61) (95% CI 59.8%-81.8%) | 95.5% (42/44) (95% CI 84.9%-98.7%) |
| non_fluent | 19 | 63.2% (12/19) (95% CI 41.0%-80.8%) | 79.0% (15/19) (95% CI 56.7%-91.5%) | 100.0% (9/9) (95% CI 70.1%-100.0%) |

### customer_region - max gap 15.3 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| asia_pacific | 21 | 85.7% (18/21) (95% CI 65.4%-95.0%) | 76.2% (16/21) (95% CI 54.9%-89.4%) | 100.0% (17/17) (95% CI 81.6%-100.0%) |
| europe | 25 | 80.0% (20/25) (95% CI 60.9%-91.1%) | 76.0% (19/25) (95% CI 56.6%-88.5%) | 94.7% (18/19) (95% CI 75.4%-99.1%) |
| latin_america | 7 | 85.7% (6/7) (95% CI 48.7%-97.4%) | 57.1% (4/7) (95% CI 25.1%-84.2%) | 100.0% (3/3) (95% CI 43.9%-100.0%) |
| north_america | 27 | 70.4% (19/27) (95% CI 51.5%-84.2%) | 74.1% (20/27) (95% CI 55.3%-86.8%) | 92.9% (13/14) (95% CI 68.5%-98.7%) |

### channel - max gap 9.1 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| chat | 22 | 81.8% (18/22) (95% CI 61.5%-92.7%) | 59.1% (13/22) (95% CI 38.7%-76.7%) | 84.6% (11/13) (95% CI 57.8%-95.7%) |
| docs_comment | 16 | 81.2% (13/16) (95% CI 57.0%-93.4%) | 68.8% (11/16) (95% CI 44.4%-85.8%) | 100.0% (10/10) (95% CI 72.2%-100.0%) |
| email | 31 | 77.4% (24/31) (95% CI 60.2%-88.6%) | 83.9% (26/31) (95% CI 67.4%-92.9%) | 100.0% (22/22) (95% CI 85.1%-100.0%) |
| forum | 11 | 72.7% (8/11) (95% CI 43.4%-90.2%) | 81.8% (9/11) (95% CI 52.3%-94.9%) | 100.0% (8/8) (95% CI 67.6%-100.0%) |

### length - max gap 20.8 pts (OUTSIDE 5-point condition)

| group | n | quality | auto-answered | retrieval hit rate |
|---|---|---|---|---|
| long | 37 | 67.6% (25/37) (95% CI 51.5%-80.4%) | 75.7% (28/37) (95% CI 59.9%-86.6%) | 92.0% (23/25) (95% CI 75.0%-97.8%) |
| short | 43 | 88.4% (38/43) (95% CI 75.5%-94.9%) | 72.1% (31/43) (95% CI 57.3%-83.2%) | 100.0% (28/28) (95% CI 87.9%-100.0%) |

## Method notes

- Every figure above is computed by `evaluation/metrics.py` from this run; nothing is entered by hand.
- 'Sent' means released after all guardrails passed. Escalations include guardrail blocks.
- Figures should be treated with caution because the labels themselves are noisy (identical ticket texts carry different routing and answerability labels in the development data), the satisfaction proxy and hallucination rate need human review, and reply-time figures for escalated tickets are modelled rather than observed.
