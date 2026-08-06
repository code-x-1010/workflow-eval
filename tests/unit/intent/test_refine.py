"""The refiner's merge policy: what survives, and what gets dropped.

Half of these tests are the refiner being *refused*. That is the point of the
module -- a refiner that only ever gets asked for well-formed grounded proposals
has never been shown to reject an invented one, and the grounding check is the
only thing standing between an LLM's confident guess and P4's cost model.

No network, no API key, no `anthropic` package: `merge()` is a pure function and
`LLMRefiner` takes its transport by injection, so every rule below runs offline.
"""
from __future__ import annotations

from typing import Any

import pytest

from services.intent.src import refine
from services.intent.src.extract import extract
from services.intent.src.refine import LLMRefiner, Refinement, cache_version, merge
from wfeval.core.ir import BranchCondition, DataField, Spec, Step

PROMPT = (
    "When an invoice arrives by email, extract the vendor and the amount. "
    "If the amount is over 10000, send it to a manager for approval. "
    "Otherwise pay it automatically. There are never more than 200 invoices a day. "
    "Roughly 10% need approval. File the receipt in the accounting system when done."
)

EMPTY: dict[str, Any] = {
    "trigger": None,
    "error_behaviour": None,
    "outputs": [],
    "input_bounds": [],
    "branch_probabilities": [],
    "steps": [],
    "step_dependencies": [],
}


def proposal(**overrides: Any) -> dict[str, Any]:
    return {**EMPTY, **overrides}


def draft() -> Spec:
    """A deterministic draft with the shapes the rules produce: some fields
    found, some left empty. Built by hand rather than by `extract()` so a change
    to the extractor's recall cannot silently change what these tests assert."""
    return Spec(
        trigger=None,
        steps=[
            Step(id="s1", description="Extract the vendor and the amount", kind_hint="agent",
                 depends_on=[], is_deterministic=False, side_effecting=False),
            Step(id="s2", description="Send it to a manager for approval", kind_hint="user",
                 depends_on=["s1"], is_deterministic=True, side_effecting=True),
        ],
        inputs=[DataField(name="amount", type="decimal", required=True, bound=None)],
        outputs=[],
        branches=[
            BranchCondition(description="amount is over 10000", expression_hint="amount > 10000",
                            probability_hint=None),
        ],
        error_behaviour=None,
        integrations=["email"],
        budget_per_instance=None,
        source="extracted",
    )


# ---------- grounding: the rule the whole module rests on ----------


def test_a_grounded_value_is_applied() -> None:
    out = merge(PROMPT, draft(), proposal(
        trigger={"value": "an invoice arrives by email", "evidence": "When an invoice arrives by email"},
    ))
    assert out.spec.trigger == "an invoice arrives by email"
    assert out.dropped == []


def test_a_value_whose_quote_is_not_in_the_prompt_is_dropped() -> None:
    """The failure this module exists for. The trigger is plausible, well-formed
    and completely invented; the quote is what gives it away."""
    out = merge(PROMPT, draft(), proposal(
        trigger={"value": "the nightly batch runs", "evidence": "every night at 2am the batch runs"},
    ))
    assert out.spec.trigger is None
    assert out.applied == []
    assert "is not in the prompt" in out.dropped[0]


def test_a_missing_quote_is_dropped() -> None:
    out = merge(PROMPT, draft(), proposal(trigger={"value": "an invoice arrives"}))
    assert out.spec.trigger is None
    assert "no evidence quote" in out.dropped[0]


def test_a_quote_too_short_to_mean_anything_is_dropped() -> None:
    """"an" is a substring of this prompt and of almost every other one. Without
    a floor the grounding check passes on any value at all."""
    out = merge(PROMPT, draft(), proposal(trigger={"value": "an invoice arrives", "evidence": "an"}))
    assert out.spec.trigger is None
    assert "shorter than" in out.dropped[0]


def test_quoting_is_insensitive_to_case_and_line_wrapping() -> None:
    """A model copying from a wrapped prompt should not lose the field to a
    newline. Only the words have to match."""
    out = merge(PROMPT, draft(), proposal(
        trigger={"value": "an invoice arrives by email", "evidence": "WHEN AN INVOICE\n  ARRIVES BY EMAIL"},
    ))
    assert out.spec.trigger == "an invoice arrives by email"


