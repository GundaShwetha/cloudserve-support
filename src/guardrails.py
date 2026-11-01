"""Validate: checks that run on every response before release and can block it (FR-12..FR-15, A7).

Guardrails (Governance Framework section 4). A failing guardrail BLOCKS the reply and escalates the
ticket - it never redacts and sends. Each check reports what it looked at and what it found, whether
or not it blocked, and the full result is written to the decision log.

Input-side (run before any reply is drafted):
  * instruction_integrity - the ticket tries to give the system instructions (prompt injection)
  * private_data_in_ticket - the ticket contains secrets/identifiers that a reply could echo
Output-side (run on the drafted reply):
  * private_data   - emails, phone numbers, keys/tokens, card or account numbers, customer ids or names
  * grounding      - every factual sentence cites a passage that was retrieved AND that passage
                     actually contains the sentence's content words and numbers
  * tone_and_scope - no refunds, credits, fixes, dates or other commitments; no off-scope content
  * confidence_floor - a routing confidence exists and the threshold was applied
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from .schemas import Draft, GuardrailResult, Retrieval, RouteDecision, Ticket

# ------------------------------------------------------------------------------- patterns
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<![\w.])(?:\+?\d[\d\s().-]{8,}\d)(?![\w.])")
_KEY = re.compile(
    r"\b(?:sk|pk|rk|cs|key|tok|token|api|ghp|gho|xox[abpr]|AKIA|AIza)[-_]?[A-Za-z0-9_\-]{12,}\b"
    r"|\b[A-Fa-f0-9]{32,}\b|\b[A-Za-z0-9+/]{40,}={0,2}"
)
_PASSWORD = re.compile(r"\b(?:password|passwd|pwd|passcode)\s*[:=]\s*\S+", re.I)
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_CUSTOMER_ID = re.compile(r"\bCUST-\d{3,}\b", re.I)
_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")

_INJECTION = [
    r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|system)?\s*(?:instructions|rules|prompts?|directions)",
    r"disregard\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)?\s*(?:instructions|rules|prompts?)",
    r"forget\s+(?:all\s+|your\s+)?(?:previous\s+)?(?:instructions|rules)",
    r"you\s+are\s+now\s+(?:a|an|the|in)\b",
    r"\bact\s+as\s+(?:a|an|the|if)\b",
    r"\bpretend\s+(?:to\s+be|you\s+are)\b",
    r"(?:reveal|print|show|repeat|output)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions|rules)",
    r"\bsystem\s*prompt\b",
    r"\bjail\s*break\b|\bdeveloper\s+mode\b|\bDAN\b",
    r"</?\s*(?:system|instructions|customer_ticket|passages?)\s*>",
    r"\bnew\s+instructions?\s*:",
    r"\b(?:issue|grant|approve|process)\s+(?:me\s+)?(?:a\s+)?(?:full\s+)?refund\b.*\b(?:you\s+must|immediately|now)\b",
]
_INJECTION_RE = [re.compile(p, re.I) for p in _INJECTION]

# Commitments and claims the system must never make (ground_truth_responses.json must_not_claim,
# Daniel Okonkwo on billing commitments, Governance Framework "tone and scope").
_COMMITMENTS = [
    r"\brefund(?:ed|s)?\b", r"\bcredit(?:ed|s)?\s+(?:has|have|will|to)\b", r"\bcompensat",
    r"\b(?:has|have)\s+been\s+(?:fixed|resolved|issued)\b", r"\bfixed\s+on\s+our\s+side\b",
    r"\bwe\s+(?:will|shall|'ll)\b", r"\bguarantee", r"\bpromise",
    r"\bby\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|end\s+of\s+(?:day|week|month))\b",
    r"\b(?:within|in)\s+\d+\s+(?:hours?|days?|weeks?)\s+we\b", r"\bdelivery\s+date\b", r"\bwaive",
    r"\broadmap\b", r"\b(?:next|upcoming)\s+release\b",
]
_COMMIT_RE = [re.compile(p, re.I) for p in _COMMITMENTS]
_OFFSCOPE = re.compile(r"\b(?:as an ai|language model|i cannot browse|chatgpt|openai)\b", re.I)

_STOP = set(
    "a an the and or but if then than so to of in on at by for with from into onto over under is are was were be been "
    "being it its this that these those there here you your yours we our us i me my they them their he she his her "
    "can could should would will may might must do does did done not no yes as also just only very more most such "
    "any all each every some which what when where who why how about after before again further once own same too "
    "out up down off above below until while because both few other nor".split()
    # meta words used when introducing documentation - not factual claims
    + "article articles covered cover covers steps step resolve resolves guidance relevant following documentation".split()
)


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in _STOP or len(w) < 3:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > 5 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out

_NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_NUM_WORDS.update({"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
                   "seventy": 70, "eighty": 80, "ninety": 90})
_SCALES = {"hundred": 100, "thousand": 1000}


def numbers_in(text: str) -> set[str]:
    """Every number in the text, whether written as digits or as words ('two hundred' -> '200')."""
    found = set(re.findall(r"\b\d+(?:\.\d+)?\b", text))
    total, current = 0, None
    for w in re.findall(r"[a-z]+", text.lower().replace("-", " ")):
        if w in _NUM_WORDS:
            current = (current or 0) + _NUM_WORDS[w]
        elif w in _SCALES and current is not None:
            current *= _SCALES[w]
            if _SCALES[w] >= 1000:
                total, current = total + current, 0
        elif w == "and" and current is not None:
            continue
        else:
            if current is not None:
                found.add(str(total + current))
            total, current = 0, None
    if current is not None:
        found.add(str(total + current))
    return found

def _luhn(digits: str) -> bool:
    nums = [int(d) for d in digits if d.isdigit()]
    if len(nums) < 13:
        return False
    total, alt = 0, False
    for d in reversed(nums):
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def find_private_data(text: str, allowed_names: Iterable[str] = (), other_names: Iterable[str] = ()) -> list[str]:
    """Return the kinds of private data present in `text` (never the values themselves)."""
    found = []
    if _EMAIL.search(text):
        found.append("email_address")
    if _KEY.search(text):
        found.append("key_or_token")
    if _PASSWORD.search(text):
        found.append("password")
    if any(_luhn(m.group()) for m in _CARD.finditer(text)):
        found.append("card_number")
    if _IBAN.search(text):
        found.append("bank_account")
    if _CUSTOMER_ID.search(text):
        found.append("customer_id")
    if _IPV4.search(text):
        found.append("ip_address")
    for m in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 9 <= len(digits) <= 15 and not _luhn(digits):
            found.append("phone_number")
            break
    lowered = text.lower()
    allowed = {n.lower() for n in allowed_names if n}
    for name in other_names:
        n = (name or "").strip().lower()
        if len(n) >= 5 and " " in n and n not in allowed and n in lowered:
            found.append("other_customer_name")
            break
    return found


def detect_injection(text: str) -> Optional[str]:
    for rx in _INJECTION_RE:
        m = rx.search(text or "")
        if m:
            return m.group(0)[:60]
    return None


# ------------------------------------------------------------------------------- checks
def check_input(ticket: Ticket) -> list[GuardrailResult]:
    results = []
    hit = detect_injection(ticket.text)
    results.append(
        GuardrailResult("instruction_integrity", "fail", f"ticket contains an instruction to the system: '{hit}'")
        if hit else GuardrailResult("instruction_integrity", "pass", "no instruction-like content found")
    )
    kinds = [k for k in find_private_data(ticket.text) if k not in ("ip_address",)]
    results.append(
        GuardrailResult("private_data_in_ticket", "fail", "ticket contains: " + ", ".join(sorted(set(kinds))))
        if kinds else GuardrailResult("private_data_in_ticket", "pass", "no secrets or identifiers in ticket")
    )
    return results


def check_grounding(draft: Draft, retrieval: Retrieval, min_support: float, template: set[str]) -> GuardrailResult:
    if not draft.sentences:
        return GuardrailResult("grounding", "fail", "no sentences to check")
    by_id = {p.chunk_id: p for p in retrieval.passages}
    problems, checked = [], 0
    for s in draft.sentences:
        if s.text in template:
            continue
        checked += 1
        if not s.citations:
            problems.append(f"uncited sentence: '{s.text[:60]}'")
            continue
        unknown = [c for c in s.citations if c not in by_id]
        if unknown:
            problems.append(f"citation not among retrieved passages: {unknown[0]}")
            continue
        source = " ".join(by_id[c].text + " " + by_id[c].title for c in s.citations)
        src_tokens = set(_tokens(source))
        sent_tokens = _tokens(s.text)
        if sent_tokens:
            support = sum(1 for w in sent_tokens if w in src_tokens) / len(sent_tokens)
            if support < min_support:
                problems.append(f"only {support:.0%} of '{s.text[:50]}' is found in {s.citations[0]}")
                continue
        source_numbers = numbers_in(source)
        missing_numbers = [n for n in re.findall(r"\b\d+(?:\.\d+)?\b", s.text)
                           if n not in source_numbers and not re.fullmatch(r"\d", n)]
        if missing_numbers:
            problems.append(f"number {missing_numbers[0]} not in cited passage")
    if checked == 0:
        return GuardrailResult("grounding", "fail", "reply contains no factual sentences")
    if problems:
        return GuardrailResult("grounding", "fail", "; ".join(problems[:3]))
    return GuardrailResult("grounding", "pass", f"{checked} sentences, every one cited and supported by a retrieved passage")


def check_scope(text: str, source_text: str = "") -> GuardrailResult:
    source_lower = source_text.lower()
    for rx in _COMMIT_RE:
        for m in rx.finditer(text):
            # Quoting the documentation is not the system making a commitment of its own.
            if m.group(0).lower() in source_lower:
                continue
            return GuardrailResult("tone_and_scope", "fail", f"reply makes a commitment or out-of-scope claim: '{m.group(0)}'")
    if _OFFSCOPE.search(text):
        return GuardrailResult("tone_and_scope", "fail", "reply contains out-of-scope self-reference")
    return GuardrailResult("tone_and_scope", "pass", "no commitments about refunds, fixes, dates or roadmap")


def check_output(draft: Draft, retrieval: Retrieval, route: Optional[RouteDecision], ticket: Ticket,
                 min_support: float, other_names: Iterable[str] = (), template: set[str] = frozenset()) -> list[GuardrailResult]:
    text = draft.text
    body_only = " ".join(s.text for s in draft.sentences if s.text not in template)
    kinds = find_private_data(text, allowed_names=[], other_names=list(other_names) + [ticket.customer_name])
    results = [
        GuardrailResult("private_data", "fail", "reply contains: " + ", ".join(sorted(set(kinds))))
        if kinds else GuardrailResult("private_data", "pass", "no private data in reply"),
        check_grounding(draft, retrieval, min_support, template),
        check_scope(body_only, " ".join(p.text for p in retrieval.passages)),
    ]
    if route is None or route.confidence is None or route.action != "auto_respond":
        results.append(GuardrailResult("confidence_floor", "fail", "no routing decision with a confidence was applied"))
    else:
        results.append(GuardrailResult(
            "confidence_floor", "pass", f"routing confidence {route.confidence:.2f}, threshold {route.threshold:.2f} applied"))
    return results


def blocked(results: list[GuardrailResult]) -> list[GuardrailResult]:
    return [r for r in results if r.status == "fail"]
