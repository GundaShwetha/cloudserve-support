# Governance: risk, fairness, decision logging, incident response

Owners are roles at CloudServe. Replace the role with a named person when the system is handed over;
"the author" is the person submitting this project.

## 1. Decision logging (FR-16, NFR-05)

Table `decisions` in `storage/decisions.db` (schema in `src/logging_store.py`) records, for every stage
of every ticket: decision id, run id, timestamp, ticket id, stage, masked input summary and SHA-256 of
the full input, model name and version, prediction, confidence, alternatives considered, sources used
(article and chunk ids with scores), threshold applied, action taken, a human-readable reason,
guardrail results, prompt version and requirement ids. Exactly one `final` row per ticket.

Coverage check: `metrics_report.md` -> "Decision log coverage" (final rows == tickets processed), and
`decision_log.csv` in every run folder. Validation run: 80/80, 539 rows.

To answer "why did it do that?" for a ticket: `GET /decisions/{ticket_id}` or
`SELECT stage, action_taken, reason, prompt_version FROM decisions WHERE ticket_id = ? ORDER BY seq`.

## 2. Risk register

Likelihood and impact: 1 (low) to 3 (high). Score = L x I; 6-9 needs a written mitigation before build.

| ID | Risk | L | I | Score | Mitigation in the design (the control, not a hope) | Evidence it works | Owner |
|---|---|---|---|---|---|---|---|
| R-01 | Confident, incorrect answer sent | 2 | 3 | 6 | Never-auto policy for risky classes; answerability threshold chosen by cost simulation; replies built only from retrieved passages; grounding guardrail blocks any sentence not supported by its cited passage; disclosure + "reply to reach an engineer" | Run 2: 0 ungrounded replies released, 6 model drafts blocked; automation precision 76.9 % (label noise limits this) | Head of Support |
| R-02 | Private data in an outbound reply | 1 | 3 | 3 | Input guardrail blocks tickets containing secrets/identifiers before drafting; output guardrail scans every reply (e-mail, phone, keys, passwords, card/IBAN, customer ids, other customers' names); block, never redact-and-send; prompt rule 5; log masks inputs | Run 2: 0 detections in 52 sent replies; tests/test_guardrails.py | Author / Security lead |
| R-03 | Customer text treated as an instruction | 2 | 3 | 6 | Ticket wrapped in a delimited data block with tag-forging neutralised; prompt rule 6; injection guardrail blocks before drafting; extractive mode ignores ticket text entirely | demo ticket DEMO-GUARDRAIL-06 blocked; tests | Author |
| R-04 | Some customer groups get worse answers | 3 | 2 | 6 | Fairness audit per run (tier, region, fluency, channel, length); intent prior bridges vocabulary gaps; region and tier are never model features | Run 2: non-fluent 57.9 % vs fluent 78.7 % - **not met on validation**; not reproduced on 500 development tickets (section 3) | Head of Support |
| R-05 | Documentation goes stale | 2 | 2 | 4 | Answers come only from the 29 reviewed articles (not agents' private snippet files); every reply cites the article so Ines can tell an article error from a system error; corpus hash recorded in each retrieval decision; index rebuilt when the corpus changes | `last_reviewed_days_ago` = 0 for 29/29 today | Technical Writer (Ines Varga's role) |
| R-06 | Model provider unavailable | 3 | 1 | 3 | Retries, backoff, circuit breaker, cache; extractive fallback; escalation path needs no model | tests: outage, timeouts, 429 | Author |
| R-07 | Latency degrades under load | 1 | 2 | 2 | Classifier and retrieval local (~25 ms p95 end to end without the model); model call bounded by timeout; Prometheus latency histogram and Grafana p95 panel | Run 2: median 0.14 s, p95 45 s with model drafting (Nemotron Ultra) | Author |
| R-08 | Costs rise with volume | 1 | 1 | 1 | Model used only for drafting auto-answers (~74 % of tickets); response cache; free tier throttle; extractive mode costs nothing | 0 paid calls required | Head of Support |
| R-09 | Wrong urgency hides an incident | 2 | 3 | 6 | Urgent incidents escalated by policy; urgency estimate shown with confidence in the handover note; **urgency model is weak (41 % on validation)** - mitigation needed | Urgency 41 % accurate in both runs; run 1: 1 urgent performance ticket answered automatically | Author |
| R-10 | Kill switch not used in time | 1 | 3 | 3 | File-based switch, no deploy; Grafana panel; incident procedure below names who may use it | test_kill_switch_takes_effect_on_next_ticket | Head of Support |

## 3. Fairness audit

Method: every harness run segments the labelled tickets by customer tier, language fluency, region,
channel and length (above/below the median word count) and reports, per group, the share handled
correctly (routing matches the label and, if answered, an expected article was cited), the automation
rate and the retrieval hit rate. Groups under 5 tickets are excluded from the gap. Sample sizes and
95 % intervals are printed with every figure.

Validation run 2 (1 Nov 2026, full stack, 80 tickets, `evaluation/results/validation_run_fullstack/metrics_report.md`):

| Segment | Tickets | Correct handling | Gap to best group |
|---|---|---|---|
| Standard tier | 42 | 78.6 % | (best tier) |
| Business tier | 30 | 70.0 % | 8.6 pts |
| Enterprise tier | 8 | 62.5 % | 16.1 pts (n = 8) |
| Fluent | 61 | 78.7 % | - |
| **Non-fluent** | 19 | **57.9 %** | **20.8 pts** |
| Short tickets | 43 | 76.7 % | - |
| Long tickets | 37 | 70.3 % | 6.5 pts |

Retrieval found the right article for 9/9 answerable non-fluent tickets; the gap is in routing, and was similar in
run 1. On the 500 development tickets (5-fold out-of-fold) non-fluent routing accuracy is 80.8 % against 76.3 %
for fluent writers, and the cost method does not choose a stricter threshold for them (0.52 vs 0.54;
`python -m evaluation.fairness_check`, docs/fairness_development.md). Tuning a threshold to 19 validation tickets
would be overfitting, so the threshold is unchanged; non-fluent tickets go to supervised mode (an agent approves
the draft) in the pilot until more data shows whether the gap is real.

## 4. Guardrails

| Guardrail | Checks | When it fires |
|---|---|---|
| instruction_integrity (input) | instruction-like text, delimiter forging | block before drafting, escalate, input recorded (masked) |
| private_data_in_ticket (input) | keys, passwords, cards, e-mail addresses, customer ids in the ticket | block before drafting, escalate |
| private_data (output) | same patterns plus phone numbers, IPs and other customers' names in the reply | block, escalate - never redact and send |
| grounding (output) | every factual sentence cited; citation is a retrieved passage; content words and numbers present in it | block, escalate with the unsupported sentence named |
| tone_and_scope (output) | refunds, credits, compensation, fixes, dates, roadmap, "we will" | block, escalate |
| confidence_floor (output) | a routing confidence exists and the threshold was applied | escalate |

All run on every ticket in production, in the harness and in the demo; there is no flag to disable them.

## 5. Incident response

Written for someone who has never seen the system, at 2 a.m.

| Step | What to do | Who | How long |
|---|---|---|---|
| 1. Detect | Signals: a customer or agent reports a wrong/odd automatic reply; Grafana shows a jump in guardrail blocks, provider failures, or a shift in the confidence distribution; the answered share moves by more than 10 points in an hour. | On-call support lead | as soon as seen |
| 2. Contain | Stop automatic replies: `python -m src.killswitch on --reason "<what happened>"` on the server (or `POST /kill-switch` with the admin token, or set `AUTO_RESPOND_ENABLED=false`). Confirm with `python -m src.killswitch status` and by submitting one test ticket: it must come back `escalated` with reason "kill switch". | On-call support lead (any Tier 2 engineer may also do it) | < 5 minutes |
| 3. Assess | Find the affected tickets: `SELECT ticket_id, created_at, reason FROM decisions WHERE stage='final' AND action_taken='auto_respond' AND created_at > '<start>'`. For each, read the `generation` and `validation` rows: which article was cited, which prompt version, which guardrails passed. Decide: article wrong (-> Technical Writer), system misread the article (-> author), or a guardrail gap. | Tier 2 engineer + author | < 2 hours |
| 4. Notify | Customers who received a wrong reply get a human follow-up correcting it, within the SLA (2 h). Head of Support informed; if private data was involved, the data-protection contact the same day. | Head of Support | same day |
| 5. Remediate | Fix the article, the prompt (new version in prompts/, logged), the threshold (re-run `python -m src.train`) or the guardrail; add a test reproducing the incident; run the harness on development data and compare. | Author / Technical Writer | before re-enabling |
| 6. Review | Release the kill switch only after the new test passes and Head of Support agrees: `python -m src.killswitch off`. Write a short post-incident note (what, impact, cause, fix, which control should have caught it). | Head of Support + author | within 5 working days |

### Kill switch

| Question | Answer |
|---|---|
| Mechanism | File `storage/KILL_SWITCH` (created by `python -m src.killswitch on`), or `AUTO_RESPOND_ENABLED=false`, or `POST /kill-switch` with `X-Admin-Token`. Checked for every ticket. |
| Who may use it | On-call support lead, any Tier 2 engineer, Head of Support. Releasing it needs Head of Support. |
| Time to effect | The next ticket processed (no restart, no deployment). |
| Tickets in flight | A ticket already past routing finishes its current path (at most one per worker); all later tickets escalate with their handover note. |
| How it is tested | `tests/test_failures.py::test_kill_switch_takes_effect_on_next_ticket` on every CI run. |

## 6. Declaration

| Statement | Position |
|---|---|
| This system must never ... | send a customer a reply that is not supported by CloudServe's reviewed documentation, contains private data, makes a commitment about money, fixes or dates, or answers a security, compliance, feature-request or unclear ticket. |
| The mechanism that enforces that is ... | the never-auto routing policy, the input guardrails that block before drafting, and the output guardrails (grounding, private data, scope) that block and escalate every non-compliant reply - on every ticket, with no switch to turn them off - plus the kill switch. |
| The most likely way it could still cause harm is ... | a reply that is fully supported by an article but answers a question the customer did not ask - most often for non-fluent writers, where routing errors were three times as frequent on validation. |
| We would not deploy this without first ... | confirming on more tickets whether the non-fluent gap seen on validation is real and closing it if it is; completing the two-assessor review of 50 replies with a hallucination rate of 5 % or less; moving to a model fast enough for live chat; adding a production-impact check so urgent incidents never depend on the urgency model alone; and a supervised pilot in which agents approve every automated reply before it is sent. |