# ---------- precedence: the deterministic draft wins ----------


def test_the_refiner_cannot_overwrite_a_value_a_rule_found() -> None:
    """Even perfectly grounded. The rules are precision-first and their output is
    not the refiner's to revise -- otherwise a refiner regression rewrites values
    that were right, and nothing downstream can tell."""
    started = draft().model_copy(update={"trigger": "an invoice arrives by email"})
    out = merge(PROMPT, started, proposal(
        trigger={"value": "an invoice is received", "evidence": "When an invoice arrives by email"},
    ))
    assert out.spec.trigger == "an invoice arrives by email"
    assert out.dropped == ["trigger: the extractor already found one"]


def test_a_populated_outputs_list_is_not_replaced() -> None:
    started = draft().model_copy(
        update={"outputs": [DataField(name="receipt", type="string", required=True, bound=None)]}
    )
    out = merge(PROMPT, started, proposal(
        outputs=[{"name": "payment", "type": "string", "evidence": "pay it automatically"}],
    ))
    assert [f.name for f in out.spec.outputs] == ["receipt"]
    assert out.dropped == ["outputs: the draft already has some"]


def test_source_becomes_merged_only_when_something_was_applied() -> None:
    """`source` is how a consumer tells a spec the refiner touched from one it
    didn't. A refiner whose every proposal was rejected must not claim credit."""
    untouched = merge(PROMPT, draft(), proposal(
        trigger={"value": "invented", "evidence": "no such words here"},
    ))
    assert untouched.spec.source == "extracted"

    touched = merge(PROMPT, draft(), proposal(
        trigger={"value": "an invoice arrives by email", "evidence": "an invoice arrives by email"},
    ))
    assert touched.spec.source == "merged"


# ---------- outputs ----------


def test_outputs_are_filled_and_snake_cased() -> None:
    out = merge(PROMPT, draft(), proposal(outputs=[
        {"name": "Filed receipt", "type": "string", "evidence": "File the receipt in the accounting system"},
    ]))
    assert out.spec.outputs == [DataField(name="filed_receipt", type="string", required=True, bound=None)]


def test_an_ungrounded_output_is_dropped_and_the_grounded_ones_survive() -> None:
    """Per-item, not all-or-nothing: one bad field should not cost the rest."""
    out = merge(PROMPT, draft(), proposal(outputs=[
        {"name": "receipt", "type": "string", "evidence": "File the receipt"},
        {"name": "audit_trail", "type": "array", "evidence": "write a full audit trail"},
    ]))
    assert [f.name for f in out.spec.outputs] == ["receipt"]
    assert len(out.dropped) == 1


def test_an_unknown_output_type_is_dropped() -> None:
    out = merge(PROMPT, draft(), proposal(outputs=[
        {"name": "receipt", "type": "InvoiceRecord", "evidence": "File the receipt"},
    ]))
    assert out.spec.outputs == []


# ---------- input bounds ----------


def test_a_bound_is_applied_to_an_existing_input() -> None:
    out = merge(PROMPT, draft(), proposal(input_bounds=[
        {"name": "amount", "bound": 200, "evidence": "never more than 200 invoices a day"},
    ]))
    assert out.spec.inputs[0].bound == 200


def test_a_bound_on_an_input_the_extractor_never_found_is_dropped() -> None:
    """A bound on an unknown input usually means the refiner invented the input
    too -- and SPEC-UNBOUNDED-INPUT at D5 reads an absent bound, so a wrong one
    hides a finding instead of adding a fact."""
    out = merge(PROMPT, draft(), proposal(input_bounds=[
        {"name": "line_items", "bound": 50, "evidence": "never more than 200 invoices a day"},
    ]))
    assert all(f.bound is None for f in out.spec.inputs)
    assert "no such input in the draft" in out.dropped[0]


def test_a_bound_that_is_not_a_positive_integer_is_dropped() -> None:
    out = merge(PROMPT, draft(), proposal(input_bounds=[
        {"name": "amount", "bound": 0, "evidence": "never more than 200 invoices a day"},
    ]))
    assert out.spec.inputs[0].bound is None


