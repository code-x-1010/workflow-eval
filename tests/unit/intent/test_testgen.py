"""Test generation: the charter's bar, and the constraint it is generated under.

Two things this file exists to pin.

The charter's measurable bar: **a spec with 3 numeric conditions yields at least
6 boundary cases.** It yields 9 -- three probes per condition.

And the constraint: **no case carries a path assertion or a `human_task_outcomes`
entry**, because both are documented as holding element ids and `testgen/` never
sees an artifact. That is asserted here rather than left as prose, so a future
change that starts emitting them fails loudly instead of producing test cases
that hang somebody else's runner.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from wfeval.core.ir import BranchCondition, DataField, Spec, Step
from wfeval.core.testcase import AssertionType, CaseKind

from services.intent.src.testgen import generate
from services.intent.src.testgen.boundaries import all_boundaries, boundaries_for, step_for
from services.intent.src.testgen.invariants import DEFAULT_MAX_TASK_EXECUTIONS, max_executions_from
from services.intent.src.testgen.mocks import mocks_for, task_stubs_for

PROMPT = (
    "When an invoice arrives by email, extract the vendor and the amount. "
    "If the amount is over 10000, route it to a manager for approval; otherwise pay it "
    "automatically. Keep it under 50 cents per invoice."
)


def spec(**overrides: object) -> Spec:
    base = Spec(
        trigger="an invoice arrives by email",
        steps=[
            Step(id="s1", description="Extract the vendor and the amount", kind_hint="agent",
                 depends_on=[], is_deterministic=False, side_effecting=False),
            Step(id="s2", description="Pay it automatically", kind_hint="service",
                 depends_on=["s1"], is_deterministic=True, side_effecting=True),
        ],
        inputs=[DataField(name="amount", type="decimal", required=True, bound=None)],
        outputs=[],
        branches=[BranchCondition(description="amount over 10000",
                                  expression_hint="amount > 10000", probability_hint=None)],
        error_behaviour=None,
        integrations=["email"],
        budget_per_instance=0.5,
        source="extracted",
    )
    return base.model_copy(update=overrides)  # type: ignore[arg-type]


def three_conditions() -> Spec:
    return spec(
        branches=[
            BranchCondition(description="amount over 10000", expression_hint="amount > 10000"),
            BranchCondition(description="score at least 0.8", expression_hint="score >= 0.8"),
            BranchCondition(description="days fewer than 5", expression_hint="days < 5"),
        ],
        inputs=[
            DataField(name="amount", type="decimal", required=True, bound=None),
            DataField(name="score", type="decimal", required=True, bound=None),
            DataField(name="days", type="integer", required=True, bound=None),
        ],
    )


# ---------- the charter's bar ----------


def test_three_numeric_conditions_yield_at_least_six_boundary_cases() -> None:
    """**The D8 done-when, verbatim.** Nine, in fact: three probes per condition."""
    cases, _ = generate(three_conditions(), PROMPT, [CaseKind.BOUNDARY])
    boundary = [c for c in cases if c.kind == CaseKind.BOUNDARY]
    assert len(boundary) >= 6
    assert len(boundary) == 9


def test_the_probes_are_the_off_by_one_around_the_threshold() -> None:
    """"Over 10000" means 9999 / 10000 / 10001. The middle value is the one that
    finds bugs: `>` and `>=` differ only there, and a generator picks between
    them by guessing what "over" means."""
    cases, _ = generate(spec(), PROMPT, [CaseKind.BOUNDARY])
    values = sorted(c.input["amount"] for c in cases)
    assert values == [9999, 10000, 10001]


def test_the_step_follows_the_notation_of_the_threshold() -> None:
    """A fixed step of 1 around 0.8 gives -0.2/0.8/1.8, which tests nothing about
    a fraction. Writing "10.25" is the user saying the second decimal matters."""
    assert step_for("10000") == Decimal(1)
    assert step_for("0.8") == Decimal("0.1")
    assert step_for("10.25") == Decimal("0.01")

    fractional = boundaries_for(BranchCondition(description="d", expression_hint="score >= 0.8"))
    assert fractional is not None
    assert (fractional.below, fractional.at, fractional.above) == (
        Decimal("0.7"), Decimal("0.8"), Decimal("0.9"),
    )


def test_a_qualitative_condition_yields_no_boundary_cases() -> None:
    """`0008`'s reason for SPEC-AMBIGUOUS-CONDITION: a generator that invents 1000
    and emits 999/1000/1001 is testing its own guess while reporting confidence
    about it. Raise the diagnostic, generate nothing."""
    vague = spec(branches=[BranchCondition(description="big orders", expression_hint=None)])
    cases, _ = generate(vague, PROMPT, [CaseKind.BOUNDARY])
    assert cases == []


def test_repeated_thresholds_are_not_probed_twice() -> None:
    """"Claims from 100 up to 1000" and "anything above 1000" both mention 1000.
    Probing it twice inflates the count without testing anything twice."""
    duplicated = spec(branches=[
        BranchCondition(description="a", expression_hint="amount > 1000"),
        BranchCondition(description="b", expression_hint="amount > 1000"),
    ])
    assert len(all_boundaries(duplicated.branches)) == 1


# ---------- the constraint ----------


def test_no_case_ever_carries_a_path_assertion() -> None:
    """`Assertion.must_traverse` holds element ids and this package never sees an
    artifact. Decisions 0005 §4 and 0009 proposed the field that would let a
    semantic description go here; both are unsigned. Until then, emitting one
    would mean either inventing ids or putting prose in an id field -- and the
    second does not fail loudly, it hangs the instance."""
    cases, _ = generate(three_conditions(), PROMPT)
    assert cases
    for case in cases:
        for assertion in case.assertions:
            assert assertion.type != AssertionType.PATH
            assert assertion.must_traverse is None
            assert assertion.must_not_traverse is None


def test_no_case_ever_carries_a_human_task_outcome() -> None:
    """Same reason: the keys are documented as element ids. An unresolvable key
    is not a failed assertion -- the human task is never answered, the instance
    blocks, times out and reports `error`, which reads on a corpus run as "the
    generated workflow hangs"."""
    cases, _ = generate(three_conditions(), PROMPT)
    for case in cases:
        assert case.human_task_outcomes == {}


