---
id: PR-06
version: 1.0
category: evaluation
serves: satisfaction proxy (business tier); used by human assessors on review_sample.csv, optionally by a model as a third opinion
model: human assessors (primary); optional model run at temperature 0
---
Score the reply from 1 to 5 against the reference answer written by a senior agent (where one exists) and the ticket.

5 - Answers the actual question, every step correct and supported, nothing important missing, clear for a non-native reader.
4 - Answers the question; one minor omission or slightly generic step.
3 - Relevant and correct but generic: the customer must work out which step applies to them.
2 - Partly relevant or misses the main point (e.g. answers a neighbouring question).
1 - Wrong, unsafe, makes a commitment, or would make the customer contact support again.

Also record: does it mention every point in must_mention (yes/no)? Does it make any claim in must_not_claim (yes/no)?
Two assessors score independently; report the mean, the share of 4-5 scores, and the agreement rate (scores within 1 point).
