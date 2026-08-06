from __future__ import annotations

from services.sandbox.src.runners.assertions import evaluate
from wfeval.core.testcase import Assertion, AssertionType, CaseKind, TestCase
from wfeval.core.trace import Trace


def _trace(path: list[str], variables: dict | None = None, status: str = "completed") -> Trace:
    return Trace(
        case_id="tc_1",
        instance_id="i1",
        status=status,
        runner="spiff",
        path=path,
        final_variables=variables or {},
    )


def _case(assertions: list[Assertion]) -> TestCase:
    return TestCase(case_id="tc_1", kind=CaseKind.HAPPY, description="d", input={}, assertions=assertions)


def test_must_traverse_satisfied_passes():
    case = _case([Assertion(type=AssertionType.PATH, description="d", must_traverse=["Gateway_amount", "Task_autopay"])])
    status, failed = evaluate(case, _trace(["Gateway_amount", "Task_autopay"]))
    assert (status, failed) == ("pass", None)


def test_must_traverse_missing_fails_with_description():
    case = _case([Assertion(type=AssertionType.PATH, description="must hit autopay", must_traverse=["Task_autopay"])])
    status, failed = evaluate(case, _trace(["Gateway_amount", "Task_approval"]))
    assert status == "fail"
    assert failed == "must hit autopay"


def test_must_not_traverse_violated_fails():
    case = _case([Assertion(type=AssertionType.PATH, description="no approval", must_not_traverse=["Task_approval"])])
    status, failed = evaluate(case, _trace(["Gateway_amount", "Task_approval"]))
    assert status == "fail"
    assert failed == "no approval"


def test_output_assertion_compares_final_variable():
    case = _case([Assertion(type=AssertionType.OUTPUT, description="settles", field="status", equals="SETTLED")])
    status, failed = evaluate(case, _trace(["Gateway_amount"], {"status": "SETTLED"}))
    assert (status, failed) == ("pass", None)


def test_output_assertion_supports_dotted_fields():
    case = _case([Assertion(type=AssertionType.OUTPUT, description="captures id", field="payment.id", equals="txn_1")])
    status, failed = evaluate(case, _trace(["Gateway_amount"], {"payment": {"id": "txn_1"}}))
    assert (status, failed) == ("pass", None)


def test_output_assertion_missing_or_mismatched_field_fails_with_description():
    case = _case([Assertion(type=AssertionType.OUTPUT, description="settles", field="status", equals="SETTLED")])
    status, failed = evaluate(case, _trace(["Gateway_amount"], {"status": "PENDING_APPROVAL"}))
    assert status == "fail"
    assert failed == "settles"


def test_invariant_assertion_reads_trace_context():
    case = _case([
        Assertion(
            type=AssertionType.INVARIANT,
            description="one terminal event and no double charge",
            expr="terminal_events == 1 and task_executions['Task_autopay'] <= 1 and status != 'faulted'",
        )
    ])
    status, failed = evaluate(
        case,
        _trace(["StartEvent_invoice", "Task_autopay", "EndEvent_done"], {"status": "SETTLED"}),
    )
    assert (status, failed) == ("pass", None)


def test_invariant_assertion_false_fails():
    case = _case([Assertion(type=AssertionType.INVARIANT, description="exactly one end", expr="terminal_events == 1")])
    status, failed = evaluate(case, _trace(["StartEvent_invoice", "Task_autopay"]))
    assert status == "fail"
    assert failed == "exactly one end"


def test_invariant_unsupported_expression_fails_closed():
    case = _case([Assertion(type=AssertionType.INVARIANT, description="no calls", expr="len(path) > 0")])
    status, failed = evaluate(case, _trace(["StartEvent_invoice"]))
    assert status == "fail"
    assert failed == "no calls"


def test_budget_assertion_uses_cost_variable():
    case = _case([Assertion(type=AssertionType.BUDGET, description="under budget", max_cost=0.50)])
    status, failed = evaluate(case, _trace(["Gateway_amount"], {"actual_cost_usd": 0.42}))
    assert (status, failed) == ("pass", None)


def test_budget_assertion_over_ceiling_fails():
    case = _case([Assertion(type=AssertionType.BUDGET, description="under budget", max_cost=0.50)])
    status, failed = evaluate(case, _trace(["Gateway_amount"], {"actual_cost_usd": 0.51}))
    assert status == "fail"
    assert failed == "under budget"
