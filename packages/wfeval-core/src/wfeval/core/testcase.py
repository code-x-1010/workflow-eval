"""Test cases and mocks. Produced by P2 (Intent), consumed by P3 (Sandbox).

CROSS-TEAM CONTRACT — changes need a decision record signed off by P2 AND P3.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CaseKind(str, Enum):
    HAPPY = "happy"
    BOUNDARY = "boundary"
    ADVERSARIAL = "adversarial"


class AssertionType(str, Enum):
    PATH = "path"            # which elements were traversed
    OUTPUT = "output"        # final variable values
    INVARIANT = "invariant"  # must hold for every input
    BUDGET = "budget"        # estimated or actual cost ceiling


class Assertion(BaseModel):
    type: AssertionType
    description: str
    must_traverse: list[str] | None = None
    must_not_traverse: list[str] | None = None
    field: str | None = None
    equals: Any | None = None
    expr: str | None = Field(None, description="For INVARIANT, e.g. 'terminal_events == 1'.")
    max_cost: float | None = None


class MockDefinition(BaseModel):
    """A real outbound HTTP call to intercept (WireMock-seeded). Only meaningful
    for a runner that actually attempts network calls -- today that's the
    deferred UiPath runner. Spiff never touches the network, so it ignores
    this list entirely; TaskStub is what Spiff consumes instead."""
    host: str
    path: str
    method: str = "POST"
    status: int = 200
    response: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0


class TaskStub(BaseModel):
    """Canned output for one non-HTTP task invocation (an AGENT_TASK or
    SERVICE_TASK), keyed by `element_id` or `asset_ref` -- prefer `asset_ref`
    when known, since it survives the generator restructuring element ids,
    same reasoning as semantic path assertions. `outputs[i]` is returned on
    the i-th invocation; the counter is scoped to a single test case's
    instance (Sandbox starts a fresh instance per case, so it always resets
    to zero) and supports loops that call the same task more than once. If
    invoked more times than len(outputs), the last entry repeats.

    MockDefinition stays for real outbound HTTP calls; this is for the task
    or agent invocation itself -- what a real UiPath connector or agent
    would have returned, resolved locally with no network call at all.
    """
    element_id: str | None = None
    asset_ref: str | None = None
    outputs: list[dict[str, Any]] = Field(default_factory=list)


class TestCase(BaseModel):
    case_id: str
    kind: CaseKind
    description: str
    input: dict[str, Any]
    assertions: list[Assertion]
    human_task_outcomes: dict[str, str] = Field(
        default_factory=dict,
        description="element_id -> outcome. Lets Sandbox auto-resolve human tasks deterministically.",
    )
    task_stubs: list[TaskStub] = Field(
        default_factory=list,
        description="Canned outputs for this case's agent/service task invocations. P2 "
        "generates these alongside assertions -- both are derived from the prompt/spec, "
        "never from the artifact, same as everything else in testgen/.",
    )
