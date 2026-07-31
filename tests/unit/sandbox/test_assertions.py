from __future__ import annotations

from wfeval.core.testcase import Assertion, AssertionType, CaseKind, TestCase
from wfeval.core.trace import Trace

from services.sandbox.src.runners.assertions import evaluate


def _trace(path: list[str]) -> Trace:
    return Trace(case_id="tc_1", instance_id="i1", status="completed", runner="spiff", path=path)


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


def test_non_path_assertions_are_not_evaluated_yet():
    case = _case([Assertion(type=AssertionType.INVARIANT, description="one terminal event", expr="terminal_events == 1")])
    status, failed = evaluate(case, _trace(["Gateway_amount"]))
    assert (status, failed) == ("pass", None)
