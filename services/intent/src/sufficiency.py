"""Prompt -> SPEC-* sufficiency diagnostics. D5.

*Not* "is this workflow wrong?" -- that is validation, and it is P1's. This asks
a narrower and earlier question: **did the user tell us enough to evaluate what
the generator built?** A prompt that never says what starts the process gives the
generator a free choice of start event, and intent alignment then has nothing to
check that choice against. The diagnostic is a statement about the *prompt*, and
it is emitted whether or not an artifact exists.

Which is why nothing in this prefix is ever an `error` (`0008`): an
under-specified prompt is a normal thing for a user to send. The severity ladder
here describes *our* inability to evaluate confidently, not the user's inability
to write. `warning` when a downstream tier will otherwise produce a
wrong-looking number; `info` when it only costs advice quality.

## What these are worth, measured

The corpus carries `expected_diagnostics` per case -- ground truth written at D2,
before any of this existed, so these rules were tuned against labels they could
not influence. `tests/unit/intent/test_sufficiency_corpus.py` scores every rule
over all 40 cases and pins precision and recall per code. Read that file before
changing a rule here: several are deliberately low-recall, and the test says
which and why.

The bar that matters most is **c01, the negative control**: trigger, threshold,
failure path and budget all stated, so it must raise nothing at all. A
sufficiency checker that cannot stay quiet on a complete prompt is worse than no
checker, because every real prompt will then carry noise that hides the findings
that mean something.

## Precision over recall, again

Same trade as `extract.py`, for a sharper reason. A false `SPEC-*` tells the
generation team to fix a prompt that was fine; enough of those and the whole
prefix gets ignored, including the true ones. A miss costs one finding. So every
rule below declines when it cannot tell -- and the declines are the tested part.

## Ask the prompt, not the extractor

**These rules read the prompt text. They do not treat an empty field on the Spec
as evidence that the prompt is missing something.** The first version of this
module did, and scored 0.71 precision: `extract.py` is deliberately low-recall,
so `spec.trigger is None` fires on fourteen corpus prompts that state their
trigger perfectly well in words the rules happened not to match. Keying a
diagnostic off a precision-first extractor's silence inherits every one of its
misses and reports them as the *user's* omission.

So the direction is inverted here. Each rule looks for the thing being reported
missing, in the prompt, with a deliberately *broad* pattern -- and fires only
when that broad search comes up empty. The Spec is consulted only where it can
settle a question positively (`budget_per_instance` is a number; `integrations`
found a real name), never as the sole evidence of an absence.

Owner: P2.  Codes: `docs/decisions/0008-spec-sufficiency-code-registry.md` (append-only).
"""
from __future__ import annotations

import re

from wfeval.core.diagnostics import Diagnostic, Severity
from wfeval.core.ir import Spec

# Bump with the rules, so a cached spec+diagnostics pair cannot outlive them.
SUFFICIENCY_VERSION = "d5.1"

# ---------- lexicons ----------

# Fuzzy magnitude and importance. A branch on one of these has no threshold, so
# D8 would have to invent the number and would then be testing its own guess.
#
# `critical` is deliberately ABSENT. In these domains it is nearly always a
# categorical flag already present in the data ("if the result is flagged
# critical"), not a judgement the workflow has to make -- corpus case c30 is
# exactly that, and including the word cost a false positive there.
_FUZZY_MAGNITUDE = {
    "big", "bigger", "biggest", "large", "larger", "small", "smaller", "high-value",
    "low-value", "expensive", "cheap", "costly", "significant", "substantial",
    "sizeable", "major", "minor", "important", "urgent", "sensitive", "risky",
    "complex", "simple", "heavy", "light", "lengthy", "unusual", "suspicious",
}

# A fuzzy word sitting after one of these is a *stated category* the data already
# carries, not a judgement the process has to form. "Flagged urgent" is a field
# to read; "urgent tickets" is a decision nobody has defined.
_CATEGORISED = r"(?:flagged|classified|marked|labell?ed|tagged|rated|categoris|categoriz|deemed|set\s+to)\w*\s+(?:as\s+)?"

