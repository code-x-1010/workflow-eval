"""The LLM residue pass for `/v1/spec`: prompt + deterministic draft -> fuller Spec.

D4. `extract.py` fills only what a rule gets right and leaves the rest empty on
purpose; this module is what fills the rest. It is the *only* place in P2 where a
model is asked what the prompt meant, and it is built on one rule:

> **Every value the model proposes carries a verbatim quote from the prompt, and
> a value whose quote is not in the prompt is dropped.**

That is the whole design. An LLM asked to complete a Spec will complete it --
confidently, plausibly, and sometimes from nothing, which is the exact failure
`extract.py`'s precision-over-recall rules exist to avoid. Requiring the model to
point at the words it read turns "did it invent this?" from a judgement call into
a substring test, and the merge below runs that test on every field. A refiner
that hallucinates loses the hallucination rather than the request.

Three further guarantees, all enforced by `merge()` rather than by the prompt:

* **The deterministic draft wins.** The refiner fills `None` and empty; it never
  overwrites a value a rule produced. A rule that was right stays right, and a
  refiner regression cannot silently rewrite `budget_per_instance`.
* **It never sees an artifact.** `refine(prompt, draft)` has no parameter for
  one, the same way `extract(prompt)` doesn't. Leg 3 of the anti-circularity
  guarantee (docs/agents/P2-intent-testgen.md) covers this file too.
* **What is dropped is recorded**, not swallowed. `/v1/spec`'s response shape is
  frozen and has nowhere to put it, so it goes to the log -- but a silent drop
  during a corpus run is indistinguishable from a refiner that never ran.

The transport is injected. Prompt construction, response validation and the
merge -- everything with a decision in it -- are pure functions of strings and
run in tests with no network and no API key. See `AnthropicTransport` for the
one part that needs either.

Owner: P2.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from wfeval.core.ir import BranchCondition, DataField, Spec, Step

log = logging.getLogger(__name__)

# Bump when the prompt, the schema or the merge rules change shape. This rides in
# the disk cache key: a cache keyed on the prompt alone keeps serving specs from
# a refiner you have since changed, and you debug the old output for an hour.
REFINER_VERSION = "d4.1"

# Anthropic's current flagship. Pinned rather than read from the environment so a
# cached spec is always attributable to a known model + prompt + rules triple.
DEFAULT_MODEL = "claude-opus-5"

# An evidence quote shorter than this matches by accident -- "a" is a substring of
# nearly every prompt, so accepting it would make the grounding check decorative.
MIN_EVIDENCE_CHARS = 4

# What `outputs` may be typed as. Open-ended types are how "a string called
# `the_thing`" gets into P4's cost model; these are the ones already in use.
_FIELD_TYPES = ["string", "decimal", "integer", "boolean", "array", "object"]
_KIND_HINTS = ["agent", "service", "user", "decision"]


class Transport(Protocol):
    """One model call. The only part of this module that touches the network.

    Returns the model's response as a JSON string. Implementations do not parse,
    validate or interpret it -- that is `merge()`'s job, and keeping it out of the
    transport is what lets the whole policy be tested with a fake.
    """

    name: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str: ...


class VersionedRefiner(Protocol):
    """A `Refiner` (see extract.py) that can also identify itself to the cache."""

    name: str
    version: str

    def refine(self, prompt: str, draft: Spec) -> Spec: ...


def cache_version(extractor_version: str, refiner: VersionedRefiner | None) -> str:
    """The disk cache's version component: whatever produced the spec.

    Both halves matter. Turning the refiner on must not serve back the specs
    extracted without it, and neither must changing which refiner is wired.
    """
    if refiner is None:
        return extractor_version
    return f"{extractor_version}+{refiner.name}.{refiner.version}"


# ---------- the proposal: what the model is allowed to answer ----------

_EVIDENCE = {
    "type": "string",
    "description": "Words copied exactly from the prompt that state this. Not a paraphrase.",
}


def residue_schema() -> dict[str, Any]:
    """JSON Schema for the model's reply, used as a structured-output constraint.

    The schema is the first line of defence and the merge is the second. The
    schema can enforce shape -- these fields, these types, no others -- but it
    cannot enforce that `evidence` is honest, which is why every rule in
    `merge()` re-checks the quote against the prompt itself.
    """
    def grounded(props: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {**props, "evidence": _EVIDENCE},
            "required": [*props, "evidence"],
            "additionalProperties": False,
        }

    return {
        "type": "object",
        "properties": {
            "trigger": {
                "anyOf": [grounded({"value": {"type": "string"}}), {"type": "null"}],
                "description": "What starts the process. Null if the prompt never says.",
            },
            "error_behaviour": {
                "anyOf": [grounded({"value": {"type": "string"}}), {"type": "null"}],
                "description": "What happens when a step fails. Null if the prompt never says.",
            },
            "outputs": {
                "type": "array",
                "description": "What the process produces or leaves behind.",
                "items": grounded(
                    {"name": {"type": "string"}, "type": {"type": "string", "enum": _FIELD_TYPES}}
                ),
            },
            "input_bounds": {
                "type": "array",
                "description": "Volume stated for an input that already exists in the draft.",
                "items": grounded({"name": {"type": "string"}, "bound": {"type": "integer"}}),
            },
            "branch_probabilities": {
                "type": "array",
                "description": "How often a branch is taken, if the prompt says.",
                "items": grounded(
                    {
                        "expression_hint": {"type": "string"},
                        "probability": {"type": "number"},
                    }
                ),
            },
            "steps": {
                "type": "array",
                "description": "Steps the prompt describes that the draft is missing.",
                "items": grounded(
                    {
                        "description": {"type": "string"},
                        "kind_hint": {"type": "string", "enum": _KIND_HINTS},
                        "side_effecting": {"type": "boolean"},
                        "after": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "description": "Id of the draft step this follows. Null if it is first.",
                        },
                    }
                ),
            },
            "step_dependencies": {
                "type": "array",
                "description": "Real ordering, where it differs from the order of the prose.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "depends_on"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "trigger",
            "error_behaviour",
            "outputs",
            "input_bounds",
            "branch_probabilities",
            "steps",
            "step_dependencies",
        ],
        "additionalProperties": False,
    }


SYSTEM_PROMPT = """\
You read a workflow request written by a user and fill the gaps in a structured \
summary of it that was built by simple text rules.

