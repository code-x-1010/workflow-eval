"""Canonical, platform-agnostic workflow AST. FROZEN after D2.

Produced by wfeval-adapters. Consumed by Validation and Cost.
NEVER imported by services/intent/src/testgen/** — enforced by .importlinter.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ElementKind(str, Enum):
    START_EVENT = "start_event"
    END_EVENT = "end_event"
    AGENT_TASK = "agent_task"          # LLM-backed; the expensive one
    SERVICE_TASK = "service_task"      # RPA process / API workflow
    USER_TASK = "user_task"            # human in the loop
    DECISION_TASK = "decision_task"    # DMN
    GATEWAY_EXCLUSIVE = "gateway_exclusive"   # branches the cost space
    GATEWAY_PARALLEL = "gateway_parallel"     # does NOT branch the cost space
    GATEWAY_INCLUSIVE = "gateway_inclusive"
    TIMER = "timer"
    SUBPROCESS = "subprocess"


class LoopSpec(BaseModel):
    """None means 'not a loop'. `cardinality_expr` set with `max_iterations` None
    means the bound is data-dependent -> Cost must stay symbolic."""
    max_iterations: int | None = None
    cardinality_expr: str | None = None
    is_parallel: bool = False


class Element(BaseModel):
    id: str
    kind: ElementKind
    name: str | None = None
    locator: str | None = None
    loop: LoopSpec | None = None
    expressions: list[str] = Field(default_factory=list, description="Raw expression strings for dataflow analysis.")
    variables_read: list[str] = Field(default_factory=list)
    variables_written: list[str] = Field(default_factory=list)
    asset_ref: str | None = Field(None, description="Deployed process/agent this task invokes.")
    attributes: dict[str, str] = Field(default_factory=dict, description="Platform extension attrs.")


class Flow(BaseModel):
    id: str
    source: str
    target: str
    condition_expr: str | None = None
    is_default: bool = False


class WorkflowAST(BaseModel):
    platform: str
    process_id: str
    elements: list[Element]
    flows: list[Flow]
    declared_variables: dict[str, str] = Field(default_factory=dict, description="name -> type")
    digest: str | None = Field(None, description="sha256 of the source artifact.")

    def element(self, eid: str) -> Element | None:
        return next((e for e in self.elements if e.id == eid), None)

    def successors(self, eid: str) -> list[str]:
        return [f.target for f in self.flows if f.source == eid]

    def predecessors(self, eid: str) -> list[str]:
        return [f.source for f in self.flows if f.target == eid]