# A named severity or priority level means the prompt did define its categories,
# even if it never gave a number. c09's "P1 tickets" and c23's "Sev1" are the
# cases; without this the rule fires on both and they are correctly labelled.
_NAMED_LEVEL_RE = re.compile(
    r"\b(?:p[1-5]|sev(?:erity)?\s?[1-5]|tier\s?[1-5a-c]|priority\s?[1-5]|grade\s?[a-f])\b",
    re.IGNORECASE,
)

# A stated numeric threshold anywhere. If the prompt gave a number to route on,
# a fuzzy adjective elsewhere in it ("anything larger goes to an underwriter")
# is prose referring back to that number, not an undefined criterion.
_NUMERIC_THRESHOLD_RE = re.compile(
    r"\b(?:over|above|under|below|exceed\w*|more\s+than|less\s+than|fewer\s+than|at\s+least"
    r"|at\s+most|up\s+to|and\s+above|and\s+below|between|from)\s+"
    r"[^.;]{0,15}?\d"
    r"|\b\d[\d,.]*\s*(?:%|per\s?cent)"
    r"|\bscoring\s+\w+\s+\d"
    r"|\b\d[\d,.]*\s+or\s+(?:less|more|fewer|above|below|higher|lower)\b",
    re.IGNORECASE,
)

# The commonest English way to state a trigger: an actor performing an initiating
# act, in the opening sentence. Matched in the third person singular only, and
# only in that sentence -- "Read the spreadsheet and create a record" (u04) is an
# imperative with no actor, and an unanchored search finds "the ... create" in it
# and wrongly reads a trigger. `orders` is absent from the verb list because
# "Big orders should go to a manager" (u02) is a plural noun, not a verb.
_ACTOR_EVENT_RE = re.compile(
    r"^\s*(?:a|an|the|every|each)?\s*[\w'’-]+(?:\s+[\w'’-]+){0,3}?\s+"
    r"(?:submits|requests|applies|asks|files|raises|sends|uploads|creates|opens|reports|places"
    r"|arrives|returns|signs\s+up|fills\s+(?:in|out)|completes|builds|runs|starts|joins|registers"
    r"|calls|emails|lodges|initiates|triggers|comes\s+in|checks\s+in|hands\s+in)\b",
    re.IGNORECASE,
)

# What starts a process, cast wide on purpose -- this decides whether
# SPEC-NO-TRIGGER fires, so a miss here is a false accusation against the user.
# Three shapes cover the corpus: an explicit temporal clause, a schedule, and the
# commonest English form for stating a trigger, an actor performing an initiating
# act in the opening clause ("An employee submits an expense claim").
_TRIGGER_LANGUAGE_RE = re.compile(
    r"\b(?:when(?:ever)?|once|each\s+time|every\s+time|as\s+soon\s+as|upon|on\s+receipt"
    r"|on\s+arrival|on\s+submission|is\s+triggered|starts?\s+when|after\s+(?:a|an|the)\s+\w+\s+(?:is|has))\b"
    r"|\b(?:every|each)\s+(?:day|morning|evening|night|hour|week|month|quarter|monday|tuesday"
    r"|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\bon\s+the\s+(?:first|second|third|fourth|last)\s+\w+\b"
    r"|\b(?:nightly|daily|hourly|weekly|monthly|quarterly)\b"
    r"|\bincoming\b"
    r"|\b(?:runs|happens|takes\s+place|kicks\s+off)\s+(?:on|every|at|when)\b"
    r"|\b(?:days?|weeks?|hours?|minutes?)\s+(?:before|after)\b",
    re.IGNORECASE,
)