def test_task_stubs_are_keyed_by_asset_ref_never_by_element_id() -> None:
    stubs = task_stubs_for(spec())
    assert stubs, "the spec has an agent step, so it should have a stub"
    for stub in stubs:
        assert stub.element_id is None
        assert stub.asset_ref


def test_a_boundary_case_still_says_which_branch_it_targets() -> None:
    """The prose stands in for the assertion we cannot write, so filling
    `must_traverse` the moment `target_match` lands is mechanical."""
    cases, _ = generate(spec(), PROMPT, [CaseKind.BOUNDARY])
    assert all("branch" in c.description for c in cases)
    assert any("true branch" in c.description for c in cases)
    assert any("false branch" in c.description for c in cases)


# ---------- invariants ----------


def test_every_case_carries_the_invariants() -> None:
    cases, _ = generate(three_conditions(), PROMPT)
    for case in cases:
        exprs = [a.expr for a in case.assertions if a.type == AssertionType.INVARIANT]
        assert "terminal_events == 1" in exprs
        assert any(e and e.startswith("max_task_executions") for e in exprs)


def test_a_stated_attempt_cap_is_used_instead_of_the_default() -> None:
    assert max_executions_from("retry up to 5 times, then escalate") == 5
    assert max_executions_from("no cap stated here") == DEFAULT_MAX_TASK_EXECUTIONS


def test_the_pii_invariant_appears_only_when_the_spec_has_such_a_field() -> None:
    """An invariant that can never fail is noise in every report that carries it,
    and P3 pays to evaluate it on every case."""
    without = spec()
    cases, _ = generate(without, PROMPT, [CaseKind.HAPPY])
    assert not any("no_pii" in (a.expr or "") for a in cases[0].assertions)

    with_pii = spec(inputs=[
        DataField(name="amount", type="decimal", required=True, bound=None),
        DataField(name="customer_email", type="string", required=True, bound=None),
    ])
    cases, _ = generate(with_pii, PROMPT, [CaseKind.HAPPY])
    pii = [a for a in cases[0].assertions if "no_pii" in (a.expr or "")]
    assert pii and "customer_email" in pii[0].expr


def test_a_budget_assertion_appears_only_when_the_prompt_gave_a_budget() -> None:
    """Emitting a default ceiling would give P4 a number to gate on that no user
    ever asked for, which is worse than having none."""
    with_budget, _ = generate(spec(), PROMPT, [CaseKind.HAPPY])
    assert any(a.type == AssertionType.BUDGET for a in with_budget[0].assertions)
    without_budget, _ = generate(spec(budget_per_instance=None), PROMPT, [CaseKind.HAPPY])
    assert not any(a.type == AssertionType.BUDGET for a in without_budget[0].assertions)


# ---------- adversarial ----------


def test_adversarial_cases_cover_the_four_shapes_the_charter_names() -> None:
    hostile = spec(inputs=[
        DataField(name="amount", type="decimal", required=True, bound=None),
        DataField(name="line_items", type="array", required=True, bound=20),
        DataField(name="vendor", type="string", required=True, bound=None),
    ])
    cases, _ = generate(hostile, PROMPT, [CaseKind.ADVERSARIAL])
    described = " ".join(c.description for c in cases)
    assert "null" in described
    assert "empty" in described
    assert "oversized" in described
    assert "type-confused" in described


