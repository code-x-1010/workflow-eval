"""Spec / IR: the structured representation of what the USER ASKED FOR.

Derived from the prompt ONLY. This is the anti-circularity boundary: a Spec must
never be built by reading a generated artifact, or intent alignment and test
generation both become tautologies.

Owned by P2. FROZEN after D2.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DataField(BaseModel):
    name: str
    type: str
    required: bool = True
    bound: int | None = Field(None, description="Volume hint, e.g. max line items. Feeds Cost free variables.")


class BranchCondition(BaseModel):
    description: str
    expression_hint: str | None = None
    probability_hint: float | None = Field(None, description="From the prompt, e.g. 'about 10% need approval'.")


class Step(BaseModel):
    id: str
    description: str
    kind_hint: str | None = Field(None, description="agent | service | user | decision — what the user implied.")
    depends_on: list[str] = Field(default_factory=list)
    is_deterministic: bool = Field(False, description="True -> a DMN table beats an agent. Feeds COST advice.")
    side_effecting: bool = False


class Spec(BaseModel):
    trigger: str | None = None
    steps: list[Step] = Field(default_factory=list)
    inputs: list[DataField] = Field(default_factory=list)
    outputs: list[DataField] = Field(default_factory=list)
    branches: list[BranchCondition] = Field(default_factory=list)
    error_behaviour: str | None = None
    integrations: list[str] = Field(default_factory=list)
    budget_per_instance: float | None = Field(None, description="If stated in the prompt, Cost gates on it.")
    source: str = Field("extracted", description="extracted | upstream | merged")