# A *technical* failure, as opposed to a business rejection. The distinction is
# what four corpus cases turn on: "reject the claim if the receipts do not
# validate" is a rule the process implements, not a failure path -- the receipts
# validating is the process working. "If the credit bureau is unreachable" is a
# failure path. Only the second answers "what happens when this breaks".
_TECHNICAL_FAILURE_RE = re.compile(
    r"\b(?:fails?|failed|failing|failure|errors?\s+out|an\s+error|times?\s+out|timed\s+out|timeout"
    r"|unreachable|unavailable|is\s+down|goes\s+down|does\s+not\s+respond|cannot\s+(?:connect|reach)"
    r"|bounces?|is\s+wrong|provider\s+rejects?|api\s+rejects?)\b",
    re.IGNORECASE,
)
# A recovery action. Either half is enough: naming the failure or naming the
# remedy both count as having thought about it.
_RECOVERY_RE = re.compile(
    r"\b(?:park\w*|roll(?:s|ing)?\s+(?:it|that|them)?\s*back|rolled\s+back|raise\s+a\s+ticket"
    r"|escalat\w+|retr(?:y|ies|ying)|re-?try|come\s+back\s+to\s+them|exceptions?\s+list"
    r"|contact\s+the\s+service\s+desk|instead\s+of\s+failing|rather\s+than\s+stopping"
    r"|compensat\w+|manual\s+review\s+queue)\b"
    # "alert" only as a verb taking an object. c23 opens "when monitoring raises
    # an alert" -- the noun is the thing being processed, not a remedy, and
    # matching it read the whole prompt as having a failure path.
    r"|\balerts?\s+(?:the|them|us|it|finance|ops|support|on-?call)\b",
    re.IGNORECASE,
)
# Anything that changes the world. Read from the prompt rather than from
# `spec.steps`, so a step the extractor's verb lexicon missed still counts.
_SIDE_EFFECT_RE = re.compile(
    r"\b(?:pay|pays|paid|send|sends|sent|email|emails|notif\w+|creat\w+|updat\w+|delet\w+|writ\w+"
    r"|post|posts|publish\w*|issue[sd]?|ship\w*|grant\w*|revok\w*|reset\w*|approv\w+|reject\w+"
    r"|declin\w+|book\w*|schedul\w+|store[sd]?|file[sd]?|log\w*|raise[sd]?|assign\w*|put|puts"
    r"|reimburs\w+|settl\w+|charg\w+|refund\w*|provision\w*|enrol\w*|sign\w*[- ]off|goes\s+out"
    # c29's vocabulary. `check` is deliberately excluded throughout: u07 only ever
    # checks, and treating a read as a side effect would report a missing failure
    # path for a process that cannot fail destructively.
    r"|text|texts|mark|marks|releas\w+|cancel\w*|confirm\w*|offer[sd]?|rings?|remind\w*"
    r"|archiv\w+|clos\w+|patch\w*|snapshot\w*|pages?|paging|rout\w+)\b",
    re.IGNORECASE,
)

# An indefinite or collective actor. A human task that names no role cannot be
# assigned, and its rejection path is undefined.
# `the department` is deliberately absent: c27's "book the spend against the
# department budget" is a cost centre, not an actor, and matching it accused a
# prompt that names its approvers (Brand, the CMO) of naming nobody.
_VAGUE_ACTOR_RE = re.compile(
    r"\b(?:someone|somebody|anyone|anybody|a\s+person|the\s+team|the\s+relevant\s+(?:person|people|team)"
    r"|the\s+right\s+(?:person|people)|the\s+appropriate\s+(?:person|people|team)"
    r"|whoever|the\s+business)\b",
    re.IGNORECASE,
)
# Bare `management` was in the list above and matched inside "the document
# management system" (c18) -- a storage integration read as an unnamed approver.
# A word that common needs its own anchored form or none at all.
_HUMAN_ACTION_RE = re.compile(
    r"\bsigns?\b[^.;]{0,20}?\boff\b"          # "sign this off", "signs the contract off"
    r"|\bsign(?:s|ed|ing)?[- ]off\b"
    r"|\b(?:approv\w+|authoris\w+|authoriz\w+|review\w*)\b"
    r"|\blet\b[^.;]{0,20}?\bknow\b"           # "let the team know"
    r"|\blook\w*\s+(?:at|over)\b|\bdecid\w+\b",
    re.IGNORECASE,
)
# A named role satisfies the actor requirement even in an otherwise vague prompt.
_NAMED_ROLE_RE = re.compile(
    r"\b(?:manager|supervisor|director|counsel|lawyer|editor|clinician|doctor|nurse|engineer"
    r"|analyst|accountant|controller|officer|admin(?:istrator)?|owner|lead|head\s+of"
    r"|on-?call|duty\s+\w+|reviewer|approver|underwriter|recruiter|agent|specialist)\b",
    re.IGNORECASE,
)

