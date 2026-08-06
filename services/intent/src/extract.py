"""Prompt -> Spec. THE ANTI-CIRCULARITY BOUNDARY.

`extract()` takes a **string**. Not a request object with an artifact on it, not
a path to one. Keep it that way -- it is leg 3 of the three-legged guarantee in
docs/agents/P2-intent-testgen.md, and it is the reason the intent tier is not a
tautology. If you ever find yourself wanting an element id in this file, the
answer is a semantic description, not an import.

## What is deterministic here, and what is not

The charter's trap for this service: *do the structured work first, reserve the
judge for the residue*. So this module extracts, by rule, only what a rule can
actually get right:

| Extracted deterministically      | Why a rule is enough                             |
|----------------------------------|--------------------------------------------------|
| numeric branch conditions        | "over 10000" has one reading, and D8's boundary  |
|                                  | cases (9999/10000/10001) are generated from it   |
| budget per instance              | a currency amount with a per-unit phrase         |
| trigger                          | a sentence-initial temporal clause               |
| integrations                     | a curated vocabulary, not open-ended inference   |
| error behaviour                  | the sentence that names a failure                |
| steps + kind hints               | first verb of each clause against a lexicon      |

Everything else is **residue** and is left empty rather than guessed:
`outputs`, step dependencies beyond prose order, which steps sit inside which
branch, and any paraphrase-level reading of intent. Empty is honest; a
plausible-looking wrong value is what makes a corpus run untrustworthy. A
`Refiner` fills the residue from D4 -- see the protocol at the bottom.

Precision over recall throughout: a clause whose verb is not in the lexicon
produces no step at all rather than a guessed one. A missing step is visible at
D5 as a sufficiency gap; an invented step silently corrupts every alignment
score computed against it.

Owner: P2.
"""
from __future__ import annotations

import re
from typing import Protocol

from wfeval.core.ir import BranchCondition, DataField, Spec, Step

# Bump when the rules below change shape, so the disk cache stops serving specs
# produced by an extractor that no longer exists. See cache.py.
EXTRACTOR_VERSION = "d3.1"

# A comparison whose subject is one of these has no variable in it. "Anything
# scoring above 0.8" and "never more than 20" both parse as thresholds and both
# name nothing P3 could seed or P4 could price, so they are dropped rather than
# turned into an expression_hint that reads like a real one. The threshold is
# then simply absent, which the refiner can fill and D5 can flag -- an invented
# variable name is silently wrong all the way through to D8's boundary cases.
_STOP_SUBJECTS = {
    "it", "this", "that", "they", "there", "them", "we", "you", "he", "she", "who",
    "anything", "everything", "nothing", "something", "never", "always", "someone",
    "anyone", "everyone", "nobody", "most", "some", "all", "both", "none", "one",
    "us", "me", "him", "her", "which", "what", "and", "or",
}

_DETERMINERS = {
    "the", "a", "an", "its", "their", "this", "that", "each", "every",
    "any", "our", "your", "his", "her", "my",
}
_VAR_LEADING = {
    "if", "when", "whenever", "unless", "once", "where", "and", "but", "so", "that", "while",
    "the", "a", "an", "its", "their", "any", "each", "every", "is", "are", "was", "were",
    "of", "for", "to", "in", "on", "at", "by", "with", "then", "otherwise", "either",
}

# comparator phrase -> operator. Longest phrases first when matching.
_COMPARATORS: dict[str, str] = {
    "greater than or equal to": ">=",
    "less than or equal to": "<=",
    "greater than": ">",
    "more than": ">",
    "less than": "<",
    "fewer than": "<",
    "at least": ">=",
    "at most": "<=",
    "no more than": "<=",
    "exceeds": ">",
    "exceed": ">",
    "over": ">",
    "above": ">",
    "under": "<",
    "below": "<",
}

_CURRENCY = r"[$£€]"

