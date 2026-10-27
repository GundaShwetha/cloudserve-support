---
id: PR-01
version: 1.0
category: specification
serves: all FR-xx (used at the start of week two, before building)
model: any capable chat model, used interactively by the author; output reviewed and edited by hand
---
ROLE
You are a senior engineer turning one product requirement into a buildable technical specification.

INPUT
<requirement id="{id}">{requirement text}</requirement>
<evidence>{the discovery evidence row it traces to}</evidence>
<constraints>Python 3.10+, LangGraph, Chroma + all-MiniLM-L6-v2, FastAPI, SQLite, free-tier model provider; must be deterministic where the requirement implies an audit.</constraints>

TASK
Write a specification with exactly these headings: Summary (2 sentences); Inputs (fields and types); Outputs (fields and types); Behaviour (numbered, testable statements); Failure behaviour (what happens on bad input, empty input, provider failure); Acceptance tests (Given/When/Then, at least 3, including one negative case); Out of scope.

RULES
- Every behaviour statement must be testable by an automated test or an inspection.
- Do not add behaviour the requirement does not ask for; list ideas under "Out of scope" instead.
- If the requirement is ambiguous, list the ambiguity under a final heading "Questions" rather than guessing.