# A system written to but never named. "Put it in the system" yields no asset
# reference, so no MockDefinition and no asset_ref-keyed TaskStub can be derived
# and P3's WireMock has nothing to seed -- this is what blocks D9.
#
# Two deliberate narrowings, each paid for by a corpus false positive:
# * the phrase must be the *destination of a write* ("in the system"), not any
#   mention. c22 says "requests access to a system" -- the subject matter, not an
#   integration the workflow calls.
# * `application` and `app` are out of the noun list entirely. "Applications for
#   25000 or less" (c15) is a loan application; the word is too polysemous to
#   carry an integration finding.
_UNNAMED_SYSTEM_RE = re.compile(
    r"\b(?:in|into|on|to)\s+(?:the|our|their)\s+(?:system|platform|tool|software|backend|database)\b",
    re.IGNORECASE,
)

# Repetition with no stated end. "Until X" is an exit *condition*, not a bound:
# nothing says how many attempts or how long before it gives up, so no terminal
# state is guaranteed and a test case can hang rather than fail.
# A negated loop is not a loop. c24's "do not let them keep guessing" is the
# prompt *closing* an unbounded retry, and reading it as opening one inverted the
# finding entirely.
_NEGATED_LOOP_RE = re.compile(r"\b(?:do\s+not|don't|never|without)\s+(?:\w+\s+){0,3}?keep\s+\w+ing", re.IGNORECASE)
_LOOP_RE = re.compile(
    r"\b(?:keep\s+\w+ing|repeat\w*|again\s+and\s+again|over\s+and\s+over|re-?submit\w*"
    r"|that\s+cycle|the\s+cycle|loops?\s+(?:back|until)|until\s+(?:it|they|he|she|someone|somebody|counsel|the)\b"
    r"|chase\w*\s+(?:them|it)|poll\w*)\b",
    re.IGNORECASE,
)
# Any of these means the loop *is* bounded and the diagnostic must not fire.
_LOOP_BOUND_RE = re.compile(
    r"\b(?:up\s+to\s+\d+|at\s+most\s+\d+|no\s+more\s+than\s+\d+|\d+\s*(?:times|attempts|retries|tries)"
    r"|max(?:imum)?\s+(?:of\s+)?\d+|give\s+up\s+after|time\s?out|times\s+out|after\s+\d+\s*\w+\s+(?:give|stop|escalat))\b",
    re.IGNORECASE,
)

# A *container* of items processed inside one process instance. The container
# noun is load-bearing: "every ticket gets a tracking record" (c09) describes what
# the process does per instance and is not a batch at all, while "read the
# spreadsheet and create a record for every row" (u04) is an unbounded fan-out
# inside a single run. Firing on the bare "every <noun>" shape cost nine false
# positives -- almost every prompt in the corpus contains it.
_COLLECTION_RE = re.compile(
    r"\bthe\s+(?:spreadsheet|csv|batch|export|feed)\b"
    r"|\b(?:the|a)\s+list\s+of\b"
    r"|\bfor\s+(?:each|every)\s+\w+\s+in\b"
    r"|\b(?:each|every)\s+row\b|\brows?\s+(?:of|in)\b",
    re.IGNORECASE,
)
_VOLUME_RE = re.compile(
    r"\b(?:up\s+to|at\s+most|no\s+more\s+than|never\s+more\s+than|fewer\s+than|less\s+than"
    r"|maximum\s+of|max|typically|around|about|roughly)\s+\d[\d,]*"
    r"|\b\d[\d,]*\s+(?:rows|records|items|lines|invoices|orders|files|entries|tickets|customers|hosts|servers)\b",
    re.IGNORECASE,
)

# A timing expectation with no duration to assert on.
#
# "Immediately", "straight away" and "right away" are deliberately NOT here.
# They are definite instructions -- "reimbursed straight away with no approval"
# (c02) means *this path has no wait in it*, which is checkable. "Quickly" is a
# wish about elapsed time that nobody has quantified. Only the second is an
# unstated SLA, and conflating them cost a false positive on c02.
_BARE_URGENCY_RE = re.compile(
    r"\b(?:quickly|promptly|asap|as\s+soon\s+as\s+possible|in\s+a\s+timely\s+manner"
    r"|without\s+delay|swiftly|urgently|in\s+good\s+time)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"\b\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|business\s+days?|working\s+days?)\b"
    r"|\bwithin\s+(?:the\s+)?\w+\s+(?:seconds?|minutes?|hours?|days?|weeks?)\b"
    r"|\bnext\s+(?:working\s+)?day\b|\bsame\s+day\b|\bby\s+\d{1,2}\s*(?:am|pm)\b",
    re.IGNORECASE,
)

