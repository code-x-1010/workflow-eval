"""Canonical DMN 1.3 decision-table model.

Additive to the frozen D2 core, not a breaking change -- new module, doesn't
touch `ast.py`/`Element`/`Flow` at all. A decision table is rows-and-columns,
not nodes-and-edges, so this deliberately does not try to force-fit DMN into
`WorkflowAST`. See `wfeval.adapters.dmn` for the parser and
`services/validation/src/l_dmn.py` for gap/overlap analysis against this
model.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class HitPolicy(str, Enum):
    UNIQUE = "UNIQUE"
    FIRST = "FIRST"
    PRIORITY = "PRIORITY"
    ANY = "ANY"
    COLLECT = "COLLECT"
    RULE_ORDER = "RULE ORDER"
    OUTPUT_ORDER = "OUTPUT ORDER"


class InputClause(BaseModel):
    id: str
    label: str | None = None
    expression: str = Field(..., description="The FEEL input expression this column tests, e.g. 'amount'.")


class OutputClause(BaseModel):
    id: str
    label: str | None = None
    name: str


class Rule(BaseModel):
    id: str
    locator: str | None = None
    input_entries: list[str | None] = Field(
        ..., description="One per InputClause, same order. None means '-' (wildcard, matches anything)."
    )
    output_entries: list[str] = Field(..., description="One per OutputClause, same order.")
    annotation: str | None = None


class DecisionTable(BaseModel):
    hit_policy: HitPolicy = HitPolicy.UNIQUE
    inputs: list[InputClause]
    outputs: list[OutputClause]
    rules: list[Rule]


class Decision(BaseModel):
    id: str
    name: str | None = None
    locator: str | None = None
    table: DecisionTable | None = Field(
        None, description="None if the decision uses a literal expression rather than a table -- not modeled here."
    )


class DecisionModel(BaseModel):
    definitions_id: str
    decisions: list[Decision]
    digest: str | None = Field(None, description="sha256 of the source artifact.")