The rules are good at numbers and literal phrasing and bad at everything else, so \
they deliberately leave fields empty rather than guess. Your job is the residue: \
what the process produces, how often a branch is taken, how many of a thing there \
are, which steps really depend on which, and steps described in a way the rules \
could not match.

Every value you return carries an `evidence` field: the words from the request \
that state it, copied exactly. A value whose evidence is not in the request is \
discarded, so a guess costs you the field and gains nothing. When the request \
does not say, return null or an empty list -- an absent value is a useful signal \
downstream, and an invented one is not.

Two things you never do. You do not correct or restate values the draft already \
has; those came from the request and are not yours to revise. And you never see \
the workflow that was generated from this request, so do not refer to one, name \
its elements, or assume what it contains -- test cases derived from the generated \
workflow are tests it passes by construction.
"""


def user_prompt(prompt: str, draft: Spec) -> str:
    """The request and the draft, labelled. The draft is shown so the model fills
    gaps rather than re-deriving what the rules already found."""
    return (
        "<request>\n"
        f"{prompt.strip()}\n"
        "</request>\n\n"
        "<draft>\n"
        f"{draft.model_dump_json(indent=2)}\n"
        "</draft>\n\n"
        "Fill only what the draft is missing, and quote the request for each value."
    )


# ---------- the merge: the deterministic half, and where the policy lives ----------


@dataclass
class Refinement:
    """The merged spec plus an account of what happened to every proposal."""

    spec: Spec
    applied: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def merge(prompt: str, draft: Spec, proposal: dict[str, Any]) -> Refinement:
    """Apply a proposal to `draft` under the grounding and precedence rules.

    Pure: same prompt, draft and proposal give the same Refinement, which is what
    makes the policy testable without a model. Every `dropped` entry names the
    field and the reason, because "the refiner added nothing" and "the refiner
    added six things and all six were rejected" are very different states.
    """
    haystack = _haystack(prompt)
    out = Refinement(spec=draft.model_copy(deep=True))

    _merge_sentence(out, "trigger", proposal.get("trigger"), haystack)
    _merge_sentence(out, "error_behaviour", proposal.get("error_behaviour"), haystack)
    _merge_outputs(out, proposal.get("outputs"), haystack)
    _merge_input_bounds(out, proposal.get("input_bounds"), haystack)
    _merge_branch_probabilities(out, proposal.get("branch_probabilities"), haystack)
    _merge_steps(out, proposal.get("steps"), haystack)
    _merge_step_dependencies(out, proposal.get("step_dependencies"))

    if out.applied:
        # `source` is a frozen field with exactly the right vocabulary for this:
        # a spec the refiner touched is no longer purely "extracted".
        out.spec = out.spec.model_copy(update={"source": "merged"})
    return out


def _merge_sentence(out: Refinement, name: str, item: Any, haystack: str) -> None:
    """`trigger` / `error_behaviour`: a free-text sentence, filled only if absent.

    Absence is load-bearing here. `_trigger()` returning None is what
    SPEC-NO-TRIGGER keys off at D5, so a refiner that fills it from nothing does
    not just add a wrong value -- it deletes a sufficiency finding about the
    prompt. Hence the quote requirement bites hardest on these two.
    """
    if item is None:
        return
    if getattr(out.spec, name) is not None:
        out.dropped.append(f"{name}: the extractor already found one")
        return
    value = _grounded_str(item, "value", haystack)
    if value is None:
        out.dropped.append(f"{name}: {_why(item, 'value', haystack)}")
        return
    out.spec = out.spec.model_copy(update={name: value})
    out.applied.append(f"{name}={value!r}")


def _merge_outputs(out: Refinement, items: Any, haystack: str) -> None:
    """`outputs` is residue in full: naming the terminal state needs the refiner,
    so the extractor emits []. Filled wholesale, or not at all."""
    if not isinstance(items, list) or not items:
        return
    if out.spec.outputs:
        out.dropped.append("outputs: the draft already has some")
        return
    fields: list[DataField] = []
    for item in items:
        name = _grounded_str(item, "name", haystack)
        type_ = _str(item, "type")
        if name is None or type_ not in _FIELD_TYPES:
            out.dropped.append(f"outputs[{_label(item, 'name')}]: {_why(item, 'name', haystack)}")
            continue
        snake = _snake(name)
        if not snake or any(f.name == snake for f in fields):
            out.dropped.append(f"outputs[{_label(item, 'name')}]: empty or duplicate name")
            continue
        fields.append(DataField(name=snake, type=type_, required=True, bound=None))
    if fields:
        out.spec = out.spec.model_copy(update={"outputs": fields})
        out.applied.append(f"outputs={[f.name for f in fields]}")


def _merge_input_bounds(out: Refinement, items: Any, haystack: str) -> None:
    """A volume on an input the draft already has.

    Only existing inputs, and only where `bound` is None. An unbounded collection
    is SPEC-UNBOUNDED-INPUT at D5 and an unbounded cost at P4, so a bound has to
    come from the prompt -- and a bound on an input the extractor never found is
    a sign the refiner invented the input too.
    """
    if not isinstance(items, list):
        return
    by_name = {f.name: f for f in out.spec.inputs}
    for item in items:
        name = _grounded_str(item, "name", haystack)
        bound = item.get("bound") if isinstance(item, dict) else None
        label = _label(item, "name")
        if name is None:
            out.dropped.append(f"input_bounds[{label}]: {_why(item, 'name', haystack)}")
            continue
        target = by_name.get(_snake(name))
        if target is None:
            out.dropped.append(f"input_bounds[{label}]: no such input in the draft")
            continue
        if target.bound is not None:
            out.dropped.append(f"input_bounds[{label}]: already bounded")
            continue
        if not isinstance(bound, int) or isinstance(bound, bool) or bound <= 0:
            out.dropped.append(f"input_bounds[{label}]: bound is not a positive integer")
            continue
        target.bound = bound
        out.applied.append(f"inputs.{target.name}.bound={bound}")


def _merge_branch_probabilities(out: Refinement, items: Any, haystack: str) -> None:
    """`probability_hint` on a branch, matched by its expression.

    `_branches()` attributes a stated likelihood only when there is exactly one
    branch to attribute it to; with two it declines rather than guess. This is
    that decline's second chance -- the refiner can say which branch the prompt
    meant, but it identifies the branch by an expression the extractor produced,
    so it cannot invent a branch on the way through.
    """
    if not isinstance(items, list):
        return
    for item in items:
        expression = _str(item, "expression_hint")
        probability = item.get("probability") if isinstance(item, dict) else None
        label = _label(item, "expression_hint")
        if _evidence(item, haystack) is None:
            out.dropped.append(f"branch_probabilities[{label}]: {_why(item, None, haystack)}")
            continue
        index = _find_branch(out.spec.branches, expression)
        if index is None:
            out.dropped.append(f"branch_probabilities[{label}]: no such branch in the draft")
            continue
        if out.spec.branches[index].probability_hint is not None:
            out.dropped.append(f"branch_probabilities[{label}]: already has one")
            continue
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            out.dropped.append(f"branch_probabilities[{label}]: probability is not a number")
            continue
        if not 0.0 <= float(probability) <= 1.0:
            out.dropped.append(f"branch_probabilities[{label}]: probability outside 0..1")
            continue
        out.spec.branches[index] = out.spec.branches[index].model_copy(
            update={"probability_hint": float(probability)}
        )
        out.applied.append(f"branches[{index}].probability_hint={float(probability)}")


def _merge_steps(out: Refinement, items: Any, haystack: str) -> None:
    """Steps the rules could not match.

    New ids continue the existing sequence and are never reused, so a
    `depends_on` written against the draft still means what it meant. Position in
    the list follows `after`; ordering that matters lives in `depends_on`, which
    the next rule may rewrite.
    """
    if not isinstance(items, list):
        return
    for item in items:
        description = _grounded_str(item, "description", haystack)
        label = _label(item, "description")
        if description is None:
            out.dropped.append(f"steps[{label}]: {_why(item, 'description', haystack)}")
            continue
        kind = _str(item, "kind_hint")
        if kind not in _KIND_HINTS:
            out.dropped.append(f"steps[{label}]: unknown kind_hint {kind!r}")
            continue
        after = _str(item, "after")
        ids = [s.id for s in out.spec.steps]
        if after is not None and after not in ids:
            out.dropped.append(f"steps[{label}]: `after` names no step in the draft")
            continue
        if any(s.description.lower() == description.lower() for s in out.spec.steps):
            out.dropped.append(f"steps[{label}]: duplicates a step already in the draft")
            continue
        side_effecting = bool(item.get("side_effecting"))
        step = Step(
            id=_next_step_id(ids),
            description=description,
            kind_hint=kind,
            depends_on=[after] if after else [],
            is_deterministic=kind != "agent",
            side_effecting=side_effecting,
        )
        position = ids.index(after) + 1 if after else 0
        out.spec.steps.insert(position, step)
        out.applied.append(f"steps+={step.id}:{description!r}")


def _merge_step_dependencies(out: Refinement, items: Any) -> None:
    """Real ordering, replacing the extractor's prose order.

    The one rule that needs no quote: it proposes no new *content*, only edges
    between steps that already exist, and every edge is checkable against the
    draft directly. What it is checked for instead is a cycle -- a spec whose
    steps depend on each other in a loop has no valid execution order at all, and
    P3 would discover that at run time. All-or-nothing on a cycle, because a
    partially applied rewiring is an ordering nobody proposed.
    """
    if not isinstance(items, list) or not items:
        return
    known = {s.id for s in out.spec.steps}
    edges = {s.id: list(s.depends_on) for s in out.spec.steps}
    staged: dict[str, list[str]] = {}
    for item in items:
        step_id = _str(item, "id")
        depends_on = item.get("depends_on") if isinstance(item, dict) else None
        label = _label(item, "id")
        if step_id is None or step_id not in known:
            out.dropped.append(f"step_dependencies[{label}]: no such step")
            continue
        if not isinstance(depends_on, list) or any(not isinstance(d, str) for d in depends_on):
            out.dropped.append(f"step_dependencies[{label}]: depends_on is not a list of ids")
            continue
        unknown = [d for d in depends_on if d not in known]
        if unknown:
            out.dropped.append(f"step_dependencies[{label}]: unknown ids {unknown}")
            continue
        if step_id in depends_on:
            out.dropped.append(f"step_dependencies[{label}]: depends on itself")
            continue
        staged[step_id] = list(dict.fromkeys(depends_on))

    if not staged:
        return
    candidate = {**edges, **staged}
    if _has_cycle(candidate):
        out.dropped.append(f"step_dependencies: would make the graph cyclic ({sorted(staged)})")
        return
    for step in out.spec.steps:
        if step.id in staged:
            step.depends_on = staged[step.id]
    out.applied.append(f"step_dependencies={sorted(staged)}")


# ---------- grounding helpers ----------


def _haystack(prompt: str) -> str:
    """The prompt in the one form quotes are compared against: whitespace
    collapsed and lowercased, so a quote that differs only in line wrapping or
    capitalisation still counts as pointing at the prompt."""
    return re.sub(r"\s+", " ", prompt).strip().lower()


def _evidence(item: Any, haystack: str) -> str | None:
    """The item's evidence quote if it really appears in the prompt, else None."""
    quote = _str(item, "evidence")
    if quote is None:
        return None
    normalised = _haystack(quote)
    if len(normalised) < MIN_EVIDENCE_CHARS:
        return None
    return normalised if normalised in haystack else None


