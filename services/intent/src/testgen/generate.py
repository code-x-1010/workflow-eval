"""Spec -> TestCases. Happy, boundary, adversarial. D8.

## The one thing to know before reading this

**No case emitted here carries a path assertion or a `human_task_outcomes`
entry, and that is a deliberate, costly choice forced by an unresolved
dependency.**

`Assertion.must_traverse` and `human_task_outcomes` are both documented as
holding *element ids*. An element id exists only in the artifact, and this
package never sees the artifact -- that is the whole anti-circularity guarantee.
Decisions `0005` §4 and `0009` proposed one optional field
(`TestCase.target_match: exact | semantic`) so P2 could put a semantic
description in those fields and have P3 resolve it. Both have been open since D1
and D2 respectively and are unsigned, and `wfeval.core.testcase` has neither
field today.

So at generation time there are exactly three options, and two of them are worse
than the gap:

1. **Emit element ids.** Impossible without seeing the artifact, and seeing it
   makes every test a tautology.
2. **Put descriptions into fields documented as element ids.** This does not fail
   loudly. An unresolvable `human_task_outcomes` key means the human task is
   never answered, so the instance blocks, times out, and reports `error` -- which
   reads on a corpus run as *"the generated workflow hangs"*. A plausible,
   confident, completely wrong result about somebody else's code.
3. **Emit no path assertions at all**, and say so.

This module does (3), the same choice `tc_006` made in the committed golden
example. The cases are real and they run: every one carries invariants, a budget
assertion where the prompt gave a budget, and output assertions where the spec
names outputs. What they cannot yet do is assert *which branch* a boundary value
took. `case.description` names the expected branch in words so that the moment
`target_match` lands, filling `must_traverse` is a small, mechanical change --
and until then nothing here reports a false pass.

## What each kind is for

* **happy** -- one case, the path the prompt describes when nothing goes wrong.
* **boundary** -- three per numeric condition (`boundaries.py`), because the
  off-by-one at a branch condition is the commonest behavioural bug in a
  generated workflow.
* **adversarial** -- null, empty, oversized and type-confused values per input,
  plus an upstream 500 when the prompt stated failure behaviour. These are the
  ones that find the missing error path.

Owner: P2. Imports `wfeval.core.ir` and `wfeval.core.testcase` -- never the AST.
"""
from __future__ import annotations

from typing import Any

from wfeval.core.ir import DataField, Spec
from wfeval.core.testcase import (
    Assertion,
    AssertionType,
    CaseKind,
    MockDefinition,
    TestCase,
)

from .boundaries import all_boundaries, as_number
from .invariants import budget_assertion, invariants_for
from .mocks import failure_mock_for, mocks_for, task_stubs_for

GENERATOR_VERSION = "d8.1"

# A collection with no stated bound still needs *a* size for the oversized case.
# This is not a claim about the real volume -- SPEC-UNBOUNDED-INPUT reports that
# nobody stated one. It is the size at which "unbounded" stops being theoretical.
OVERSIZED_WITHOUT_BOUND = 10_000


def generate(
    spec: Spec, prompt: str = "", kinds: list[CaseKind] | None = None
) -> tuple[list[TestCase], list[MockDefinition]]:
    """The suite for one spec, and the mocks it needs.

    `prompt` is read only for the stated attempt cap (`invariants.py`) -- there is
    no field on `Spec` for one. It is never used to derive a case.
    """
    wanted = set(kinds or [CaseKind.HAPPY, CaseKind.BOUNDARY, CaseKind.ADVERSARIAL])
    shared = invariants_for(spec, prompt) + budget_assertion(spec)
    stubs = task_stubs_for(spec)

    cases: list[TestCase] = []
    if CaseKind.HAPPY in wanted:
        cases.extend(_happy(spec, shared, stubs))
    if CaseKind.BOUNDARY in wanted:
        cases.extend(_boundary(spec, shared, stubs))
    if CaseKind.ADVERSARIAL in wanted:
        cases.extend(_adversarial(spec, shared, stubs))

    for index, case in enumerate(cases, 1):
        case.case_id = f"tc_{index:03d}"

    mocks = mocks_for(spec)
    if CaseKind.ADVERSARIAL in wanted:
        mocks = mocks + failure_mock_for(spec)
    return cases, mocks


# ---------- the three kinds ----------


def _happy(spec: Spec, shared: list[Assertion], stubs: list[Any]) -> list[TestCase]:
    return [TestCase(
        case_id="tc_000",
        kind=CaseKind.HAPPY,
        description=_happy_description(spec),
        input=_nominal_input(spec),
        assertions=shared + _output_assertions(spec),
        human_task_outcomes={},  # never: see the module docstring
        task_stubs=list(stubs),
    )]


def _boundary(spec: Spec, shared: list[Assertion], stubs: list[Any]) -> list[TestCase]:
    """Three cases per numeric condition. A spec with three numeric conditions
    yields nine, which is the charter's "at least 6" with room to spare."""
    cases = []
    base = _nominal_input(spec)
    for boundary in all_boundaries(spec.branches):
        for label, value in boundary.probes:
            cases.append(TestCase(
                case_id="tc_000",
                kind=CaseKind.BOUNDARY,
                description=(
                    f"{boundary.variable} is {label} the stated threshold "
                    f"({boundary.operator} {as_number(boundary.threshold)}): "
                    f"{boundary.variable}={as_number(value)}. Expected to take the "
                    f"{'true' if _is_true_side(boundary.operator, label) else 'false'} "
                    "branch of that condition."
                ),
                input={**base, boundary.variable: as_number(value)},
                assertions=shared + _output_assertions(spec),
                human_task_outcomes={},
                task_stubs=list(stubs),
            ))
    return cases


