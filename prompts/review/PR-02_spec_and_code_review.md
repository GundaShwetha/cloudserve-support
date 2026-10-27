---
id: PR-02
version: 1.0
category: review
serves: traceability check (Stage 3 section 4); applied to each component after it was drafted
model: any capable chat model, used interactively; findings triaged by the author
---
ROLE
You are reviewing one component of a customer-support automation system against the requirement it is meant to satisfy.

INPUT
<requirement id="{id}">{text}</requirement>
<specification>{spec}</specification>
<code path="{path}">{code}</code>

TASK
1. List every behaviour in the specification and state whether the code implements it (yes / partly / no), citing the line.
2. List anything the code does that the specification does not ask for.
3. List failure paths that are not handled (empty input, exceptions from dependencies, timeouts, malformed data).
4. List anything that could let customer text change the system's instructions, or let private data reach a reply.
5. Give at most three concrete changes, most important first.

RULES
Be specific; quote identifiers. Do not rewrite the code. If everything is satisfied, say so plainly.
