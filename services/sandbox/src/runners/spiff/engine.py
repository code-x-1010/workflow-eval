"""Spiff engine harness: parse -> seed -> resolve -> Trace.

Verified against SpiffWorkflow 3.1 (2026-07-30) by hand -- these are not
guesses, they're the actual observed behaviour of the library:

1. A bare <serviceTask>/<userTask> with no embedded script or extension Spiff
   understands NEVER auto-completes. `do_engine_steps()` runs the task's
   `_run_hook` (a no-op for ServiceTask) and leaves it at TaskState.STARTED
   forever. Real UiPath-generated BPMN has no embedded scripts either --
   activities are described by UiPath extension attributes Spiff doesn't
   understand -- so EVERY automated task in a real artifact needs an explicit
   resolution step here. There is no "let Spiff run it unassisted".

2. Manual (user) tasks stop one stage earlier, at TaskState.READY, not
   STARTED -- `do_engine_steps()` only auto-advances non-manual tasks. Both
   states mean "needs resolution" as far as this harness is concerned.

3. Data does not flow through `BpmnWorkflow.data`. It flows task-to-task,
   copied from a completed predecessor's `task.data` into its successor.
   Seed test-case input on the START task before the first engine step, and
   always call `task.set_data(**everything_accumulated_so_far)` -- the full
   running dict, not just this task's new output -- before `task.complete()`,
   or a downstream gateway condition silently evaluates against a stale or
   empty scope.

A construct Spiff can't even parse (e.g. one that trips BpmnParser's
validation, such as a gateway split with no default flow and no condition)
is a runner limitation, not an artifact defect -- see EXE-RUNNER-UNSUPPORTED
in docs/agents/P3-sandbox.md. So is a reached task with no TaskStub,
MockDefinition, or human_task_outcomes entry to resolve it: we stop that
instance and mark the case skipped rather than hang forever or claim a false
pass/fail.
"""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from SpiffWorkflow.bpmn.parser import BpmnParser
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.exceptions import SpiffWorkflowException
from SpiffWorkflow.task import TaskState

from wfeval.core.diagnostics import Diagnostic, Severity
from wfeval.core.testcase import MockDefinition, TestCase
from wfeval.core.trace import Actuals, ElementEvent, RunnerFidelity, Trace

from ..assertions import evaluate
from .asset_refs import asset_ref_map
from .stubs import TaskStubResolver

RUNNER_NAME = "spiff"
_PENDING_STATES = (TaskState.READY, TaskState.STARTED)


def _build_spec(artifact: dict[str, Any]):
    content = artifact.get("content", artifact) if isinstance(artifact, dict) else artifact
    if isinstance(content, str):
        content = content.encode("utf-8")
    parser = BpmnParser()
    parser.add_bpmn_str(content)
    process_ids = parser.get_process_ids()
    if not process_ids:
        raise SpiffWorkflowException("No executable <process> found in artifact.")
    # Collaboration diagrams (multiple top-level processes / message flows
    # between pools) aren't in scope yet -- take the sole process.
    return parser.get_spec(process_ids[0])


def _pending_tasks(workflow: BpmnWorkflow) -> list:
    return [t for t in workflow.get_tasks() if t.state in _PENDING_STATES]


def _record_completions(workflow: BpmnWorkflow, seen_ids: set, path: list[str], events: list[ElementEvent]) -> None:
    now = datetime.now(UTC).isoformat()
    for t in workflow.get_tasks():
        # Spiff wraps every process in synthetic Start/End/join wrapper tasks
        # that don't correspond to a BPMN element -- verified by hand: they're
        # the only tasks with `bpmn_id is None`. Keep `path` to real element
        # ids only, since assertions and downstream diagnostics reason about
        # BPMN ids, not Spiff engine internals.
        if getattr(t.task_spec, "bpmn_id", None) is None:
            continue
        if t.state == TaskState.COMPLETED and t.id not in seen_ids:
            seen_ids.add(t.id)
            path.append(t.task_spec.bpmn_id)
            events.append(ElementEvent(element_id=t.task_spec.bpmn_id, started_at=now, ended_at=now,
                                        outcome="completed", actuals=Actuals()))


