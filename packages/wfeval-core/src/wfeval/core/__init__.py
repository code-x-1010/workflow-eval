"""wfeval-core — shared domain types.

FROZEN after Day 2. This package has no network calls, no I/O, and no
dependencies on any service. Everything imports it; it imports nothing back.

If you need a change here, DO NOT EDIT. Write a proposal in docs/decisions/ and
stop. See AGENTS.md, "Changing a frozen contract".
"""
from .ast import Element, ElementKind, Flow, LoopSpec, WorkflowAST
from .diagnostics import PREFIX_OWNER, Diagnostic, Severity
from .ir import BranchCondition, DataField, Spec, Step
from .report import (
    Confidence,
    CostReport,
    EvaluationReport,
    ExecutionReport,
    ExecutionResult,
    IntentReport,
    ValidationReport,
    Verdict,
)
from .testcase import Assertion, AssertionType, CaseKind, MockDefinition, TestCase
from .trace import Actuals, ElementEvent, Trace

__all__ = [
    "Actuals", "Assertion", "AssertionType", "BranchCondition", "CaseKind",
    "Confidence", "CostReport", "DataField", "Diagnostic", "Element",
    "ElementEvent", "ElementKind", "EvaluationReport", "ExecutionReport",
    "ExecutionResult", "Flow", "IntentReport", "LoopSpec", "MockDefinition",
    "PREFIX_OWNER", "Severity", "Spec", "Step", "TestCase", "Trace",
    "ValidationReport", "Verdict", "WorkflowAST",
]
