"""Spec x WorkflowAST -> INT-* diagnostics and coverage scores. D6.

**This is the one P2 module that sees the artifact, and that is why it is here
and not under `testgen/`.** Alignment asks "did the generator build what was
asked for?", which is impossible without looking at what it built. Test
generation asks "what would prove it works?", which must never look -- tests
derived from the artifact are tests the artifact passes. The two questions live
in different directories on purpose, `.importlinter` contract 2 enforces the
separation, and the moment this file's reasoning starts leaking into `testgen/`
the execution tier becomes a tautology.

## Deterministic first, judge for the residue only

The charter's trap for this service, verbatim: *"the temptation is to hand the
prompt and the artifact to an LLM and ask 'does this match?'. That produces
unstable, unexplainable scores."* So everything here is a mechanical diff over
two typed structures. Every `INT-*` it emits can name the element it is about and
say what to do, because it knows exactly which comparison failed -- and a
deterministic differ re-run on the same pair gives the same answer, which is the
only way a corpus baseline means anything over time.

What genuinely needs paraphrase-level judgement -- is "notify the vendor" the
same intent as "send settlement confirmation"? -- is left to `judge.py` at D7 and
reported through `judge_agreement`, never as an `INT-*` code.

## The matching problem is the whole problem

Everything downstream depends on deciding which artifact element, if any, is a
given spec step. Get it wrong in one direction and you invent `INT-MISSING-STEP`
for a step that is plainly there under a different name; wrong in the other and
every unmatched step silently disappears and coverage reads 1.0 for an empty
workflow. `_match()` is therefore lexical, conservative and symmetric about its
failure modes, and `tests/unit/intent/test_align.py` tests both directions.

Owner: P2.  Codes: `docs/decisions/0019-int-alignment-code-registry.md` (append-only).
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

from wfeval.core.ast import Element, ElementKind, WorkflowAST
from wfeval.core.diagnostics import Diagnostic, Severity
from wfeval.core.ir import Spec, Step

from .extract import INTEGRATION_VOCABULARY

ALIGNER_VERSION = "d6.1"

# Element kinds that can carry a spec step. Gateways and events are structure,
# not work: a spec step is something the user asked the process to *do*.
_STEP_KINDS = {
    ElementKind.AGENT_TASK,
    ElementKind.SERVICE_TASK,
    ElementKind.USER_TASK,
    ElementKind.DECISION_TASK,
    ElementKind.SUBPROCESS,
}

# What a `kind_hint` expects to find. Used to break ties, never to reject a
# match outright -- a generator legitimately implements "check the balance" as a
# service task or a decision task, and refusing the pairing over that would
# report a missing step that is right there.
_KIND_EXPECTATION: dict[str, set[ElementKind]] = {
    "agent": {ElementKind.AGENT_TASK},
    "service": {ElementKind.SERVICE_TASK, ElementKind.SUBPROCESS},
    "user": {ElementKind.USER_TASK},
    "decision": {ElementKind.DECISION_TASK, ElementKind.GATEWAY_EXCLUSIVE},
}

# Kinds that change the world, for INT-EXTRA-SIDE-EFFECT. An agent task reads and
# reasons; a service task calls something; a user task makes a person act. Only
# the last two are side effects the prompt should have asked for.
_SIDE_EFFECTING_KINDS = {ElementKind.SERVICE_TASK, ElementKind.USER_TASK}

# Words that carry no signal in a match. "The invoice is processed" and
# "processing of an invoice" should score identically.
_STOPWORDS = {
    "a", "an", "the", "to", "of", "for", "in", "on", "at", "by", "with", "and", "or", "is",
    "are", "be", "it", "its", "their", "them", "this", "that", "then", "from", "into", "as",
    "if", "when", "otherwise", "either", "way", "all", "any", "each", "every", "new",
}

# Crude stemming, enough to make "notifies"/"notification"/"notify" one token.
_SUFFIXES = ("ations", "ation", "ing", "ies", "ed", "es", "s")

_MATCH_THRESHOLD = 0.34


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = set()
    for word in words:
        if word in _STOPWORDS or len(word) < 2:
            continue
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                word = word[: -len(suffix)]
                break
        out.add(word)
    return out


def _similarity(a: str, b: str) -> float:
    """Containment, not Jaccard.

    A step description is a sentence and an element name is a label: "Route it to
    a manager for approval" against "Manager approval". Jaccard punishes that gap
    for being a gap, which is exactly wrong -- the short name being *contained in*
    the long description is the strongest possible evidence they are the same
    thing. Dividing by the smaller set says so.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


