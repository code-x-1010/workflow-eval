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
    host: str
    path: str
    method: str = "POST"
    status: int = 200
    response: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0


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