# A universal "no approval needed" claim, and an approval requirement on a subset
# of the same thing. Both halves have to be about the same noun.
_UNIVERSAL_AUTO_RE = re.compile(
    r"\b(?:approve|process|accept|pay|release|publish|ship)\s+(?:all|every)\s+(?P<noun>\w+?)s?\b"
    r"[^.;]{0,60}?\b(?:automatic\w*|without\s+(?:approval|review|sign-?off)|no\s+approval)\b",
    re.IGNORECASE,
)
_SUBSET_APPROVAL_RE = re.compile(
    r"\b(?:every|any|all|each)\s+(?P<noun>\w+?)s?\s+(?:over|above|under|below|exceeding|greater\s+than|more\s+than)"
    r"[^.;]{0,60}?\b(?:sign\w*[- ]off|approv\w+|authoris\w+|authoriz\w+|review\w*)\b",
    re.IGNORECASE,
)


def _norm(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt).strip()


def diagnose(prompt: str, spec: Spec) -> list[Diagnostic]:
    """Every SPEC-* the prompt earns, in registry order.

    Takes the prompt as well as the spec because several of these are properties
    of the *wording* that the Spec deliberately does not preserve: `extract.py`
    drops a qualitative condition rather than inventing a threshold for it, so by
    the time you hold a Spec, "big orders" and "no condition at all" look
    identical. The diagnostic has to see the words.

    Never reads an artifact. Nothing here takes one, the same as `extract()`.
    """
    text = _norm(prompt)
    found = [
        _no_trigger(text, spec),
        _no_error_behaviour(text, spec),
        _ambiguous_condition(text, spec),
        _unbounded_input(text, spec),
        _no_terminal_state(text, spec),
        _unspecified_integration(text, spec),
        _ambiguous_actor(text, spec),
        _contradictory_requirement(text, spec),
        _unstated_sla(text, spec),
        _no_budget(text, spec),
    ]
    return [d for d in found if d is not None]


def _d(code: str, severity: Severity, message: str, fix: str) -> Diagnostic:
    return Diagnostic(code=code, severity=severity, message=message, suggested_fix=fix,
                      element_id=None, locator=None)


# ---------- the rules ----------


def _no_trigger(text: str, spec: Spec) -> Diagnostic | None:
    """Fires only when *no* trigger language appears anywhere in the prompt.

    Not `spec.trigger is None`. `extract._trigger()` is strict by design -- it
    wants a temporal clause opening the first sentence, and refuses a mid-process
    join like c05's "when all three are done" -- so its silence means "no rule
    matched", not "the user never said". Fourteen corpus prompts state their
    trigger in a form it does not match, and reporting those as the user's
    omission is how a diagnostic prefix loses its credibility.
    """
    if spec.trigger is not None:
        return None
    if _TRIGGER_LANGUAGE_RE.search(text):
        return None
    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    if _ACTOR_EVENT_RE.search(first_sentence):
        return None
    return _d(
        "SPEC-NO-TRIGGER", Severity.WARNING,
        "The prompt never says what starts the process. Any start event in the artifact is "
        "the generator's choice, and intent alignment has nothing to check it against.",
        "State the triggering event or schedule, e.g. 'when an invoice arrives by email' or "
        "'every weekday at 6am'.",
    )


def _no_error_behaviour(text: str, spec: Spec) -> Diagnostic | None:
    """Only when there is a side effect to get wrong.

    The gate matters: corpus u07 ("keep checking the status until it's sorted")
    states no failure path either, and is correctly *not* labelled with this code,
    because nothing it does changes the world. Reporting a missing failure path
    for a process that only reads is noise.
    """
    if _TECHNICAL_FAILURE_RE.search(text) or _RECOVERY_RE.search(text):
        return None
    if not _SIDE_EFFECT_RE.search(text):
        return None
    culprit = next((s.description for s in spec.steps if s.side_effecting), "a step that changes state")
    return _d(
        "SPEC-NO-ERROR-BEHAVIOUR", Severity.WARNING,
        f"A side-effecting step ({culprit!r}) has no stated failure behaviour: "
        "no retry, escalation or compensation. Robustness testing has nothing to assert against.",
        "Say what happens when it fails, e.g. 'if the payment API is down, park the invoice "
        "and alert finance'.",
    )