def _grounded_str(item: Any, key: str, haystack: str) -> str | None:
    value = _str(item, key)
    if value is None or _evidence(item, haystack) is None:
        return None
    return value


def _why(item: Any, key: str | None, haystack: str) -> str:
    """Why a proposal was rejected, in words a handoff note can quote."""
    if key is not None and _str(item, key) is None:
        return f"no {key}"
    quote = _str(item, "evidence")
    if quote is None:
        return "no evidence quote"
    if len(_haystack(quote)) < MIN_EVIDENCE_CHARS:
        return f"evidence quote shorter than {MIN_EVIDENCE_CHARS} characters"
    return f"evidence {quote!r} is not in the prompt"


def _str(item: Any, key: str) -> str | None:
    if not isinstance(item, dict):
        return None
    value = item.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _label(item: Any, key: str) -> str:
    return _str(item, key) or "?"


def _find_branch(branches: list[BranchCondition], expression: str | None) -> int | None:
    if expression is None:
        return None
    wanted = re.sub(r"\s+", " ", expression).strip()
    for index, branch in enumerate(branches):
        if branch.expression_hint and re.sub(r"\s+", " ", branch.expression_hint).strip() == wanted:
            return index
    return None


def _next_step_id(existing: list[str]) -> str:
    taken = set(existing)
    index = len(existing) + 1
    while f"s{index}" in taken:
        index += 1
    return f"s{index}"