@dataclass
class Match:
    step_id: str
    element_id: str
    score: float


@dataclass
class Alignment:
    """Everything the diff learned. Diagnostics and scores are both derived from
    this, so the two can never disagree about what was matched."""

    matches: list[Match] = field(default_factory=list)
    unmatched_steps: list[str] = field(default_factory=list)
    unmatched_elements: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)

    def element_for(self, step_id: str) -> str | None:
        return next((m.element_id for m in self.matches if m.step_id == step_id), None)


def align(spec: Spec, ast: WorkflowAST, prompt: str = "") -> Alignment:
    """The deterministic diff. Pure: same spec, AST and prompt give the same answer.

    `prompt` is used in exactly one place -- `_extra_side_effects()` -- and only
    ever to *suppress* a finding, never to create a match or a score. The reason
    is the same lesson `sufficiency.py` learned the hard way: `extract.py` is
    precision-first and finds around three steps per corpus prompt, while the
    reference artifacts have many more tasks than that. An unmatched element
    therefore means "no rule built a step for this", not "the user never asked
    for it" -- and reporting the difference as the generator's invention scored
    83 false extra-side-effects across 35 reference artifacts, artifacts the
    prompts were literally derived from.

    Checking the element's own words against the prompt costs nothing and is not
    circular: the artifact is not allowed to *add* intent, only to fail to
    contradict what the prompt already says.
    """
    out = Alignment()
    steps = list(spec.steps)
    candidates = [e for e in ast.elements if e.kind in _STEP_KINDS]

    out.matches = _match(steps, candidates)
    matched_steps = {m.step_id for m in out.matches}
    matched_elements = {m.element_id for m in out.matches}
    out.unmatched_steps = [s.id for s in steps if s.id not in matched_steps]
    out.unmatched_elements = [e.id for e in candidates if e.id not in matched_elements]

    reach = _reachability(ast)

    out.diagnostics.extend(_missing_steps(spec, out))
    out.diagnostics.extend(_extra_side_effects(candidates, out, prompt))
    out.diagnostics.extend(_order_violations(spec, out, reach))
    out.diagnostics.extend(_conditions_not_expressed(spec, ast))
    out.diagnostics.extend(_no_error_handling(spec, ast, out))
    out.diagnostics.extend(_trigger_mismatch(spec, ast))
    out.diagnostics.extend(_integrations_missing(spec, ast))
    out.diagnostics.extend(_unreachable_intent(spec, ast, out, reach))
    out.scores = _scores(spec, ast, out)
    return out


# ---------- matching ----------


def _match(steps: list[Step], candidates: list[Element]) -> list[Match]:
    """Greedy one-to-one on lexical similarity, best pair first.

    Greedy rather than optimal assignment on purpose: with a threshold this high
    the pairs that matter are unambiguous, and a Hungarian-style global optimum
    would happily pair two mediocre matches to raise a total score -- inventing
    coverage out of two things that are each individually wrong. Taking the best
    pair first and never revisiting keeps every match locally defensible.
    """
    scored: list[tuple[float, str, str]] = []
    for step in steps:
        for element in candidates:
            name = element.name or element.id
            score = _similarity(step.description, name)
            if step.kind_hint and element.kind in _KIND_EXPECTATION.get(step.kind_hint, set()):
                # A kind agreement is corroboration, not a licence: it lifts a
                # borderline pair over the line, it never rescues an unrelated one.
                score += 0.15
            if score >= _MATCH_THRESHOLD:
                scored.append((score, step.id, element.id))

    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_steps: set[str] = set()
    used_elements: set[str] = set()
    matches: list[Match] = []
    for score, step_id, element_id in scored:
        if step_id in used_steps or element_id in used_elements:
            continue
        used_steps.add(step_id)
        used_elements.add(element_id)
        matches.append(Match(step_id=step_id, element_id=element_id, score=round(min(score, 1.0), 3)))
    matches.sort(key=lambda m: m.step_id)
    return matches


def _attachments(ast: WorkflowAST) -> dict[str, list[str]]:
    """Host element id -> the boundary events watching it.

    A boundary event has no incoming `sequenceFlow`. BPMN attaches it to the task
    it watches with `attachedToRef`, which the adapter records in
    `attributes["attached_to_ref"]` (`0021`). Control still reaches it -- that is
    the entire point of an error boundary event -- so for reachability the
    attachment *is* a control-flow edge and has to be walked like one.
    """
    out: dict[str, list[str]] = {}
    for element in ast.elements:
        host = element.attributes.get("attached_to_ref")
        if host:
            out.setdefault(host, []).append(element.id)
    return out