def _ambiguous_condition(text: str, spec: Spec) -> Diagnostic | None:
    """A fuzzy magnitude used as a routing criterion, with no threshold anywhere.

    This is the code that stands between D8 and a tautology (`0008`). Given "big
    orders go to a manager" there is no number to work from, and a generator that
    invents 1000 and emits 999/1000/1001 is testing its own guess while reporting
    confidence about it. Raise this, generate no boundary cases.

    Four ways it declines, all of them real corpus cases:
    * a numeric branch was extracted -- the prompt did give a threshold;
    * the prompt states a numeric threshold in *any* form, matched independently
      of the extractor. "Anything larger goes to an underwriter" (c15) is prose
      referring back to the "25000 or less" in the previous clause, not an
      undefined criterion;
    * the fuzzy word follows a categorisation verb ("flagged urgent"), so it names
      a field the data already carries;
    * the prompt names its levels (P1, Sev2), so the categories are defined even
      though no number appears.
    """
    if spec.branches:
        return None
    if _NUMERIC_THRESHOLD_RE.search(text):
        return None
    if _NAMED_LEVEL_RE.search(text):
        return None
    for word in _FUZZY_MAGNITUDE:
        for match in re.finditer(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            before = text[max(0, match.start() - 40):match.start()]
            if re.search(_CATEGORISED + r"$", before, re.IGNORECASE):
                continue
            return _d(
                "SPEC-AMBIGUOUS-CONDITION", Severity.WARNING,
                f"The routing criterion is qualitative ({word!r}) with no threshold. Boundary "
                "test generation would have to invent the number and would then be testing "
                "its own guess.",
                f"Replace {word!r} with a measurable condition, e.g. 'orders over 10000'.",
            )
    return None


def _unbounded_input(text: str, spec: Spec) -> Diagnostic | None:
    """A named container fanned out per item inside one instance, with no volume.

    **Deliberately does not fire on open-ended repetition.** An unbounded loop
    costs the same thing downstream, and the first version reported it here --
    but three corpus cases (c17, c28, c30) loop without being labelled unbounded,
    because a retry cycle is not a collection. `SPEC-NO-TERMINAL-STATE` is the
    code for those, and it fires on all three. Reporting both would double-count
    one gap and cost this rule its precision; the price is a known miss on u07,
    recorded in the corpus test.
    """
    if any(f.bound is not None for f in spec.inputs):
        return None
    if _VOLUME_RE.search(text):
        return None
    if not _COLLECTION_RE.search(text):
        return None
    return _d(
        "SPEC-UNBOUNDED-INPUT", Severity.WARNING,
        "A collection is processed per item, or a step repeats, with no volume stated. "
        "Per-instance cost is unbounded and Cost cannot gate on it.",
        "State the expected and maximum volume, e.g. 'typically 50 rows, never more than 500'.",
    )


def _no_terminal_state(text: str, spec: Spec) -> Diagnostic | None:
    """Repetition with an exit *condition* but no cap or timeout.

    The distinction the corpus's four cases all turn on: "keep paging until
    someone acknowledges" says when the loop *should* stop, not what happens when
    that never occurs. Nothing guarantees termination, and a test case for it does
    not fail -- it hangs, then reports `error`, which reads on a corpus run as
    "the generated workflow hangs".
    """
    if not _LOOP_RE.search(text):
        return None
    if _LOOP_BOUND_RE.search(text) or _NEGATED_LOOP_RE.search(text):
        return None
    return _d(
        "SPEC-NO-TERMINAL-STATE", Severity.WARNING,
        "A step repeats with no attempt cap, timeout or escalation path, so no terminal "
        "state is guaranteed. A test for it hangs rather than fails.",
        "Add a bound and an escape, e.g. 'retry up to 5 times, then escalate to the duty manager'.",
    )


def _unspecified_integration(text: str, spec: Spec) -> Diagnostic | None:
    """An external system referred to but never named.

    Blocks D9 concretely: no name means no asset reference, so no
    `MockDefinition` and no `asset_ref`-keyed `TaskStub`, and P3's WireMock has
    nothing to seed. If the extractor recognised a real integration from its
    vocabulary, the prompt did name something and this stays quiet.
    """
    if spec.integrations:
        return None
    match = _UNNAMED_SYSTEM_RE.search(text)
    if not match:
        return None
    return _d(
        "SPEC-UNSPECIFIED-INTEGRATION", Severity.WARNING,
        f"An external system is referred to but not named ({match.group(0)!r}), so no asset "
        "reference and no mock can be derived for it.",
        "Name the system and the operation, e.g. 'create a record in Salesforce'.",
    )


def _ambiguous_actor(text: str, spec: Spec) -> Diagnostic | None:
    """A human step whose actor is a pronoun or a collective.

    A named role anywhere in the prompt settles it -- prompts routinely name the
    approver once and then say "they", and reporting on the pronoun would fire on
    most well-specified prompts.
    """
    if _NAMED_ROLE_RE.search(text):
        return None
    if not _HUMAN_ACTION_RE.search(text):
        return None
    match = _VAGUE_ACTOR_RE.search(text)
    if not match:
        return None
    return _d(
        "SPEC-AMBIGUOUS-ACTOR", Severity.WARNING,
        f"A human step names no role ({match.group(0)!r}), so the task cannot be assigned and "
        "any rejection path is unspecified.",
        "Name the role that acts, e.g. 'the finance manager approves', and say what happens "
        "if they reject.",
    )


def _contradictory_requirement(text: str, spec: Spec) -> Diagnostic | None:
    """A universal automatic-approval claim, plus an approval requirement on a
    subset of the same noun.

    **This rule detects one shape, not contradiction in general.** Detecting
    arbitrary contradiction between two sentences is a judgement task, not a
    regex, and pretending otherwise would produce exactly the confident-and-wrong
    finding the rest of this module avoids. The shape it does catch is a real and
    common one -- a blanket "don't slow deals down" instruction next to a specific
    control -- and a generated workflow silently picks one reading of it.
    """
    auto = _UNIVERSAL_AUTO_RE.search(text)
    if not auto:
        return None
    for subset in _SUBSET_APPROVAL_RE.finditer(text):
        if subset.group("noun").lower() == auto.group("noun").lower():
            return _d(
                "SPEC-CONTRADICTORY-REQUIREMENT", Severity.WARNING,
                f"Two statements about {auto.group('noun')!r} cannot both be satisfied: one asks "
                "for it to be automatic, the other requires sign-off for part of the same set. "
                "Any artifact silently picks one reading.",
                "State the precedence explicitly, e.g. 'auto-approve under 10%, everything else "
                "goes to the sales manager'.",
            )
    return None


def _unstated_sla(text: str, spec: Spec) -> Diagnostic | None:
    """A bare urgency adverb with no duration anywhere in the prompt.

    Deliberately narrow. The corpus also labels two cases where urgency is implied
    by *paging an on-call* rather than stated as an adverb, and this rule misses
    both -- see the recall note in the corpus test. Widening it to "paging implies
    an SLA" fired on c30, which the corpus does not label, so the wider rule buys
    two findings and one false positive. Not worth it at `info`.
    """
    if _DURATION_RE.search(text):
        return None
    match = _BARE_URGENCY_RE.search(text)
    if not match:
        return None
    return _d(
        "SPEC-UNSTATED-SLA", Severity.INFO,
        f"A timing expectation is implied ({match.group(0)!r}) without a duration, so it "
        "cannot be asserted on.",
        "Give the deadline as a duration, e.g. 'acknowledged within 15 minutes'.",
    )


def _no_budget(text: str, spec: Spec) -> Diagnostic | None:
    """No per-instance cost ceiling. `info`: Cost still reports a number, it just
    has nothing to gate it against."""
    if spec.budget_per_instance is not None:
        return None
    return _d(
        "SPEC-NO-BUDGET", Severity.INFO,
        "No per-instance cost ceiling was stated, so Cost reports a number with nothing to "
        "gate it against.",
        "State the ceiling, e.g. 'keep it under 50 cents per invoice'.",
    )