_BUDGET_RE = re.compile(
    r"(?P<lead>budget(?:ed)?(?:\s+(?:of|at))?"
    r"|(?:has\s+to\s+|must\s+|should\s+)?cost(?:s|ing)?\s+(?:us\s+)?(?:no\s+more\s+than|under|below|less\s+than|at\s+most)"
    r"|keep\s+it\s+(?:under|below)|(?:stay|spend)\s+(?:under|below)"
    r"|(?:under|below|less\s+than|no\s+more\s+than|at\s+most|up\s+to))\s+"
    rf"(?:{_CURRENCY}\s?(?P<major>\d+(?:\.\d+)?)(?:\s*(?:dollars?|usd|pounds?|euros?))?"
    r"|(?P<major_word>\d+(?:\.\d+)?)\s*(?:dollars?|usd|pounds?|euros?)"
    r"|(?P<minor>\d+(?:\.\d+)?)\s*(?:cents?|pence|p\b))"
    r"(?P<per>[^.;]{0,40}?\bper\b[^.;]{0,25}|[^.;]{0,20}\beach\b)?",
    re.IGNORECASE,
)

_PROBABILITY_RE = re.compile(
    r"(?:roughly|about|around|approximately|typically|maybe)?\s*(?P<pct>\d{1,3}(?:\.\d+)?)\s*(?:%|per\s?cent)\s+of\b",
    re.IGNORECASE,
)

_THRESHOLD_RE = re.compile(
    r"\b(?P<pre>the\s+|a\s+|an\s+)?(?P<var>[a-z][a-z'\-]*(?:\s+[a-z][a-z'\-]*){0,2}?)\s*"
    r"(?:\s(?:is|are|was|were|goes|gets|comes|totals?|amounts?\s+to))?\s*"
    rf"\b(?P<cmp>{'|'.join(sorted(_COMPARATORS, key=len, reverse=True))})\s+"
    rf"(?:{_CURRENCY}\s?)?(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|per\s?cent|hours?|days?|minutes?|weeks?|months?|items?|lines?)?",
    re.IGNORECASE,
)

_WEEKDAY = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
# An event trigger: the leading conjunction is dropped, leaving the event itself.
_TRIGGER_EVENT_RE = re.compile(
    r"^\s*(?:when(?:ever)?|once|each\s+time|every\s+time|as\s+soon\s+as|upon"
    r"|on\s+(?:receipt|arrival|submission|creation))\b",
    re.IGNORECASE,
)
# A schedule trigger: kept whole, because "2am" without "every night at" is not
# a trigger anyone can act on.
_TRIGGER_SCHEDULE_RE = re.compile(
    rf"^\s*(?:every\s+(?:day|morning|evening|hour|night|week|month|{_WEEKDAY})"
    rf"|on\s+the\s+(?:first|second|third|fourth|last)\s+(?:{_WEEKDAY}|day|working\s+day)"
    r"|nightly|daily|hourly|weekly|monthly"
    r"|(?:\d+|one|two|three|four|five|six|seven|ten|fourteen|thirty|ninety)\s+"
    r"(?:minutes?|hours?|days?|weeks?|months?)\s+(?:before|after))\b",
    re.IGNORECASE,
)
_TRIGGER_TAIL_RE = re.compile(
    r"\b(?:is\s+)?triggered\s+(?:by|when|whenever)\b|\bstarts?\s+when\b", re.IGNORECASE
)

_FAILURE_RE = re.compile(
    r"\b(fails?|failed|failure|errors?\s+out|an\s+error|times?\s+out|timeout|unavailable|"
    r"declined|rejected|bounces?|is\s+down|goes\s+down)\b",
    re.IGNORECASE,
)

# Integration vocabulary. Curated on purpose: an open-ended "any capitalised
# noun is a system" rule turns every proper noun in the prompt into a fake
# integration, and P4 prices integrations.
#
# Public because `align.py` matches the *artifact* against the same table. Both
# directions of the question -- "does the prompt name this system?" and "does the
# artifact invoke it?" -- are answered by the same vocabulary, and two tables
# would drift into reporting an integration missing because the artifact happens
# to spell it the way this one does not.
INTEGRATION_VOCABULARY: dict[str, str] = {
    "email": r"\b(e-?mails?|inbox|outlook|gmail|mailbox)\b",
    "slack": r"\bslack\b",
    "teams": r"\bms\s?teams\b|\bmicrosoft\s+teams\b",
    "sms": r"\b(sms|text\s+message|twilio)\b",
    "payments_api": r"\b(payments?\s+(?:api|gateway|provider|service)|stripe|adyen|braintree)\b",
    "crm": r"\b(crm|salesforce|hubspot)\b",
    "erp": r"\b(erp|sap|netsuite|oracle\s+financials)\b",
    "accounting": r"\b(quickbooks|xero|accounting\s+system)\b",
    "ticketing": r"\b(jira|servicenow|zendesk|freshdesk|ticketing\s+system)\b",
    "hris": r"\b(workday|bamboohr|hris)\b",
    "esignature": r"\b(docusign|adobe\s+sign|e-?signature)\b",
    "spreadsheet": r"\b(spreadsheet|google\s+sheets?|excel|csv)\b",
    "object_storage": r"\b(s3|blob\s+storage|object\s+storage)\b",
    "document_store": r"\b(sharepoint|google\s+drive|dropbox|box)\b",
    "database": r"\b(database|postgres|mysql|sql\s+server)\b",
    "sftp": r"\b(sftp|ftp)\b",
    "calendar": r"\b(calendar|google\s+calendar|outlook\s+calendar)\b",
    "shipping": r"\b(shipping\s+(?:api|provider)|fedex|ups|dhl)\b",
    "identity": r"\b(active\s+directory|okta|azure\s+ad|sso)\b",
}

