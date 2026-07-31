"""Execution traces. Produced by P3 (Sandbox), consumed by P4 (Cost calibration).

CROSS-TEAM CONTRACT — the `Actuals` block is the P3->P4 handshake. Changes need a
decision record signed off by P3 AND P4.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunnerFidelity(str, Enum):
    """How much to trust a trace as evidence of real platform behaviour.

    PRODUCTION only when the runner IS the actual target platform engine
    (uipath_maestro). Spiff is fast/free/local/CI-friendly but doesn't exercise
    real connectors, Orchestrator queueing, or Action Center semantics -- it is
    REDUCED fidelity by construction. See docs/decisions/0002-spiff-primary-runner.md.
    """
    PRODUCTION = "production"
    REDUCED = "reduced"


class Actuals(BaseModel):
    """Observed cost inputs. Cheap to capture while building trace extraction,
    expensive to retrofit. P3: populate these from day one even if Cost isn't
    consuming them yet."""
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None
    agent_turns: int | None = None
    duration_ms: int | None = None
    robot_minutes: float | None = None
    human_minutes: float | None = None


class ElementEvent(BaseModel):
    element_id: str
    started_at: str
    ended_at: str | None = None
    outcome: str | None = None
    actuals: Actuals = Field(default_factory=Actuals)


class Trace(BaseModel):
    case_id: str
    instance_id: str
    status: str = Field(..., description="completed | faulted | timed_out | cancelled")
    runner: str = Field(..., description="Execution engine that produced this trace, e.g. 'spiff' or 'uipath_maestro'.")
    fidelity: RunnerFidelity = Field(
        RunnerFidelity.REDUCED,
        description="'production' only when `runner` is the actual target platform engine.",
    )
    path: list[str] = Field(default_factory=list, description="Ordered element ids actually traversed.")
    events: list[ElementEvent] = Field(default_factory=list)
    final_variables: dict[str, Any] = Field(default_factory=dict)
    totals: Actuals = Field(default_factory=Actuals)
