# Traceability: evidence -> requirement -> specification/prompt -> code -> test

Evidence ids: **E** = docs/discovery_evidence.md (ticket data); **I-x** = stakeholder interview
(I-MA Marcus Adeyemi, I-SR Sofia Restrepo, I-DO Daniel Okonkwo, I-IV Ines Varga, I-RM Ravi Menon);
**B** = Project Brief / Build Specification / Governance Framework. Every decision row in the log
carries the requirement ids of the stage that produced it (`requirement_ids` column).

| Req | Requirement (short) | Evidence | Spec / prompt | Code | Tests | Acceptance |
|---|---|---|---|---|---|---|
| FR-01 | Normalise four channels into one representation, keep original text and channel, never fail on bad input | B (four channels), E2 (channels behave differently; chat has no subject), E9 (subjects unreliable) | Stage 3 spec FR-01 | `src/ingest.py` | test_ingest.py | A2 |
| FR-02 | Classify intent, urgency, answerability with calibrated confidence and recorded alternatives; defined fallback | I-MA ("I would be guessing"), E8, B (calibration condition) | Stage 3 spec FR-02, ADR-02 | `src/classify.py`, `src/train.py` | test_classify.py | A3 |
| FR-03 | Retrieve passages from the 29-article KB despite vocabulary mismatch; ids resolve; nothing below relevance threshold | I-IV (title/exact-term search fails), I-SR ("I cannot find things"), E1.7, E1.8 | ADR-03, ADR-04 | `src/retrieve.py` | test_retrieve.py | A4 |
| FR-04 | Route auto vs escalate with thresholds chosen from data; deterministic; plain-language reason | I-MA ("explainable", "rather it said nothing"), B (threshold from data) | ADR-07, docs/threshold_analysis.md | `src/route.py`, `src/train.py` | test_route.py | A5 |
| FR-05 | Never auto-answer security incidents, compliance requests, feature requests, unclear requests | I-SR (security always escalates), I-DO (security, data location), I-IV (feature requests, roadmap), E10, E1.10 | route rule 3 | `src/schemas.py` NEVER_AUTO_INTENTS, `src/route.py` | test_route.py::test_rules | governance |
| FR-06 | Escalate urgent production incidents (performance/database, high urgency) | I-RM (deployment failing at 9 a.m.), E3 (high urgency waits longest), E10 | route rule 4 | `src/route.py` | test_route.py::test_rules | - |
| FR-07 | Every escalation carries a handover note: likely intent and alternatives, reason, what was uncertain, articles found, unsent draft | I-DO ("show its working"), I-SR ("draft and the relevant page attached"), E1.8 | PR-04 | `src/generate.py::escalation_summary`, `pipeline.n_escalate` | test_pipeline.py::test_escalation_carries_summary_and_reason | Brief s05 |
| FR-08 | Replies grounded in retrieved passages with citations that resolve | I-IV (which article), I-RM ("the page it came from"), B | PR-03 | `src/generate.py` | test_generate.py | A6 |
| FR-09 | Say plainly when the documentation does not answer (no gap-filling) | I-MA, I-RM ("sounds certain and is wrong") | PR-03 rule 3 | `generate.py` cannot_answer -> escalate | test_cannot_answer_is_respected | Build spec |
| FR-10 | Customer text cannot redirect the system | Stage 3 injection note, R-03 | PR-03 rule 6, delimiter neutralising | `generate.py::_neutralise`, `guardrails.detect_injection` | test_ticket_cannot_close_the_data_block, test_injection... | A7 |
| FR-11 | Automatic replies disclose that they are automated and how to reach a person | I-RM ("would you want to know it was automated? Yes") | DISCLOSURE text | `generate.py` | test_each_channel_end_to_end | - |
| FR-12 | Block any reply containing private data | B (zero occurrences), R-02 | guardrail spec | `guardrails.py` private_data / private_data_in_ticket | test_private_data_blocks | A7 |
| FR-13 | Block replies whose claims are not supported by the cited passage | I-MA (screenshot risk), I-DO (stale snippets), B (hallucination <= 5 %) | guardrail spec | `guardrails.check_grounding` | test_unsupported_claims... | A7 |
| FR-14 | Block commitments: refunds, credits, fixes, dates, roadmap | I-DO (billing commitments), ground_truth must_not_claim | PR-03 rule 4 | `guardrails.check_scope` | test_commitments_block... | A7 |
| FR-15 | Guardrails run on every reply and block (no warn-only mode) | B (Build spec, Governance s4) | - | `pipeline.n_validate` | test_output_guardrail_blocks_a_bad_model_reply | A7 |
| FR-16 | Log every decision with the governance fields; reconcilable | I-MA ("compliance review in the autumn... say why it did what it did"), B | ADR-08 | `src/logging_store.py`, `pipeline.n_finalise` | test_decision_log_has_required_fields_and_reconciles | A8 |
| FR-17 | Kill switch without deployment | B (Governance s5) | ADR-09 | `src/killswitch.py`, `route.py` rule 1 | test_kill_switch_takes_effect_on_next_ticket | governance |
| FR-18 | One command processes any ticket file unattended and writes a metrics report | B (A9, A10) | - | `evaluation/harness.py`, `metrics.py` | test_harness.py | A9, A10 |
| FR-19 | Degrade, never crash: no hit, timeouts, outage, rate limits, malformed input | B (A11), availability 99.5 % | provider design | `src/provider.py`, `pipeline._emergency` | test_failures.py | A11 |
| NFR-01 | p95 latency < 3 s | B, I-RM | - | local classifier and retrieval | report: p95 | - |
| NFR-02 | Available through provider outages | B | ADR-05 | extractive fallback | test_failures.py | A11 |
| NFR-03 | Intent precision >= 85 %, citation accuracy >= 95 %, hallucination <= 5 % | B | - | - | metrics report | - |
| NFR-04 | Zero private data in replies | B | - | guardrails | metrics report | - |
| NFR-05 | Complete decision coverage | B | - | logging_store | metrics report | A8 |
| NFR-06 | Quality gap between customer groups < 5 points | B, I-SR (non-fluent), I-RM / I-MA (tier) | - | metrics fairness | metrics report | - |
| NFR-07 | Zero cost | B | - | local models, cache, throttle | - | - |
| A1 | Runs from a clean checkout via README | B | README | - | CI workflow | A1 |
| A12 | Tests run with one command | B | README | - | `python -m pytest tests/ -v` | A12 |