def _has_cycle(edges: dict[str, list[str]]) -> bool:
    """Depth-first, iterative. `edges[a] = [b]` reads "a depends on b"."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(edges, WHITE)
    for start in edges:
        if colour[start] != WHITE:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                colour[node] = BLACK
                continue
            if colour[node] == GREY:
                continue
            colour[node] = GREY
            stack.append((node, True))
            for parent in edges.get(node, []):
                if colour.get(parent, BLACK) == GREY:
                    return True
                if colour.get(parent, BLACK) == WHITE:
                    stack.append((parent, False))
    return False


def _snake(fragment: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", fragment.strip().lower()).strip("_")


# ---------- the refiner ----------


class LLMRefiner:
    """A `Refiner` (see extract.py) that asks a model for the residue.

    Everything except `transport.complete` is deterministic, so the whole policy
    is exercised in tests by a fake transport that returns a canned proposal.
    A transport that raises, times out or returns something unparseable yields
    the unrefined draft: `/v1/spec` degrades to the deterministic answer rather
    than 500ing, which is the same trade `cache.py` makes for a corrupt entry.
    """

    def __init__(self, transport: Transport, version: str = REFINER_VERSION) -> None:
        self.transport = transport
        self.name = transport.name
        self.version = version

    def refine(self, prompt: str, draft: Spec) -> Spec:
        return self.refine_verbosely(prompt, draft).spec

    def refine_verbosely(self, prompt: str, draft: Spec) -> Refinement:
        try:
            raw = self.transport.complete(SYSTEM_PROMPT, user_prompt(prompt, draft), residue_schema())
        except Exception as exc:  # noqa: BLE001 -- any transport failure is a non-event
            log.warning("refiner %s failed, serving the deterministic draft: %s", self.name, exc)
            return Refinement(spec=draft, dropped=[f"transport: {exc}"])
        try:
            proposal = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("refiner %s returned unparseable JSON: %s", self.name, exc)
            return Refinement(spec=draft, dropped=[f"response: not JSON ({exc})"])
        if not isinstance(proposal, dict):
            return Refinement(spec=draft, dropped=["response: not a JSON object"])

        result = merge(prompt, draft, proposal)
        if result.dropped:
            # Not an error. The grounding check rejecting a proposal is this
            # module working, and the count is the signal worth watching over a
            # corpus run -- a refiner whose drops climb has drifted.
            log.info("refiner %s dropped %d proposal(s): %s", self.name, len(result.dropped), result.dropped)
        return result


class AnthropicTransport:
    """`Transport` over the Anthropic Messages API.

    The only code here that needs a network and a key, and it is deliberately
    thin: build the request, return the text. The SDK is imported lazily so the
    service starts, `make test` runs and `make contract` passes with neither the
    package nor `ANTHROPIC_API_KEY` present -- which is the state of this repo
    today, and the reason `refiner_from_env()` defaults to off.

    Structured outputs do the parsing work that would otherwise be a regex over
    prose: the response is constrained to `residue_schema()`, so a malformed
    proposal is not a failure mode the merge has to handle.
    """

    name = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._client: Any | None = None

    def _connect(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise RuntimeError(
                    "the anthropic SDK is not installed; add it to pyproject's `intent` extra "
                    "before setting WFEVAL_SPEC_REFINER=llm"
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str:
        response = self._connect().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            # Filling gaps against a quoted source is not a reasoning task, and
            # the residue is small; `low` keeps a 40-case corpus run affordable.
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        return "".join(block.text for block in response.content if block.type == "text")


def refiner_from_env() -> LLMRefiner | None:
    """The refiner `/v1/spec` runs, or None.

    **Off unless asked for.** There is no LLM client and no API key anywhere in
    this repo (checked again on 2026-08-05), so a refiner that defaulted to on
    would turn every real-mode request into a failed call and a warning line.
    `WFEVAL_SPEC_REFINER=llm` opts in; the deterministic extractor is what runs
    otherwise, and it is enough to keep D5 moving.
    """
    choice = os.environ.get("WFEVAL_SPEC_REFINER", "off").strip().lower()
    if choice in {"", "off", "none", "0"}:
        return None
    if choice in {"llm", "anthropic"}:
        model = os.environ.get("WFEVAL_SPEC_REFINER_MODEL", DEFAULT_MODEL)
        return LLMRefiner(AnthropicTransport(model=model))
    log.warning("unknown WFEVAL_SPEC_REFINER=%r, running without a refiner", choice)
    return None