def _reachability(ast: WorkflowAST) -> dict[str, set[str]]:
    """Forward reachability per element. Small graphs; a BFS each is fine and
    stays obviously correct, which matters more here than the asymptotics.

    Walks sequence flows *and* boundary attachments. Flows alone strand every
    error handler in the corpus: the boundary event has no incoming flow, so it
    is unreachable from the start event and so is the whole chain behind it.
    """
    attached = _attachments(ast)

    def successors(eid: str) -> list[str]:
        return ast.successors(eid) + attached.get(eid, [])

    out: dict[str, set[str]] = {}
    for element in ast.elements:
        seen: set[str] = set()
        queue = deque(successors(element.id))
        while queue:
            nxt = queue.popleft()
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.extend(successors(nxt))
        out[element.id] = seen
    return out


# ---------- the rules ----------


def _d(code: str, message: str, fix: str, element_id: str | None = None) -> Diagnostic:
    # Every INT code is a warning by construction -- IntentReport has no `gates`
    # field, so nothing here can block anything. See `0019`.
    return Diagnostic(code=code, severity=Severity.WARNING, message=message,
                      suggested_fix=fix, element_id=element_id, locator=None)


def _missing_steps(spec: Spec, out: Alignment) -> list[Diagnostic]:
    found = []
    for step_id in out.unmatched_steps:
        step = next(s for s in spec.steps if s.id == step_id)
        found.append(_d(
            "INT-MISSING-STEP",
            f"The prompt asks for {step.description!r} ({step_id}) but no task in the artifact "
            "corresponds to it.",
            f"Add a task implementing {step.description!r}, or say why the prompt's request is "
            "covered elsewhere.",
        ))
    return found


def _extra_side_effects(candidates: list[Element], out: Alignment, prompt: str) -> list[Diagnostic]:
    """A side effect the prompt does not support anywhere.

    Two filters, and the second is what makes the code trustworthy.

    Only side-effecting kinds: an unmatched *agent* task is usually the generator
    decomposing one asked-for step into two reasoning steps, which is an
    implementation choice, not a change to what the process does to the world.

    Then, before reporting: does the prompt itself contain this element's words?
    `extract.py` finds ~3 steps per prompt and the artifacts have far more tasks,
    so "unmatched" mostly means the extractor was quiet, not that the generator
    invented something. Requiring the prompt to be silent *too* is what took this
    rule from 83 findings across the reference corpus to a number that means
    something.
    """
    prompt_tokens = _tokens(prompt)
    found = []
    for element_id in out.unmatched_elements:
        element = next(e for e in candidates if e.id == element_id)
        if element.kind not in _SIDE_EFFECTING_KINDS:
            continue
        label = element.name or element.id
        element_tokens = _tokens(label)
        if element_tokens and len(element_tokens & prompt_tokens) / len(element_tokens) >= 0.5:
            continue  # the user did ask for this; only the extractor missed it
        found.append(_d(
            "INT-EXTRA-SIDE-EFFECT",
            f"{label!r} ({element.kind.value}) changes state, and nothing in the prompt asks "
            "for it.",
            f"Remove {label!r}, or confirm the prompt should have asked for it.",
            element_id=element.id,
        ))
    return found


def _order_violations(spec: Spec, out: Alignment, reach: dict[str, set[str]]) -> list[Diagnostic]:
    """Reported only when the artifact clearly *reverses* a stated order.

    Three outcomes, and only one is a finding. If the spec says a precedes b and
    the artifact agrees, fine. If the artifact puts them on parallel branches,
    that is a legitimate implementation choice -- the prompt's prose order is
    rarely a hard constraint, and reporting it would fire on every parallel
    gateway in the corpus. Only b strictly reaching a, with a not reaching b, is
    unambiguously the wrong way round.
    """
    found = []
    for step in spec.steps:
        for parent_id in step.depends_on:
            after = out.element_for(step.id)
            before = out.element_for(parent_id)
            if after is None or before is None or after == before:
                continue
            if before in reach.get(after, set()) and after not in reach.get(before, set()):
                found.append(_d(
                    "INT-ORDER-VIOLATION",
                    f"The prompt puts {parent_id} before {step.id}, but in the artifact "
                    f"{after!r} runs before {before!r}.",
                    f"Reorder so {before!r} precedes {after!r}, or make them parallel if the "
                    "order genuinely does not matter.",
                    element_id=after,
                ))
    return found