# First verb of a clause -> (kind_hint, side_effecting). is_deterministic is
# derived: anything but an agent step is deterministic given its inputs.
# `agent` means a model has to read something and form a judgement -- that is
# what P4 prices differently and what a DMN table can sometimes replace.
_VERBS: dict[str, tuple[str, bool]] = {
    # agent — reads, interprets, produces text
    "extract": ("agent", False), "classify": ("agent", False), "categorise": ("agent", False),
    "categorize": ("agent", False), "summarise": ("agent", False), "summarize": ("agent", False),
    "interpret": ("agent", False), "analyse": ("agent", False), "analyze": ("agent", False),
    "draft": ("agent", False), "generate": ("agent", False), "transcribe": ("agent", False),
    "parse": ("agent", False), "read": ("agent", False), "identify": ("agent", False),
    "detect": ("agent", False), "translate": ("agent", False),
    # decision — routes, chooses, compares
    "route": ("decision", False), "decide": ("decision", False), "determine": ("decision", False),
    "check": ("decision", False), "compare": ("decision", False), "evaluate": ("decision", False),
    "triage": ("decision", False), "prioritise": ("decision", False), "prioritize": ("decision", False),
    "validate": ("decision", False), "verify": ("decision", False), "match": ("decision", False),
    # user — a human acts
    "approve": ("user", True), "reject": ("user", True), "review": ("user", False),
    "sign": ("user", True), "authorise": ("user", True), "authorize": ("user", True),
    "confirm": ("user", True), "escalate": ("user", True), "acknowledge": ("user", True),
    # service — a system is called, the world changes
    "pay": ("service", True), "charge": ("service", True), "refund": ("service", True),
    "send": ("service", True), "notify": ("service", True), "email": ("service", True),
    "alert": ("service", True), "message": ("service", True), "post": ("service", True),
    "create": ("service", True), "update": ("service", True), "delete": ("service", True),
    "remove": ("service", True), "add": ("service", True), "upload": ("service", True),
    "download": ("service", False), "fetch": ("service", False), "retrieve": ("service", False),
    "store": ("service", True), "save": ("service", True), "record": ("service", True),
    "log": ("service", True), "file": ("service", True), "archive": ("service", True),
    "park": ("service", True), "close": ("service", True), "open": ("service", True),
    "assign": ("service", True), "schedule": ("service", True), "book": ("service", True),
    "publish": ("service", True), "sync": ("service", True), "provision": ("service", True),
    "issue": ("service", True), "cancel": ("service", True), "ship": ("service", True),
    "print": ("service", True), "order": ("service", True), "raise": ("service", True),
    "flag": ("service", True), "tag": ("service", True), "attach": ("service", True),
    "import": ("service", True), "export": ("service", True), "invite": ("service", True),
    "enrol": ("service", True), "enroll": ("service", True), "set": ("service", True),
    "text": ("service", True), "remind": ("service", True), "call": ("service", True),
    "ring": ("service", True), "phone": ("service", True), "chase": ("service", True),
    "contact": ("service", True), "offer": ("service", True), "release": ("service", True),
    "mark": ("service", True), "hand": ("service", True), "retry": ("service", True),
    "patch": ("service", True), "snapshot": ("service", True), "grant": ("service", True),
    "revoke": ("service", True), "reset": ("service", True), "disable": ("service", True),
    "enable": ("service", True), "deactivate": ("service", True), "activate": ("service", True),
    "register": ("service", True), "settle": ("service", True), "reimburse": ("service", True),
    "decline": ("service", True), "renew": ("service", True), "collect": ("service", True),
    "deliver": ("service", True), "dispatch": ("service", True), "pack": ("service", True),
    "reorder": ("service", True), "replenish": ("service", True), "restore": ("service", True),
    "roll": ("service", True), "block": ("service", True), "quarantine": ("service", True),
    "redact": ("service", True), "anonymise": ("service", True), "anonymize": ("service", True),
    "purge": ("service", True), "erase": ("service", True), "credit": ("service", True),
    "debit": ("service", True), "invoice": ("service", True), "bill": ("service", True),
    "score": ("agent", False), "screen": ("agent", False), "rank": ("agent", False),
    "assess": ("agent", False), "redline": ("agent", False), "compose": ("agent", False),
    "compile": ("service", False), "gather": ("service", False), "collate": ("service", False),
    "run": ("service", False), "look": ("service", False), "search": ("service", False),
    "query": ("service", False), "wait": ("service", False), "stop": ("service", False),
}