def test_an_already_bounded_input_is_left_alone() -> None:
    started = draft()
    started.inputs[0].bound = 10
    out = merge(PROMPT, started, proposal(input_bounds=[
        {"name": "amount", "bound": 200, "evidence": "never more than 200 invoices a day"},
    ]))
    assert out.spec.inputs[0].bound == 10


# ---------- branch probabilities ----------


def test_a_probability_is_attached_to_the_branch_it_names() -> None:
    """`_branches()` declines to attribute a stated likelihood when more than one
    branch could own it. This is that decline's second chance."""
    out = merge(PROMPT, draft(), proposal(branch_probabilities=[
        {"expression_hint": "amount > 10000", "probability": 0.1, "evidence": "Roughly 10% need approval"},
    ]))
    assert out.spec.branches[0].probability_hint == 0.1


def test_a_probability_for_a_branch_the_draft_does_not_have_is_dropped() -> None:
    """The branch is identified by an expression the *extractor* produced, so the
    refiner cannot smuggle in a branch nobody derived from the prompt."""
    out = merge(PROMPT, draft(), proposal(branch_probabilities=[
        {"expression_hint": "risk_score > 0.8", "probability": 0.2, "evidence": "Roughly 10% need approval"},
    ]))
    assert out.spec.branches[0].probability_hint is None
    assert "no such branch" in out.dropped[0]


@pytest.mark.parametrize("probability", [1.5, -0.1, "10%", True])
def test_a_probability_outside_zero_to_one_is_dropped(probability: Any) -> None:
    out = merge(PROMPT, draft(), proposal(branch_probabilities=[
        {"expression_hint": "amount > 10000", "probability": probability,
         "evidence": "Roughly 10% need approval"},
    ]))
    assert out.spec.branches[0].probability_hint is None


# ---------- new steps ----------


def test_a_grounded_step_is_inserted_after_the_step_it_names() -> None:
    out = merge(PROMPT, draft(), proposal(steps=[
        {"description": "Pay the invoice automatically", "kind_hint": "service", "side_effecting": True,
         "after": "s2", "evidence": "Otherwise pay it automatically"},
    ]))
    assert [s.id for s in out.spec.steps] == ["s1", "s2", "s3"]
    assert out.spec.steps[2].depends_on == ["s2"]
    assert out.spec.steps[2].is_deterministic is True


def test_a_new_step_may_be_inserted_at_the_front() -> None:
    out = merge(PROMPT, draft(), proposal(steps=[
        {"description": "Receive the invoice", "kind_hint": "service", "side_effecting": False,
         "after": None, "evidence": "an invoice arrives by email"},
    ]))
    assert [s.id for s in out.spec.steps] == ["s3", "s1", "s2"]
    assert out.spec.steps[0].depends_on == []


def test_a_step_whose_after_names_nothing_is_dropped() -> None:
    out = merge(PROMPT, draft(), proposal(steps=[
        {"description": "Pay the invoice", "kind_hint": "service", "side_effecting": True,
         "after": "s99", "evidence": "Otherwise pay it automatically"},
    ]))
    assert len(out.spec.steps) == 2
    assert "names no step in the draft" in out.dropped[0]


def test_a_step_that_restates_one_the_rules_already_found_is_dropped() -> None:
    out = merge(PROMPT, draft(), proposal(steps=[
        {"description": "send it to a manager for approval", "kind_hint": "user", "side_effecting": True,
         "after": "s1", "evidence": "send it to a manager for approval"},
    ]))
    assert len(out.spec.steps) == 2
    assert "duplicates a step" in out.dropped[0]


def test_a_step_with_an_unknown_kind_hint_is_dropped() -> None:
    out = merge(PROMPT, draft(), proposal(steps=[
        {"description": "Pay the invoice", "kind_hint": "robot", "side_effecting": True,
         "after": "s2", "evidence": "Otherwise pay it automatically"},
    ]))
    assert len(out.spec.steps) == 2


