"""Exercises the real SpiffWorkflow engine (not mocked) against
tests/fixtures/spiff/executable_invoice.bpmn -- a gate-cleared copy of the
shared artifact.bpmn story. See that fixture's header comment for why it
isn't just contracts/examples/artifact.bpmn itself.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from wfeval.core.testcase import Assertion, AssertionType, CaseKind, TaskStub, TestCase

from services.sandbox.src.runners.spiff.engine import run_case

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "spiff" / "executable_invoice.bpmn"


def _artifact() -> dict:
    return {"content": FIXTURE.read_text()}


def test_happy_path_takes_the_autopay_branch():
    case = TestCase(
        case_id="tc_001", kind=CaseKind.HAPPY, description="under threshold", input={"amount": 250.0},
        assertions=[
            Assertion(type=AssertionType.PATH, description="auto-pay branch",
                      must_traverse=["Gateway_amount", "Task_autopay"], must_not_traverse=["Task_approval"]),
            Assertion(type=AssertionType.OUTPUT, description="settles invoice", field="status", equals="SETTLED"),
        ],
        task_stubs=[
            TaskStub(element_id="Task_extract", outputs=[{"vendor": "Acme Ltd", "amount": 250.0}]),
            TaskStub(element_id="Task_autopay", outputs=[{"status": "SETTLED"}]),
            TaskStub(element_id="Task_notify", outputs=[{}]),
        ],
    )
    trace, diagnostics, status, failed = run_case(_artifact(), case, mocks=[], timeout_s=10)
    assert status == "pass"
    assert failed is None
    assert diagnostics == []
    assert trace.path == ["StartEvent_invoice", "Task_extract", "Gateway_amount", "Task_autopay",
                           "Task_notify", "EndEvent_done"]
    assert trace.runner == "spiff"
    assert trace.fidelity == "reduced"


def test_output_assertion_failure_marks_case_failed():
    case = TestCase(
        case_id="tc_output", kind=CaseKind.HAPPY, description="output mismatch", input={"amount": 250.0},
        assertions=[Assertion(type=AssertionType.OUTPUT, description="settles invoice",
                               field="status", equals="SETTLED")],
        task_stubs=[
            TaskStub(element_id="Task_extract", outputs=[{"vendor": "Acme Ltd", "amount": 250.0}]),
            TaskStub(element_id="Task_autopay", outputs=[{"status": "PENDING_APPROVAL"}]),
            TaskStub(element_id="Task_notify", outputs=[{}]),
        ],
    )
    trace, diagnostics, status, failed = run_case(_artifact(), case, mocks=[], timeout_s=10)
    assert diagnostics == []
    assert trace.status == "completed"
    assert status == "fail"
    assert failed == "settles invoice"


def test_boundary_case_routes_to_approval_and_resolves_the_human_task():
    case = TestCase(
        case_id="tc_003", kind=CaseKind.BOUNDARY, description="one cent over", input={"amount": 10000.01},
        assertions=[Assertion(type=AssertionType.PATH, description="must route to approval",
                               must_traverse=["Task_approval"])],
        task_stubs=[
            TaskStub(element_id="Task_extract", outputs=[{"vendor": "Acme Ltd", "amount": 10000.01}]),
            TaskStub(element_id="Task_notify", outputs=[{}]),
        ],
        human_task_outcomes={"Task_approval": "approved"},
    )
    trace, _diagnostics, status, _failed = run_case(_artifact(), case, mocks=[], timeout_s=10)
    assert status == "pass"
    assert "Task_approval" in trace.path
    assert "Task_autopay" not in trace.path


def test_unresolvable_task_is_skipped_not_failed():
    """No TaskStub for Task_autopay -- a runner limitation, never an artifact defect."""
    case = TestCase(
        case_id="tc_005", kind=CaseKind.ADVERSARIAL, description="missing stub", input={"amount": 5.0},
        assertions=[],
        task_stubs=[TaskStub(element_id="Task_extract", outputs=[{"vendor": "Acme Ltd", "amount": 5.0}])],
    )
    trace, diagnostics, status, _failed = run_case(_artifact(), case, mocks=[], timeout_s=5)
    assert status == "skipped"
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "EXE-RUNNER-UNSUPPORTED"
    assert diagnostics[0].severity == "info"
    assert diagnostics[0].suggested_fix
    assert trace.status == "cancelled"


def test_unparseable_artifact_is_also_skipped_not_failed():
    """The shared artifact.bpmn's Gateway_amount has no default flow and no
    condition -- deliberately, per validation.response.json's
    STR-UNREACHABLE-TASK fixture. Any compliant BPMN engine rejects it, not
    just Spiff; Sandbox never sees this in practice because L1-L4 gates it
    first. Verifies the engine treats that as EXE-RUNNER-UNSUPPORTED, not a
    crash."""
    shared_fixture = Path(__file__).resolve().parents[3] / "contracts" / "examples" / "artifact.bpmn"
    case = TestCase(case_id="tc_001", kind=CaseKind.HAPPY, description="d", input={"amount": 250.0}, assertions=[])
    _trace, diagnostics, status, _failed = run_case(
        {"content": shared_fixture.read_text()}, case, mocks=[], timeout_s=5
    )
    assert status == "skipped"
    assert diagnostics[0].code == "EXE-RUNNER-UNSUPPORTED"


@pytest.mark.parametrize("timeout_s", [0])
def test_zero_timeout_times_out_immediately(timeout_s):
    case = TestCase(case_id="tc_timeout", kind=CaseKind.HAPPY, description="d", input={"amount": 1.0}, assertions=[],
                     task_stubs=[TaskStub(element_id="Task_extract", outputs=[{"amount": 1.0}])])
    trace, _diagnostics, status, failed = run_case(_artifact(), case, mocks=[], timeout_s=timeout_s)
    assert status == "error"
    assert "timeout_s" in (failed or "")
    assert trace.status == "timed_out"