# A lexicon word sitting after one of these is a noun doing duty as an object.
_NOT_BEFORE_A_VERB = _DETERMINERS | {"of", "to", "for", "with", "in", "on", "at", "by", "from", "into", "no"}

# Crude morphology. The prompts are prose, so the lexicon's base forms have to
# survive "creates", "registers", "issuing", "settled". Good enough for a first
# verb of a clause; a real lemmatiser is not worth a dependency here.
_SUFFIXES = (("ies", "y"), ("ses", "se"), ("shes", "sh"), ("ches", "ch"), ("es", "e"), ("s", ""),
             ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"))


def _lemma(word: str) -> str:
    """The lexicon key for `word`: itself if known, else the first base form
    reachable by stripping an inflection."""
    if word in _VERBS:
        return word
    for suffix, replacement in _SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            candidate = word[: -len(suffix)] + replacement
            if candidate in _VERBS:
                return candidate
    return word

# Any lexicon verb, inflected -- prose says "creates", not "create".
_ANY_VERB = r"(?:" + "|".join(sorted(_VERBS, key=len, reverse=True)) + r")(?:e?[sd]|ing)?"

_CLAUSE_SPLIT_RE = re.compile(
    r";|\bthen\b|\band\s+then\b|,?\s*\botherwise\b|,?\s*\band\s+(?=" + _ANY_VERB + r"\b)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# A leading conditional clause is dropped: the condition is already a branch,
# and what is left is the step. Two forms, because English writes both --
# "If the payment API fails, park the invoice" and the comma-less
# "If the amount is over 10000 route it to a manager".
_LEADING_CONDITION_RE = re.compile(
    r"^\s*(?:if|unless|when(?:ever)?|once|after|where)\b(?:[^,]*,\s*|.*?(?=\b" + _ANY_VERB + r"\b))",
    re.IGNORECASE,
)
# Words that can precede the subject of a comparison but are not part of it:
# "If the amount is over 10000" is a condition on `amount`, not on `if_the_amount`.
_LEADING_FILLER_RE = re.compile(
    r"^\s*(?:either\s+way|in\s+either\s+case|also|finally|then|next|first|afterwards|"
    r"please|and|but|so|meanwhile|at\s+the\s+end)\b[,\s]*",
    re.IGNORECASE,
)


class Refiner(Protocol):
    """The LLM residue seam, wired at D4.

    A refiner receives the prompt and the deterministic draft and returns a
    fuller Spec. It never receives an artifact -- there is no parameter for one
    and there will not be. Its cost is why cache.py exists.
    """

    name: str

    def refine(self, prompt: str, draft: Spec) -> Spec: ...


def extract(prompt: str, refiner: Refiner | None = None) -> Spec:
    """Structured extraction from the prompt ALONE.

    `refiner` is the LLM residue pass. None (today) means the deterministic
    draft is the answer, which is under-populated but never wrong-by-invention.
    """
    text = _normalise(prompt)
    masked, budget = _budget(text)
    masked, probability = _probability(masked)
    branches = _branches(masked, probability)

    spec = Spec(
        trigger=_trigger(text),
        steps=_steps(text),
        inputs=_inputs(text, branches),
        outputs=[],  # residue: naming the terminal state needs the refiner.
        branches=branches,
        error_behaviour=_error_behaviour(text),
        integrations=_integrations(text),
        budget_per_instance=budget,
        source="extracted",
    )
    return refiner.refine(prompt, spec) if refiner is not None else spec


# ---------- field extractors: each is a pure function of the prompt string ----------


def _normalise(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt).strip()


def _mask(text: str, span: tuple[int, int]) -> str:
    """Blank a matched span so a later rule cannot match inside it. Length is
    preserved so earlier spans stay valid."""
    start, end = span
    return text[:start] + " " * (end - start) + text[end:]


def _budget(text: str) -> tuple[str, float | None]:
    """Returns (text with the budget phrase masked, budget per instance).

    Masking matters: "keep it under 50 cents per invoice" would otherwise be
    read by the threshold rule as a branch condition on a variable called "it".
    """
    for m in _BUDGET_RE.finditer(text):
        major = m.group("major") or m.group("major_word")
        value = float(major) if major is not None else float(m.group("minor")) / 100.0
        # A bare amount is not a budget. It needs a per-unit phrase, or a lead-in
        # that says so ("budget of", "has to cost us no more than") -- otherwise
        # "claims under 500 are auto-approved" gets read as a price ceiling.
        lead = m.group("lead").lower()
        if not m.group("per") and "budget" not in lead and "cost" not in lead:
            continue
        return _mask(text, m.span()), value
    return text, None


def _probability(text: str) -> tuple[str, float | None]:
    m = _PROBABILITY_RE.search(text)
    if not m:
        return text, None
    pct = float(m.group("pct"))
    if not 0 <= pct <= 100:
        return text, None
    return _mask(text, m.span()), pct / 100.0


def _branches(masked: str, probability: float | None) -> list[BranchCondition]:
    """Numeric conditions only. These are the ones a rule reads correctly and
    the ones D8's boundary cases are generated from -- the off-by-one at a
    branch condition is the commonest behavioural bug in a generated workflow,
    so it matters more that these are right than that they are many."""
    out: list[BranchCondition] = []
    seen: set[str] = set()
    for m in _THRESHOLD_RE.finditer(masked):
        raw = m.group("var").lower().split()
        tokens = list(raw)
        while tokens and tokens[0] in _VAR_LEADING:
            tokens.pop(0)
        if not tokens or any(t in _STOP_SUBJECTS for t in tokens):
            continue
        var = _snake(" ".join(tokens))
        # Half the process nouns in this domain are also verbs -- score, order,
        # claim, credit. A determiner or a plural marks the noun reading ("the
        # score is at least 60", "orders above 500"); without either, a lexicon
        # verb here is an imperative that happens to precede a number ("route
        # over 500 to approval") and is not a condition on anything.
        nounish = bool(m.group("pre")) or any(t in _DETERMINERS for t in raw) or tokens[-1].endswith("s")
        if var in _VERBS and not nounish:
            continue
        op = _COMPARATORS[m.group("cmp").lower()]
        number = m.group("num").replace(",", "")
        unit = (m.group("unit") or "").strip().lower()
        expression = f"{var} {op} {number}"
        if expression in seen:
            continue
        seen.add(expression)
        description = _tidy(m.group(0))
        if unit in {"%", "per cent", "percent"}:
            description += " (a percentage, not an absolute figure)"
        out.append(
            BranchCondition(description=description, expression_hint=expression, probability_hint=None)
        )
    # A stated likelihood is only attributable when there is one branch to
    # attribute it to. With two, "roughly 10%" could belong to either, and
    # guessing puts a wrong number into P4's cost model.
    if probability is not None and len(out) == 1:
        out[0] = out[0].model_copy(update={"probability_hint": probability})
    return out


def _trigger(text: str) -> str | None:
    """A temporal clause opening the FIRST sentence, or an explicit "triggered
    by" anywhere.

    Two ways to get this wrong, both seen on the corpus. `when` mid-sentence
    ("notify the vendor when it's settled") is a step's timing. And a *later*
    sentence opening with a temporal clause ("When all three are done, the
    hiring manager confirms...") is a join inside the process, not its trigger
    -- reading it as one produces a confident, wrong trigger, which is worse
    than the SPEC-NO-TRIGGER that a missing one earns at D5.
    """
    sentences = _sentences(text)
    if sentences:
        first = sentences[0]
        clause = first.split(",")[0]
        if _TRIGGER_SCHEDULE_RE.match(first):
            return _tidy(clause)
        if _TRIGGER_EVENT_RE.match(first):
            return _tidy(_TRIGGER_EVENT_RE.sub("", clause, count=1)) or _tidy(clause)
    for sentence in sentences:
        tail = _TRIGGER_TAIL_RE.search(sentence)
        if tail:
            return _tidy(sentence[tail.end():].split(",")[0])
    return None


def _error_behaviour(text: str) -> str | None:
    """The sentence that says what happens when something fails. Absent means
    the prompt never said -- that is SPEC-NO-ERROR-BEHAVIOUR at D5, and it is a
    statement about the prompt, never about an artifact."""
    for sentence in _sentences(text):
        if _FAILURE_RE.search(sentence):
            return _tidy(sentence)
    return None


def _integrations(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(
        name for name, pattern in INTEGRATION_VOCABULARY.items() if re.search(pattern, lowered)
    )


def _steps(text: str) -> list[Step]:
    steps: list[Step] = []
    for sentence in _sentences(text):
        for clause in _CLAUSE_SPLIT_RE.split(sentence):
            step = _step_from_clause(clause)
            if step is None:
                continue
            step.id = f"s{len(steps) + 1}"
            # Prose order, which is the only ordering a rule can see. Real
            # dependencies -- and which steps sit inside which branch -- are
            # residue for the refiner; see the module docstring.
            step.depends_on = [steps[-1].id] if steps else []
            steps.append(step)
    return steps


def _step_from_clause(clause: str) -> Step | None:
    body = _LEADING_CONDITION_RE.sub("", clause)
    body = _LEADING_FILLER_RE.sub("", body)
    body = _tidy(body)
    if not body:
        return None
    # Only the opening words: a verb buried deep in a clause is usually part of
    # an object ("...for the finance team to review"), not the clause's action.
    opening = re.findall(r"[a-z][a-z'\-]*", body.lower())[:4]
    for position, raw in enumerate(opening):
        # A word after a preposition or determiner is the object, not the
        # action: "10% of invoices need approval" is not an "invoice" step.
        if position and opening[position - 1] in _NOT_BEFORE_A_VERB:
            continue
        word = _lemma(raw)
        if word not in _VERBS:
            continue
        kind, side_effecting = _VERBS[word]
        # "send it to a manager for approval" is a human decision point, not a
        # message: the approval noun outranks the verb that carries it.
        if re.search(r"\b(approval|sign[- ]off|manager|supervisor|reviewer|human)\b", body, re.IGNORECASE):
            kind, side_effecting = "user", True
        return Step(
            id="s?",
            description=body[0].upper() + body[1:],
            kind_hint=kind,
            depends_on=[],
            is_deterministic=kind != "agent",
            side_effecting=side_effecting,
        )
    return None


def _inputs(text: str, branches: list[BranchCondition]) -> list[DataField]:
    """Two rules only: anything a branch compares against is an input, and
    anything the prompt asks to be extracted is an input. `bound` stays None
    unless the prompt states a volume -- an unbounded collection is exactly
    what SPEC-UNBOUNDED-INPUT flags at D5 and what makes P4's cost unbounded,
    so inventing a bound here would hide two findings at once."""
    fields: dict[str, DataField] = {}
    for branch in branches:
        if not branch.expression_hint:
            continue
        name = branch.expression_hint.split()[0]
        fields.setdefault(name, DataField(name=name, type="decimal", required=True, bound=None))

    for m in re.finditer(r"\bextract(?:ing)?\s+(?P<list>[^.;]{3,120})", text, re.IGNORECASE):
        for raw in re.split(r",|\band\b", m.group("list")):
            name = _snake(re.sub(r"^\s*(?:the|a|an|its|their|all)\s+", "", raw.strip(), flags=re.IGNORECASE))
            if not name or name in _STOP_SUBJECTS or len(name) > 40:
                continue
            plural = name.endswith("s") and not name.endswith("ss")
            fields.setdefault(
                name,
                DataField(name=name, type="array" if plural else "string", required=True, bound=None),
            )
    return list(fields.values())


# ---------- text helpers ----------


def _sentences(text: str) -> list[str]:
    return [s for s in (_tidy(part) for part in _SENTENCE_SPLIT_RE.split(text)) if s]


def _tidy(fragment: str) -> str:
    return re.sub(r"\s+", " ", fragment).strip(" ,.;:-")


def _snake(fragment: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", fragment.strip().lower()).strip("_")
    return cleaned
