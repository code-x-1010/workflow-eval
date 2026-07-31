"""Diagnostic model. FROZEN after D2 — see contracts/README.md.

Every service emits Diagnostics. The `code` registry is the layer's public
interface: the generation team keys their repair logic off these strings, so
codes are append-only. Never rename or repurpose an existing code.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    ERROR = "error"      # blocks a gate, or fails a test case
    WARNING = "warning"  # degrades a score, never blocks
    INFO = "info"        # advice only


class Diagnostic(BaseModel):
    code: str = Field(..., description="PREFIX-CATEGORY-DETAIL, e.g. STR-UNREACHABLE-TASK")
    severity: Severity
    message: str = Field(..., description="Human-readable, specific to this artifact.")
    suggested_fix: str | None = Field(
        None,
        description="Imperative the generator can act on. 'Connect an outgoing flow "
        "from Gateway_0kk' — not 'the graph is invalid'.",
    )
    element_id: str | None = Field(None, description="BPMN element id, when applicable.")
    locator: str | None = Field(None, description="XPath (BPMN) or JSON pointer (n8n).")


# Prefix ownership. An agent may only emit codes under its own prefixes.
# Enforced by tests/contract/test_code_ownership.py
PREFIX_OWNER: dict[str, str] = {
    "SCH": "P1", "REF": "P1", "STR": "P1", "FLW": "P1", "DMN": "P1",
    "SPEC": "P2", "INT": "P2",
    "PLT": "P3", "EXE": "P3", "ROB": "P3",
    "COST": "P4",
}
