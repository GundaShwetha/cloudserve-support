# Prompt library (register)

Every prompt the system or the author uses is a file in this directory with a header (`id`, `version`,
`category`, `serves`, `model`). The id and version of any build prompt used for a decision are written to
the decision log (`prompt_version` column), so every reply can be traced to the exact prompt text.

| ID | Category | File | Serves | Version | Used by |
|---|---|---|---|---|---|
| PR-01 | Specification | specification/PR-01_requirement_to_spec.md | all FR | 1.0 | author, start of week two |
| PR-02 | Review | review/PR-02_spec_and_code_review.md | traceability | 1.0 | author, after each component |
| PR-03 | Build | build/PR-03_answer_generation.md | FR-08, FR-09, FR-10, FR-11 | 1.0 | `src/generate.py` (LLMGenerator) |
| PR-04 | Build (template, no model) | build/PR-04_escalation_handover.md | FR-07 | 1.0 | `src/generate.py` (escalation_summary) |
| PR-05 | Evaluation | evaluation/PR-05_grounding_judge.md | NFR-03 | 1.0 | `evaluation/judge.py` (optional), human assessors |
| PR-06 | Evaluation | evaluation/PR-06_reply_quality_rubric.md | satisfaction proxy | 1.0 | human assessors on `review_sample.csv` |

Classification is deliberately **not** a prompt: intent, urgency and answerability come from a calibrated
supervised model (`src/classify.py`) because it is deterministic, free per ticket and measurably calibrated
(ADR-02 in docs/architecture.md).

## Change history

Record every change here, with the version bump and the reason (a new version whenever the text changes).

| Prompt | Version | Date | Change | Why |
|---|---|---|---|---|
| PR-01..PR-06 | 1.0 | | Initial versions. | |
| PR-04 | 1.0 | | Implemented as a template rather than a model call. | Escalation must work when the provider is down (A11); Daniel Okonkwo asked for the system to "show its working", which is structured data the system already holds. |

PR-03 has not yet been exercised against a live model in this repository (the build environment had no
provider access); its first live run is where a 1.1 is most likely to come from. Record what changes and why.