def test_one_field_is_mutated_per_case() -> None:
    """A case where every input is simultaneously wrong tells you the workflow
    rejected *something*, not which thing it failed to guard."""
    hostile = spec(inputs=[
        DataField(name="amount", type="decimal", required=True, bound=None),
        DataField(name="vendor", type="string", required=True, bound=None),
    ])
    nominal, _ = generate(hostile, PROMPT, [CaseKind.HAPPY])
    baseline = nominal[0].input
    cases, _ = generate(hostile, PROMPT, [CaseKind.ADVERSARIAL])
    for case in cases:
        differing = [k for k in baseline if case.input.get(k) != baseline[k]]
        assert len(differing) <= 1, f"{case.description}: mutated {differing}"


def test_an_oversized_array_is_one_past_a_stated_bound() -> None:
    bounded = spec(inputs=[DataField(name="line_items", type="array", required=True, bound=20)])
    cases, _ = generate(bounded, PROMPT, [CaseKind.ADVERSARIAL])
    assert any("21 items" in c.description for c in cases)


def test_adversarial_cases_do_not_assert_the_nominal_outputs() -> None:
    """With a hostile input the prompt says nothing about what the outputs should
    be, and asserting the nominal ones fails every adversarial case for the wrong
    reason."""
    with_outputs = spec(outputs=[DataField(name="payment_id", type="string", required=True, bound=None)])
    cases, _ = generate(with_outputs, PROMPT, [CaseKind.ADVERSARIAL])
    for case in cases:
        assert not any(a.type == AssertionType.OUTPUT for a in case.assertions)


# ---------- happy path ----------


def test_the_happy_case_does_not_sit_on_a_boundary() -> None:
    """A happy path that lands exactly on a threshold is a boundary case wearing
    the wrong label, and it makes the suite's own results hard to read."""
    cases, _ = generate(spec(), PROMPT, [CaseKind.HAPPY])
    assert cases[0].input["amount"] != 10000


def test_kinds_are_honoured() -> None:
    cases, _ = generate(three_conditions(), PROMPT, [CaseKind.HAPPY])
    assert {c.kind for c in cases} == {CaseKind.HAPPY}


def test_case_ids_are_unique_and_sequential() -> None:
    cases, _ = generate(three_conditions(), PROMPT)
    ids = [c.case_id for c in cases]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


# ---------- D9: mocks ----------


def test_one_mock_per_named_integration_fully_specified() -> None:
    """P3's WireMock seeds from this without transformation, so a mock missing a
    host, path, method or body is one P3 has to invent."""
    mocks = mocks_for(spec(integrations=["slack", "payments_api", "email"]))
    assert len(mocks) == 3
    for mock in mocks:
        assert mock.host and "." in mock.host
        assert mock.path.startswith("/")
        assert mock.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert mock.status == 200
        assert mock.response


def test_mocks_are_stable_across_regeneration() -> None:
    """A list that reshuffles turns every regeneration into a diff for P3."""
    first = mocks_for(spec(integrations=["slack", "email", "crm"]))
    second = mocks_for(spec(integrations=["crm", "slack", "email"]))
    assert [m.host for m in first] == [m.host for m in second]


def test_an_unknown_integration_still_gets_a_usable_mock() -> None:
    mocks = mocks_for(spec(integrations=["some_bespoke_system"]))
    assert len(mocks) == 1 and mocks[0].host and mocks[0].path


def test_a_failure_mock_appears_only_when_the_prompt_stated_failure_behaviour() -> None:
    """Without a stated failure behaviour there is nothing to assert about what
    should happen, so a failing mock just produces an unexplained `error`."""
    _, silent = generate(spec(), PROMPT, [CaseKind.ADVERSARIAL])
    assert all(m.status == 200 for m in silent)

    stated = spec(error_behaviour="if the payment API fails, park the invoice")
    _, mocks = generate(stated, PROMPT, [CaseKind.ADVERSARIAL])
    assert any(m.status == 500 for m in mocks)


def test_no_mocks_when_the_prompt_names_no_integration() -> None:
    assert mocks_for(spec(integrations=[])) == []


@pytest.mark.parametrize("kind", list(CaseKind))
def test_generation_never_raises_on_an_empty_spec(kind: CaseKind) -> None:
    """A spec with nothing in it is what an under-specified prompt produces, and
    it must yield an empty or minimal suite rather than an exception -- the
    corpus has ten of them."""
    cases, mocks = generate(Spec(), "", [kind])
    assert isinstance(cases, list) and isinstance(mocks, list)