def _trace(case_id: str, instance_id: str, status: str, path: list[str],
           events: list[ElementEvent], variables: dict[str, Any]) -> Trace:
    return Trace(case_id=case_id, instance_id=instance_id, status=status, runner=RUNNER_NAME,
                 fidelity=RunnerFidelity.REDUCED, path=path, events=events,
                 final_variables=variables, totals=Actuals())


def run_case(
    artifact: dict[str, Any],
    test_case: TestCase,
    mocks: list[MockDefinition],
    timeout_s: int = 60,
) -> tuple[Trace, list[Diagnostic], str, str | None]:
    """Execute one TestCase to completion, timeout, or an unresolvable task.
    Never raises for a runner limitation -- see module docstring."""
    instance_id = f"inst_{uuid.uuid4().hex[:8]}"
    variables: dict[str, Any] = dict(test_case.input)
    path: list[str] = []
    events: list[ElementEvent] = []

    try:
        spec = _build_spec(artifact)
    except SpiffWorkflowException as exc:
        return (_trace(test_case.case_id, instance_id, "cancelled", path, events, variables),
                [_unsupported_diagnostic(test_case.case_id, f"artifact does not parse on Spiff: {exc}")],
                "skipped", None)

    workflow = BpmnWorkflow(spec)
    resolver = TaskStubResolver(test_case.task_stubs, asset_ref_map(artifact))
    seen_ids: set = set()
    stalled_ids: set = set()

    for start_task in _pending_tasks(workflow):
        start_task.set_data(**variables)

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            workflow.do_engine_steps()
        except SpiffWorkflowException as exc:
            return (_trace(test_case.case_id, instance_id, "faulted", path, events, variables),
                    [], "error", f"instance faulted evaluating an expression: {exc}")

        _record_completions(workflow, seen_ids, path, events)

        if workflow.is_completed():
            trace = _trace(test_case.case_id, instance_id, "completed", path, events, variables)
            status, failed = evaluate(test_case, trace)
            return trace, [], status, failed

        progressed = False
        for t in _pending_tasks(workflow):
            if t.id in stalled_ids:
                continue
            element_id = getattr(t.task_spec, "bpmn_id", None) or t.task_spec.name
            if getattr(t.task_spec, "manual", False):
                outcome = test_case.human_task_outcomes.get(element_id)
                if outcome is None:
                    stalled_ids.add(t.id)
                    continue
                variables["_outcome"] = outcome
                t.set_data(**variables)
                t.complete()
                progressed = True
                continue

            output = resolver.resolve(element_id)
            if output is None:
                stalled_ids.add(t.id)
                continue
            variables.update(output)
            t.set_data(**variables)
            t.complete()
            progressed = True

        if not progressed:
            unresolved = sorted({
                getattr(t.task_spec, "bpmn_id", None) or t.task_spec.name
                for t in _pending_tasks(workflow) if t.id in stalled_ids
            })
            return (_trace(test_case.case_id, instance_id, "cancelled", path, events, variables),
                    [_unsupported_diagnostic(test_case.case_id,
                                              f"no TaskStub/mock/human_task_outcomes for: {', '.join(unresolved)}",
                                              element_id=unresolved[0] if unresolved else None)],
                    "skipped", None)

    return (_trace(test_case.case_id, instance_id, "timed_out", path, events, variables),
            [], "error", f"instance exceeded timeout_s={timeout_s}")


def _unsupported_diagnostic(case_id: str, reason: str, element_id: str | None = None) -> Diagnostic:
    return Diagnostic(
        code="EXE-RUNNER-UNSUPPORTED",
        severity=Severity.INFO,
        message=f"Case {case_id}: {reason}",
        suggested_fix="No artifact change needed -- this is a runner limitation, not a "
                       "defect. Provide a TaskStub/MockDefinition/human_task_outcomes entry "
                       "for the unresolved element, or verify this case on the "
                       "uipath_maestro runner instead of Spiff.",
        element_id=element_id,
    )