def test_new_step_ids_never_reuse_one_the_draft_already_spent() -> None:
    """A reused id silently redirects every `depends_on` written against the
    draft, which is a reordered workflow nobody proposed."""
    started = draft()
    started.steps.append(Step(id="s3", description="File the receipt", kind_hint="service",
                              depends_on=["s2"], is_deterministic=True, side_effecting=True))
    started.steps.pop(0)  # ids s2, s3 remain -- a naive "s{len+1}" would collide
    out = merge(PROMPT, started, proposal(steps=[
        {"description": "Pay the invoice automatically", "kind_hint": "service", "side_effecting": True,
         "after": "s3", "evidence": "Otherwise pay it automatically"},
    ]))
    ids = [s.id for s in out.spec.steps]
    assert len(ids) == len(set(ids))
    assert "s4" in ids


# ---------- step dependencies ----------


def test_dependencies_replace_the_extractors_prose_order() -> None:
    out = merge(PROMPT, draft(), proposal(step_dependencies=[{"id": "s2", "depends_on": []}]))
    assert out.spec.steps[1].depends_on == []
    assert out.dropped == []


def test_a_dependency_on_an_unknown_step_is_dropped() -> None:
    out = merge(PROMPT, draft(), proposal(step_dependencies=[{"id": "s2", "depends_on": ["s9"]}]))
    assert out.spec.steps[1].depends_on == ["s1"]
    assert "unknown ids" in out.dropped[0]


def test_a_self_dependency_is_dropped() -> None:
    out = merge(PROMPT, draft(), proposal(step_dependencies=[{"id": "s2", "depends_on": ["s2"]}]))
    assert out.spec.steps[1].depends_on == ["s1"]
    assert "depends on itself" in out.dropped[0]


def test_a_cycle_drops_the_whole_rewiring_not_part_of_it() -> None:
    """A cyclic spec has no execution order at all, and P3 would find that out at
    run time. Applying the acyclic half of a cyclic proposal would leave an
    ordering nobody proposed, so it is all or nothing."""
    out = merge(PROMPT, draft(), proposal(step_dependencies=[
        {"id": "s1", "depends_on": ["s2"]},
        {"id": "s2", "depends_on": ["s1"]},
    ]))
    assert [s.depends_on for s in out.spec.steps] == [[], ["s1"]]
    assert "cyclic" in out.dropped[0]


def test_a_dependency_may_reference_a_step_the_same_proposal_added() -> None:
    """Steps are merged before dependencies for exactly this: a refiner that adds
    a step and then says what waits on it should not lose the second half."""
    out = merge(PROMPT, draft(), proposal(
        steps=[{"description": "Receive the invoice", "kind_hint": "service", "side_effecting": False,
                "after": None, "evidence": "an invoice arrives by email"}],
        step_dependencies=[{"id": "s1", "depends_on": ["s3"]}],
    ))
    by_id = {s.id: s for s in out.spec.steps}
    assert by_id["s1"].depends_on == ["s3"]
    assert by_id["s3"].depends_on == []
    assert out.dropped == []


def test_a_dependency_that_contradicts_a_step_the_same_proposal_added_is_dropped() -> None:
    """The two halves of a proposal are checked against each other, not just
    against the draft. "s3 comes after s2" and "s2 waits for s3" cannot both be
    true, and the cycle check is what notices."""
    out = merge(PROMPT, draft(), proposal(
        steps=[{"description": "Pay the invoice automatically", "kind_hint": "service",
                "side_effecting": True, "after": "s2", "evidence": "Otherwise pay it automatically"}],
        step_dependencies=[{"id": "s2", "depends_on": ["s1", "s3"]}],
    ))
    by_id = {s.id: s for s in out.spec.steps}
    assert by_id["s2"].depends_on == ["s1"]
    assert "cyclic" in out.dropped[0]


# ---------- the refiner around the merge ----------


class FakeTransport:
    """A transport that counts calls and returns whatever it was handed.

    Counting is the point: the charter's D3-D4 bar is "the same prompt twice is
    zero model calls the second time", and only a countable transport can show it.
    """

    name = "fake"

    def __init__(self, reply: str = "{}") -> None:
        self.reply = reply
        self.calls = 0
        self.last: tuple[str, str, dict[str, Any]] | None = None

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str:
        self.calls += 1
        self.last = (system, user, schema)
        return self.reply


class ExplodingTransport:
    name = "boom"

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> str:
        raise RuntimeError("no API key")