def _conditions_not_expressed(spec: Spec, ast: WorkflowAST) -> list[Diagnostic]:
    """A stated threshold that no flow can actually route on.

    Checks the *variable*, not the whole expression: a generator writing
    `amount > 10000` or `invoice.amount >= 10001` has expressed the condition,
    while flows labelled "over" and "under" with no `conditionExpression` at all
    have not -- which is the real defect in the shared fixture, and the one the
    committed golden example describes.
    """
    expressions = " ".join(f.condition_expr or "" for f in ast.flows).lower()
    found = []
    for branch in spec.branches:
        if not branch.expression_hint:
            continue
        variable = branch.expression_hint.split()[0]
        if variable and variable.lower() in expressions:
            continue
        gateway = next(
            (e.id for e in ast.elements if e.kind == ElementKind.GATEWAY_EXCLUSIVE), None
        )
        found.append(_d(
            "INT-CONDITION-NOT-EXPRESSED",
            f"The prompt's branch condition {branch.description!r} is not expressed in the "
            f"artifact: no flow carries a condition on {variable!r}, so nothing can route on it.",
            f"Add a condition expression '{branch.expression_hint}' to the outgoing flow, and "
            "mark the other one as the gateway's default.",
            element_id=gateway,
        ))
    return found


def _no_error_handling(spec: Spec, ast: WorkflowAST, out: Alignment) -> list[Diagnostic]:
    """The prompt said what happens on failure; the artifact has no path for it.

    Silent when the prompt never said -- that gap is `SPEC-NO-ERROR-BEHAVIOUR`,
    about the prompt, and reporting the same gap twice under two prefixes would
    double-count one omission in whatever P4 aggregates.
    """
    if spec.error_behaviour is None:
        return []
    has_error_path = any(
        e.kind == ElementKind.END_EVENT and "error" in (e.name or "").lower() for e in ast.elements
    ) or any("error" in (e.attributes.get("boundary", "") or "").lower() for e in ast.elements) or any(
        "error" in " ".join(e.attributes.values()).lower() for e in ast.elements
    )
    if has_error_path:
        return []
    culprit = next((s for s in spec.steps if s.side_effecting), None)
    element_id = out.element_for(culprit.id) if culprit else None
    return [_d(
        "INT-NO-ERROR-HANDLING",
        f"The prompt states failure behaviour ({spec.error_behaviour!r}) but the artifact has no "
        "error path implementing it.",
        "Attach a boundary error event to the side-effecting task and route it to the "
        "escalation the prompt describes.",
        element_id=element_id,
    )]


def _trigger_mismatch(spec: Spec, ast: WorkflowAST) -> list[Diagnostic]:
    """Compares the *kind* of trigger, not its wording.

    A prompt saying "every night at 2am" and an artifact starting on an inbound
    message is a real disagreement about when the process runs. A prompt saying
    "when an invoice arrives" against a message start is agreement, whatever
    words each uses -- so this deliberately does not compare text.
    """
    if spec.trigger is None:
        return []
    starts = [e for e in ast.elements if e.kind == ElementKind.START_EVENT]
    if not starts:
        return []
    wants_schedule = bool(re.search(
        r"\b(?:every|nightly|daily|hourly|weekly|monthly|each\s+(?:day|night|morning)|at\s+\d)\b",
        spec.trigger, re.IGNORECASE,
    ))
    start = starts[0]
    is_timer = start.kind == ElementKind.TIMER or "timer" in " ".join(start.attributes).lower()
    if wants_schedule and not is_timer:
        return [_d(
            "INT-TRIGGER-MISMATCH",
            f"The prompt describes a schedule ({spec.trigger!r}) but the artifact starts on "
            f"{start.name or start.id!r}, which is not a timer.",
            "Replace the start event with a timer start carrying the stated schedule.",
            element_id=start.id,
        )]
    return []


_IDENTIFIER_BREAK_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _artifact_vocabulary(ast: WorkflowAST) -> str:
    """Everything in the artifact that could name an integration, flattened into
    prose so the prompt-side patterns can be run over it.

    `asset_ref`s and platform attributes are identifiers, not sentences --
    `PaymentsApi_Prod`, `stripe-charge-v2`. Splitting camel case and punctuation
    into spaces is what lets a vocabulary pattern written for prose ("payments
    api") match one.
    """
    parts: list[str] = []
    for element in ast.elements:
        parts += [element.name or "", element.asset_ref or "", *element.attributes.values()]
    return re.sub(r"[_\-.]+", " ", _IDENTIFIER_BREAK_RE.sub(" ", " ".join(parts))).lower()


