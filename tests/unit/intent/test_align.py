"""The deterministic Spec x AST differ, and the three fixtures the charter names.

Artifacts are built with `datasets/tools/bpmn.py` -- the same emitter that builds
the corpus, already validated by `test_corpus_bpmn.py`. Hand-written BPMN in a
test file is a second, unvalidated artifact format: a dangling `sequenceFlow`
reference in a fixture makes the differ look wrong when the fixture is what is
broken. Building them means every fixture here is structurally sound by
construction.

The matching problem is the whole problem (see align.py), so this file tests both
directions of it: a step named differently must still match, and a step that is
genuinely absent must still be reported.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from services.intent.src.align import align
from wfeval.adapters import parse
from wfeval.core.ir import BranchCondition, DataField, Spec, Step

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "datasets") not in sys.path:
    sys.path.insert(0, str(ROOT / "datasets"))

from tools.bpmn import branch, check, emit, end, start, task, xor

# The corpus emitter has no `agent` task kind, because the adapter does not infer
# one from a tag: `ElementKind.AGENT_TASK` requires a UiPath `activityType`
# attribute on an otherwise ordinary service task. Rather than teach the emitter a
# platform extension it does not need, the two tests that want an agent task
# stamp the attribute on afterwards. Everything else is emitted normally.
UIPATH_NS = "http://uipath.com/schema/maestro"


def as_agent(xml: str, element_id: str) -> str:
    xml = xml.replace("<definitions ", f'<definitions xmlns:uipath="{UIPATH_NS}" ', 1)
    return xml.replace(f'id="{element_id}"', f'id="{element_id}" uipath:activityType="Agent"', 1)


PROMPT = (
    "When an invoice arrives by email, extract the vendor and the amount. "
    "If the amount is over 10000, route it to a manager for approval; otherwise "
    "pay it automatically. Notify the vendor when it is settled."
)


def spec(**overrides: object) -> Spec:
    base = Spec(
        trigger="an invoice arrives by email",
        steps=[
            Step(id="s1", description="Extract the vendor and the amount", kind_hint="agent",
                 depends_on=[], is_deterministic=False, side_effecting=False),
            Step(id="s2", description="Route it to a manager for approval", kind_hint="user",
                 depends_on=["s1"], is_deterministic=True, side_effecting=True),
            Step(id="s3", description="Pay it automatically", kind_hint="service",
                 depends_on=["s2"], is_deterministic=True, side_effecting=True),
        ],
        inputs=[DataField(name="amount", type="decimal", required=True, bound=None)],
        outputs=[],
        branches=[BranchCondition(description="amount is over 10000",
                                  expression_hint="amount > 10000", probability_hint=None)],
        error_behaviour=None,
        integrations=["email"],
        budget_per_instance=None,
        source="extracted",
    )
    return base.model_copy(update=overrides)  # type: ignore[arg-type]


def artifact(*, drop_pay: bool = False, extra_task: bool = False, conditions: bool = True) -> str:
    """The faithful implementation of `spec()`, with switches for each defect."""
    approve = [task("Task_approve", "Manager approval", "user")]
    autopay = [] if drop_pay else [task("Task_autopay", "Pay it automatically", "service")]
    nodes: list[object] = [
        start("Start_invoice", "Invoice received by email", message=True),
        task("Task_extract", "Extract vendor and amount", "service"),
        xor("Gateway_amount", "Amount over 10000?", [
            branch("over", approve, condition="amount > 10000" if conditions else None),
            branch("under", autopay or [task("Task_noop", "Record it", "service")],
                   default=True),
        ], join="Join_amount"),
        task("Task_notify", "Notify the vendor", "service"),
    ]
    if extra_task:
        nodes.append(task("Task_upsell", "Add the customer to the upsell campaign", "service"))
    nodes.append(end("End_done", "Done"))
    xml = emit("invoice", nodes)  # type: ignore[arg-type]
    if conditions:
        assert check(xml) == [], check(xml)
    else:
        # `conditions=False` is deliberately the defect `check()` exists to catch
        # -- an exclusive gateway whose outgoing flows carry neither a condition
        # nor a default marker. It is also the real defect in
        # contracts/examples/artifact.bpmn, and the one INT-CONDITION-NOT-EXPRESSED
        # reports. Asserting the validator still sees it keeps the two views
        # honest: P1's structure tier and P2's intent tier should both notice,
        # and for different reasons.
        assert check(xml) != []
    return xml


def codes(alignment: object) -> list[str]:
    return sorted(d.code for d in alignment.diagnostics)  # type: ignore[attr-defined]


# ---------- the three fixtures the charter names ----------


def test_int_missing_step() -> None:
    """The prompt asks for automatic payment; the artifact never pays."""
    result = align(spec(), parse(artifact(drop_pay=True)), PROMPT)
    assert "INT-MISSING-STEP" in codes(result)
    missing = next(d for d in result.diagnostics if d.code == "INT-MISSING-STEP")
    assert "Pay it automatically" in missing.message
    assert result.scores["step_coverage"] < 1.0


def test_int_extra_side_effect() -> None:
    """The artifact enrols the customer in a marketing campaign. Nobody asked."""
    result = align(spec(), parse(artifact(extra_task=True)), PROMPT)
    assert "INT-EXTRA-SIDE-EFFECT" in codes(result)
    extra = next(d for d in result.diagnostics if d.code == "INT-EXTRA-SIDE-EFFECT")
    assert extra.element_id == "Task_upsell"
    assert extra.suggested_fix is not None and "Task_upsell" not in extra.suggested_fix.split()[0]


def test_int_order_violation() -> None:
    """The prompt approves before paying. This artifact pays, then approves."""
    reversed_flow = emit("invoice", [
        start("Start_invoice", "Invoice received by email", message=True),
        task("Task_extract", "Extract vendor and amount", "service"),
        task("Task_autopay", "Pay it automatically", "service"),
        task("Task_approve", "Manager approval", "user"),
        end("End_done", "Done"),
    ])
    assert check(reversed_flow) == []
    result = align(spec(), parse(reversed_flow), PROMPT)
    assert "INT-ORDER-VIOLATION" in codes(result)
    assert result.scores["order_fidelity"] < 1.0


# ---------- matching, in both directions ----------


def test_a_step_named_differently_still_matches() -> None:
    """"Route it to a manager for approval" against an element called "Manager
    approval". Failing this invents INT-MISSING-STEP for a step that is there,
    which is the more damaging of the two failure modes -- it tells the
    generation team to add something they already built."""
    result = align(spec(), parse(artifact()), PROMPT)
    assert result.element_for("s2") == "Task_approve"
    assert "INT-MISSING-STEP" not in codes(result)


def test_matching_is_one_to_one() -> None:
    """Two spec steps must never claim the same element -- that reads as full
    coverage of a workflow that only does half the job."""
    result = align(spec(), parse(artifact()), PROMPT)
    elements = [m.element_id for m in result.matches]
    assert len(elements) == len(set(elements))


def test_an_unrelated_element_does_not_match() -> None:
    unrelated = emit("invoice", [
        start("Start_x", "Start"),
        task("Task_weather", "Check the weather forecast", "service"),
        end("End_x", "Done"),
    ])
    result = align(spec(), parse(unrelated), unrelated)
    assert result.matches == []
    assert result.scores["step_coverage"] == 0.0


def test_an_unmatched_element_the_prompt_asked_for_is_not_an_extra_side_effect() -> None:
    """The correction that took this rule from 83 findings across the reference
    corpus to a usable number. `extract()` finds ~3 steps per prompt while the
    artifacts have many more tasks, so an unmatched element mostly means the
    extractor was quiet -- not that the generator invented something."""
    prompt = PROMPT + " Also file the receipt in the accounting system."
    with_filing = emit("invoice", [
        start("Start_invoice", "Invoice received by email", message=True),
        task("Task_extract", "Extract vendor and amount", "service"),
        task("Task_file", "File the receipt", "service"),
        end("End_done", "Done"),
    ])
    result = align(spec(), parse(with_filing), prompt)
    assert "INT-EXTRA-SIDE-EFFECT" not in codes(result)


def test_an_unmatched_agent_task_is_never_an_extra_side_effect() -> None:
    """Decomposing one asked-for step into two reasoning steps is an
    implementation choice, not a change to what the process does to the world."""
    decomposed = as_agent(emit("invoice", [
        start("Start_invoice", "Invoice received by email", message=True),
        task("Task_extract", "Extract vendor and amount", "service"),
        task("Task_classify", "Classify the document type", "service"),
        end("End_done", "Done"),
    ]), "Task_classify")
    ast = parse(decomposed)
    assert ast.element("Task_classify").kind.value == "agent_task", "precondition: it really is an agent task"
    result = align(spec(), ast, PROMPT)
    assert "INT-EXTRA-SIDE-EFFECT" not in codes(result)


# ---------- the other codes ----------


def test_a_threshold_with_no_routable_condition_is_reported() -> None:
    """The real defect in the shared fixture: flows labelled "over" and "under"
    with no condition expression, so the threshold exists only as a name."""
    result = align(spec(), parse(artifact(conditions=False)), PROMPT)
    assert "INT-CONDITION-NOT-EXPRESSED" in codes(result)


def test_an_expressed_condition_is_not_reported() -> None:
    result = align(spec(), parse(artifact(conditions=True)), PROMPT)
    assert "INT-CONDITION-NOT-EXPRESSED" not in codes(result)


def test_error_handling_is_only_asked_for_when_the_prompt_stated_it() -> None:
    """Silent when the prompt never said -- that gap is SPEC-NO-ERROR-BEHAVIOUR,
    and reporting it under both prefixes double-counts one omission in whatever
    P4 aggregates."""
    assert "INT-NO-ERROR-HANDLING" not in codes(align(spec(), parse(artifact()), PROMPT))
    stated = spec(error_behaviour="if the payment API fails, park the invoice")
    assert "INT-NO-ERROR-HANDLING" in codes(align(stated, parse(artifact()), PROMPT))


def test_a_schedule_against_a_message_start_is_a_trigger_mismatch() -> None:
    scheduled = spec(trigger="Every night at 2am")
    assert "INT-TRIGGER-MISMATCH" in codes(align(scheduled, parse(artifact()), PROMPT))


def test_a_matching_trigger_kind_is_not_reported() -> None:
    """Compares the kind of trigger, not its wording: "when an invoice arrives"
    against a message start is agreement, whatever words each uses."""
    assert "INT-TRIGGER-MISMATCH" not in codes(align(spec(), parse(artifact()), PROMPT))


def test_a_named_integration_that_nothing_invokes_is_reported() -> None:
    result = align(spec(integrations=["slack"]), parse(artifact()), PROMPT)
    assert "INT-INTEGRATION-MISSING" in codes(result)


def test_a_stranded_step_is_unreachable_not_missing() -> None:
    """The generator did build it, so a repair that adds it again is the wrong
    fix. What is wrong is the wiring, and only this tier can say which asked-for
    step is the one stranded."""
    orphaned = emit("invoice", [
        start("Start_invoice", "Invoice received by email", message=True),
        task("Task_extract", "Extract vendor and amount", "service"),
        end("End_done", "Done"),
    ])
    # Splice in a task nothing flows to -- the one shape the emitter will not
    # build for us, because its own validator rejects unreachable elements.
    orphaned = orphaned.replace(
        "</process>",
        '<serviceTask id="Task_autopay" name="Pay it automatically" /></process>',
    )
    result = align(spec(), parse(orphaned), PROMPT)
    assert "INT-UNREACHABLE-INTENT" in codes(result)
    assert "INT-MISSING-STEP" not in [d.code for d in result.diagnostics if "autopay" in (d.element_id or "")]


# ---------- scores ----------


def test_a_faithful_artifact_scores_high() -> None:
    result = align(spec(), parse(artifact()), PROMPT)
    assert result.scores["step_coverage"] == 1.0
    assert result.scores["order_fidelity"] == 1.0
    assert result.scores["intent_coverage"] >= 0.9


def test_intent_coverage_is_not_step_coverage() -> None:
    """`0019`'s point, and the reason the golden example can report all four steps
    matched at 0.72. A workflow can contain every step the prompt asked for and
    still be wrong about what the prompt meant."""
    result = align(spec(), parse(artifact(conditions=False)), PROMPT)
    assert result.scores["step_coverage"] == 1.0
    assert result.scores["intent_coverage"] < result.scores["step_coverage"]


def test_scores_stay_inside_zero_to_one() -> None:
    """Penalties are subtractive, so a badly wrong artifact could otherwise drive
    the headline negative and hand P4 a number no scorecard can render."""
    awful = spec(integrations=["slack", "crm", "erp", "sms"], trigger="Every night at 2am")
    result = align(awful, parse(artifact(drop_pay=True, extra_task=True, conditions=False)), "")
    for name, value in result.scores.items():
        assert 0.0 <= value <= 1.0, f"{name}={value}"


@pytest.mark.parametrize("bad", ["", "<nonsense/>", "not xml at all"])
def test_the_differ_is_never_handed_an_unparsed_artifact(bad: str) -> None:
    """`align()` takes a WorkflowAST, not a string. Parsing is the caller's job
    and its failure is the caller's to report -- see `0020`, where five corpus
    artifacts cannot be parsed at all and are reported as skipped rather than
    scored zero."""
    from wfeval.adapters import AdapterParseError

    with pytest.raises((AdapterParseError, Exception)):
        parse(bad)