def _adversarial(spec: Spec, shared: list[Assertion], stubs: list[Any]) -> list[TestCase]:
    """Null, empty, oversized and type-confused, per input field.

    One case per (field, mutation) rather than one case mutating everything at
    once: a suite where every input is simultaneously wrong tells you the
    workflow rejected *something*, not which thing it failed to guard.
    """
    cases = []
    base = _nominal_input(spec)
    for field in spec.inputs:
        for label, value in _mutations(field):
            cases.append(TestCase(
                case_id="tc_000",
                kind=CaseKind.ADVERSARIAL,
                description=f"{field.name} is {label}. The process must fail cleanly, not hang or crash.",
                input={**base, field.name: value},
                # Deliberately NOT the output assertions. With a hostile input
                # the prompt says nothing about what the outputs should be, and
                # asserting the nominal ones would fail every adversarial case
                # for the wrong reason.
                assertions=shared,
                human_task_outcomes={},
                task_stubs=list(stubs),
            ))
    if spec.error_behaviour is not None and spec.integrations:
        cases.append(TestCase(
            case_id="tc_000",
            kind=CaseKind.ADVERSARIAL,
            description=(
                f"The {sorted(set(spec.integrations))[0]!r} integration returns 500. The prompt "
                f"says: {spec.error_behaviour!r}."
            ),
            input=base,
            assertions=shared,
            human_task_outcomes={},
            task_stubs=list(stubs),
        ))
    return cases


# ---------- inputs ----------


def _nominal_input(spec: Spec) -> dict[str, Any]:
    """A plausible value per input field.

    Numeric fields that a branch compares against get a value *between* the
    stated thresholds where one exists, so the happy case does not sit on a
    boundary -- a happy path that happens to land exactly on a threshold is a
    boundary case wearing the wrong label, and it makes the suite's own results
    hard to read.
    """
    values: dict[str, Any] = {}
    thresholds = {b.variable: b for b in all_boundaries(spec.branches)}
    for field in spec.inputs:
        boundary = thresholds.get(field.name)
        if boundary is not None:
            below = as_number(boundary.below - abs(boundary.threshold) / 2 - 1)
            values[field.name] = below
        else:
            values[field.name] = _nominal_for(field)
    return values


def _nominal_for(field: DataField) -> Any:
    match field.type:
        case "decimal" | "number":
            return 42.5
        case "integer":
            return 42
        case "boolean":
            return True
        case "array":
            return [{"id": 1}, {"id": 2}]
        case "object":
            return {"id": 1}
        case _:
            return f"example {field.name}"


def _mutations(field: DataField) -> list[tuple[str, Any]]:
    """The four adversarial shapes the charter names, filtered to the ones that
    are meaningful for this field's type. "Empty" means nothing for a boolean,
    and a case that cannot fail is a case P3 pays to run for no signal."""
    out: list[tuple[str, Any]] = [("null", None)]
    if field.type in {"string", "array", "object"}:
        out.append(("empty", "" if field.type == "string" else ([] if field.type == "array" else {})))
    if field.type == "array":
        size = field.bound + 1 if field.bound else OVERSIZED_WITHOUT_BOUND
        out.append((
            f"oversized ({size} items{', one past the stated bound' if field.bound else ', unbounded'})",
            [{"id": i} for i in range(min(size, 50))] if size <= 50 else {"__repeat__": size, "item": {"id": 1}},
        ))
    if field.type == "string":
        out.append(("oversized (100k characters)", "x" * 100_000))
    if field.type in {"decimal", "integer", "number"}:
        out.append(("type-confused (a string where a number is expected)", "not-a-number"))
        out.append(("negative", -1))
    else:
        out.append(("type-confused (a number where a non-number is expected)", 12345))
    return out


# ---------- assertions and prose ----------


def _output_assertions(spec: Spec) -> list[Assertion]:
    """One per named output. Emitted only when the spec names outputs -- which,
    since `outputs` is refiner residue, means only when a refiner ran or the
    caller supplied a Spec. Asserting on an output nobody named would be P2
    inventing a post-condition."""
    return [
        Assertion(
            type=AssertionType.OUTPUT,
            description=f"{field.name!r} is produced by the run.",
            field=field.name,
        )
        for field in spec.outputs
    ]


def _happy_description(spec: Spec) -> str:
    trigger = spec.trigger or "the process starts"
    steps = ", then ".join(s.description.lower() for s in spec.steps[:4]) or "the described work happens"
    return f"Happy path: {trigger}, then {steps}. Nothing fails and no threshold is crossed."


def _is_true_side(operator: str, label: str) -> bool:
    """Which side of the comparison a probe lands on. Reported in prose only --
    it is what a `must_traverse` would encode if the field existed."""
    if label == "just below":
        return operator in {"<", "<="}
    if label == "just above":
        return operator in {">", ">="}
    return operator in {">=", "<=", "=="}