def _invoked(integration: str, haystack: str) -> bool:
    """Two ways to count as invoked, and the vocabulary is the one that matters.

    The literal-token check alone reports a workflow that plainly calls the
    payments API as missing it: the extractor canonicalises "the payment API" to
    `payments_api`, and the artifact names the task "Auto-pay invoice" with a
    "Payment API failed" boundary event -- so `payments`, plural, is not in it.
    Matching `INTEGRATION_VOCABULARY` instead asks the question the extractor
    already answered in the other direction, against the same words.

    The token check is kept underneath rather than replaced, because an artifact
    may name a system the prompt vocabulary does not cover at all (a bare
    `asset_ref` of `hris`). Both are widening: neither can invent a finding.
    """
    pattern = INTEGRATION_VOCABULARY.get(integration)
    if pattern and re.search(pattern, haystack):
        return True
    needles = {integration, integration.replace("_", " "), integration.split("_")[0]}
    return any(n and n in haystack for n in needles)


def _integrations_missing(spec: Spec, ast: WorkflowAST) -> list[Diagnostic]:
    """An integration the prompt named that nothing in the artifact invokes."""
    haystack = _artifact_vocabulary(ast)
    found = []
    for integration in spec.integrations:
        if _invoked(integration, haystack):
            continue
        found.append(_d(
            "INT-INTEGRATION-MISSING",
            f"The prompt names the {integration!r} integration but no task in the artifact "
            "invokes it.",
            f"Add a service task calling {integration!r}, with an asset reference so it can be "
            "stubbed at execution time.",
        ))
    return found


def _unreachable_intent(
    spec: Spec, ast: WorkflowAST, out: Alignment, reach: dict[str, set[str]]
) -> list[Diagnostic]:
    """A step that exists but cannot run.

    Distinct from `INT-MISSING-STEP` and worth its own code: the generator did
    build the thing, so a repair that adds it again is the wrong fix. What is
    wrong is the wiring. P1's structural tier will also see the orphan, but only
    this tier can say *which asked-for step* is the one stranded.
    """
    starts = [e.id for e in ast.elements if e.kind == ElementKind.START_EVENT]
    if not starts:
        return []
    live = set().union(*(reach.get(s, set()) for s in starts)) | set(starts)
    found = []
    for match in out.matches:
        if match.element_id in live:
            continue
        step = next(s for s in spec.steps if s.id == match.step_id)
        found.append(_d(
            "INT-UNREACHABLE-INTENT",
            f"{step.description!r} is in the artifact as {match.element_id!r} but cannot be "
            "reached from the start event, so it never runs.",
            f"Connect {match.element_id!r} into the flow from the start event.",
            element_id=match.element_id,
        ))
    return found


# ---------- scores ----------


def _scores(spec: Spec, ast: WorkflowAST, out: Alignment) -> dict[str, float]:
    """Three numbers, all deterministic, all in 0..1 (`0019`).

    `intent_coverage` is deliberately *not* step coverage. A workflow can contain
    every step the prompt asked for and still be wrong about what the prompt
    meant -- the shared fixture matches all four steps and still cannot route on
    its own threshold. The headline number has to be able to say so, which is why
    it is penalised by the findings that step coverage cannot see.
    """
    total_steps = len(spec.steps)
    step_coverage = len(out.matches) / total_steps if total_steps else 1.0

    ordered_pairs = sum(len(s.depends_on) for s in spec.steps)
    violations = sum(1 for d in out.diagnostics if d.code == "INT-ORDER-VIOLATION")
    order_fidelity = 1.0 if not ordered_pairs else max(0.0, (ordered_pairs - violations) / ordered_pairs)

    # Each unexpressed condition, missing integration, extra side effect or
    # stranded step is one thing the prompt asked for that the artifact does not
    # deliver. Counted against the total of everything asked for, so a big
    # correct workflow is not punished as hard as a small wrong one for the same
    # single defect.
    penalties = sum(
        1 for d in out.diagnostics
        if d.code in {
            "INT-CONDITION-NOT-EXPRESSED", "INT-INTEGRATION-MISSING",
            "INT-EXTRA-SIDE-EFFECT", "INT-UNREACHABLE-INTENT",
            "INT-TRIGGER-MISMATCH", "INT-NO-ERROR-HANDLING",
        }
    )
    asked_for = total_steps + len(spec.branches) + len(spec.integrations) + (1 if spec.trigger else 0)
    penalty_ratio = penalties / asked_for if asked_for else 0.0
    intent_coverage = max(0.0, min(1.0, step_coverage * order_fidelity - penalty_ratio))

    return {
        "intent_coverage": round(intent_coverage, 3),
        "step_coverage": round(step_coverage, 3),
        "order_fidelity": round(order_fidelity, 3),
    }