def test_the_refiner_applies_a_grounded_proposal_end_to_end() -> None:
    import json

    transport = FakeTransport(json.dumps(proposal(
        trigger={"value": "an invoice arrives by email", "evidence": "an invoice arrives by email"},
    )))
    spec = LLMRefiner(transport).refine(PROMPT, draft())
    assert spec.trigger == "an invoice arrives by email"
    assert transport.calls == 1


def test_a_transport_failure_serves_the_deterministic_draft() -> None:
    """The refiner is an enhancement, not a dependency. A missing key, a timeout
    or a 500 costs the residue -- it must not cost the request."""
    started = draft()
    out = LLMRefiner(ExplodingTransport()).refine_verbosely(PROMPT, started)
    assert out.spec == started
    assert out.spec.source == "extracted"
    assert "transport:" in out.dropped[0]


@pytest.mark.parametrize("reply", ["not json at all", "[1, 2, 3]", ""])
def test_an_unusable_response_serves_the_deterministic_draft(reply: str) -> None:
    started = draft()
    out = LLMRefiner(FakeTransport(reply)).refine_verbosely(PROMPT, started)
    assert out.spec == started
    assert out.dropped


def test_the_refiner_is_never_handed_an_artifact() -> None:
    """Leg 3 of the anti-circularity guarantee reaches this module too: the
    refiner's whole input is the prompt and a Spec built from the prompt, and
    `refine()` has no parameter that could carry BPMN even if someone wanted it."""
    import inspect

    parameters = list(inspect.signature(LLMRefiner.refine).parameters)
    assert parameters == ["self", "prompt", "draft"]

    transport = FakeTransport()
    LLMRefiner(transport).refine(PROMPT, draft())
    assert transport.last is not None
    system, user, _schema = transport.last
    assert "bpmn" not in (system + user).lower()


def test_the_extractor_accepts_the_refiner_as_its_seam() -> None:
    """`extract(prompt, refiner)` is the wiring `/v1/spec` uses. Asserted here
    because the two modules are only ever joined at that call."""
    import json

    transport = FakeTransport(json.dumps(proposal(outputs=[
        {"name": "receipt", "type": "string", "evidence": "File the receipt in the accounting system"},
    ])))
    spec = extract(PROMPT, LLMRefiner(transport))
    assert [f.name for f in spec.outputs] == ["receipt"]
    assert spec.source == "merged"


# ---------- cache identity ----------


def test_the_cache_version_names_whatever_produced_the_spec() -> None:
    """Turning the refiner on, or swapping which one is wired, has to miss the
    cache. Otherwise the first corpus run after the change quietly serves specs
    from the pipeline you just replaced."""
    assert cache_version("d3.1", None) == "d3.1"
    with_refiner = cache_version("d3.1", LLMRefiner(FakeTransport(), version="d4.1"))
    assert with_refiner == "d3.1+fake.d4.1"
    assert with_refiner != cache_version("d3.1", LLMRefiner(FakeTransport(), version="d4.2"))
    assert with_refiner != cache_version("d3.2", LLMRefiner(FakeTransport(), version="d4.1"))


# ---------- configuration ----------


def test_no_refiner_runs_unless_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no LLM client and no API key in this repo. On-by-default would
    make every real-mode request a failed call plus a warning line."""
    monkeypatch.delenv("WFEVAL_SPEC_REFINER", raising=False)
    assert refine.refiner_from_env() is None
    monkeypatch.setenv("WFEVAL_SPEC_REFINER", "off")
    assert refine.refiner_from_env() is None
    monkeypatch.setenv("WFEVAL_SPEC_REFINER", "nonsense")
    assert refine.refiner_from_env() is None


def test_opting_in_builds_an_anthropic_refiner_without_calling_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing the transport must not import the SDK or need a key -- the
    service has to start in an environment that has neither."""
    monkeypatch.setenv("WFEVAL_SPEC_REFINER", "llm")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    refiner = refine.refiner_from_env()
    assert refiner is not None
    assert refiner.name == "anthropic"
    assert isinstance(refiner.transport, refine.AnthropicTransport)
    assert refiner.transport.model == refine.DEFAULT_MODEL


def test_an_empty_proposal_changes_nothing() -> None:
    started = draft()
    out = merge(PROMPT, started, proposal())
    assert out == Refinement(spec=started, applied=[], dropped=[])
