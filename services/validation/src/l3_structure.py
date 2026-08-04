"""L3: structural semantics.

Implemented: exactly one start event; every element reachable from it; every
reachable path terminates at an end event; exclusive/inclusive gateway splits
have either a default flow or a condition on every outgoing flow (undefined
runtime behaviour otherwise); parallel gateway splits don't carry conditions
they'd ignore; ISO-8601 conformance on timer values.

DEFERRED to L4: "no mixed inclusive/exclusive join" needs token-provenance
tracing (which split each incoming branch of a join descends from, and
whether the split/join types agree) -- that is soundness analysis, not plain
graph structure, and belongs with the BPMN -> workflow-net -> soundness work
in the charter's L4 tier. Implementing a shortcut version here risked either
false positives on legitimate patterns or missing the real cases; better to
do it once, properly, alongside L4. See docs/handoff/P1.md.

`score()`'s error/warning weighting is a documented heuristic, not a
calibrated model -- ships at whatever severity each check below says
(warning unless noted), per the house rule that new analysers start at
warning and get promoted after fixtures validate them.
"""
from __future__ import annotations

import re

from wfeval.core.ast import ElementKind, WorkflowAST
from wfeval.core.diagnostics import Diagnostic, Severity

_ISO8601_DURATION = re.compile(
    r"^P(?!$)(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+(\.\d+)?S)?)?$"
)
_ISO8601_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$"
)

_GATEWAY_KINDS = (ElementKind.GATEWAY_EXCLUSIVE, ElementKind.GATEWAY_PARALLEL, ElementKind.GATEWAY_INCLUSIVE)


def check(ast: WorkflowAST) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    diagnostics += _start_events(ast)
    reachable = _reachable_set(ast)
    diagnostics += _unreachable_elements(ast, reachable)
    diagnostics += _dead_ends(ast, reachable)
    diagnostics += _gateway_balance(ast)
    diagnostics += _timers(ast)
    return diagnostics


def score(diagnostics: list[Diagnostic], element_count: int) -> float:
    """Heuristic, not calibrated -- see module docstring."""
    errors = sum(1 for d in diagnostics if d.severity == Severity.ERROR)
    warnings = sum(1 for d in diagnostics if d.severity == Severity.WARNING)
    denom = max(element_count, 1)
    penalty = min(1.0, (errors * 0.5 + warnings * 0.15) / denom)
    return round(1.0 - penalty, 4)


def _start_events(ast: WorkflowAST) -> list[Diagnostic]:
    starts = [e for e in ast.elements if e.kind == ElementKind.START_EVENT]
    if not starts:
        return [Diagnostic(
            code="STR-NO-START-EVENT", severity=Severity.ERROR,
            message="The process has no start event.",
            suggested_fix="Add a startEvent element that begins the process.",
        )]
    if len(starts) > 1:
        ids = ", ".join(e.id for e in starts)
        return [Diagnostic(
            code="STR-MULTIPLE-START-EVENTS", severity=Severity.ERROR,
            message=f"The process has {len(starts)} start events ({ids}); exactly one is required.",
            suggested_fix="Keep a single start event, or split this into separate processes "
                          "if multiple independent triggers are genuinely intended.",
            element_id=starts[0].id, locator=starts[0].locator,
        )]
    return []


def _reachable_set(ast: WorkflowAST) -> set[str]:
    frontier = [e.id for e in ast.elements if e.kind == ElementKind.START_EVENT]
    seen: set[str] = set()
    while frontier:
        eid = frontier.pop()
        if eid in seen:
            continue
        seen.add(eid)
        frontier.extend(ast.successors(eid))
    return seen


def _unreachable_elements(ast: WorkflowAST, reachable: set[str]) -> list[Diagnostic]:
    diagnostics = []
    for el in ast.elements:
        if el.kind == ElementKind.START_EVENT or el.id in reachable:
            continue
        diagnostics.append(Diagnostic(
            code="STR-UNREACHABLE-TASK", severity=Severity.WARNING,
            message=f"'{el.name or el.id}' ({el.kind.value}) is not reachable from any start event.",
            suggested_fix=f"Connect an incoming flow from the reachable part of the process to "
                          f"'{el.id}', or remove it if it is dead code.",
            element_id=el.id, locator=el.locator,
        ))
    return diagnostics


def _dead_ends(ast: WorkflowAST, reachable: set[str]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not any(e.kind == ElementKind.END_EVENT for e in ast.elements):
        diagnostics.append(Diagnostic(
            code="STR-NO-END-EVENT", severity=Severity.ERROR,
            message="The process has no end event.",
            suggested_fix="Add an endEvent element that terminates the process.",
        ))
    for el in ast.elements:
        if el.id not in reachable or el.kind == ElementKind.END_EVENT:
            continue
        if not ast.successors(el.id):
            diagnostics.append(Diagnostic(
                code="STR-NO-END-EVENT", severity=Severity.ERROR,
                message=f"'{el.name or el.id}' has no outgoing flow and is not an end event -- "
                        "this path never terminates.",
                suggested_fix=f"Add an outgoing flow from '{el.id}' to an end event "
                              "(directly or via more tasks).",
                element_id=el.id, locator=el.locator,
            ))
    return diagnostics


def _gateway_balance(ast: WorkflowAST) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for el in ast.elements:
        if el.kind not in _GATEWAY_KINDS:
            continue
        outgoing = [f for f in ast.flows if f.source == el.id]
        if len(outgoing) <= 1:
            continue  # not a split

        if el.kind == ElementKind.GATEWAY_PARALLEL:
            conditioned = [f for f in outgoing if f.condition_expr]
            if conditioned:
                diagnostics.append(Diagnostic(
                    code="STR-GATEWAY-UNEXPECTED-CONDITION", severity=Severity.WARNING,
                    message=f"Parallel gateway '{el.id}' has a condition on outgoing flow "
                            f"'{conditioned[0].id}', but parallel gateways activate every "
                            "outgoing flow regardless of conditions.",
                    suggested_fix=f"Remove the condition from '{conditioned[0].id}', or change "
                                  f"'{el.id}' to an exclusive/inclusive gateway if branching was intended.",
                    element_id=el.id, locator=el.locator,
                ))
            continue

        has_default = any(f.is_default for f in outgoing)
        unconditioned = [f for f in outgoing if not f.condition_expr and not f.is_default]
        if not has_default and unconditioned:
            kind_label = el.kind.value.removeprefix("gateway_").capitalize()
            diagnostics.append(Diagnostic(
                code="STR-GATEWAY-NO-DEFAULT", severity=Severity.WARNING,
                message=f"{kind_label} gateway '{el.id}' has {len(outgoing)} outgoing flows; "
                        f"{len(unconditioned)} have no condition and none is marked default. "
                        "Runtime behaviour is undefined if no condition matches.",
                suggested_fix=f"Mark one outgoing flow from '{el.id}' as the default flow, "
                              "or add a condition to every outgoing flow.",
                element_id=el.id, locator=el.locator,
            ))
    return diagnostics


def _timers(ast: WorkflowAST) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for el in ast.elements:
        if el.kind != ElementKind.TIMER:
            continue
        expr = el.attributes.get("timer_expression")
        timer_type = el.attributes.get("timer_type")
        if not expr:
            diagnostics.append(Diagnostic(
                code="STR-TIMER-MISSING-VALUE", severity=Severity.ERROR,
                message=f"Timer '{el.id}' has a timerEventDefinition but no duration/date/cycle value.",
                suggested_fix=f"Add a timeDuration, timeDate, or timeCycle expression to '{el.id}'.",
                element_id=el.id, locator=el.locator,
            ))
            continue
        valid = (
            (timer_type == "duration" and bool(_ISO8601_DURATION.match(expr)))
            or (timer_type == "date" and bool(_ISO8601_DATETIME.match(expr)))
            or timer_type == "cycle"  # R.../... recurrence grammar not validated in v1
        )
        if not valid:
            diagnostics.append(Diagnostic(
                code="STR-TIMER-INVALID-ISO8601", severity=Severity.ERROR,
                message=f"Timer '{el.id}' has {timer_type} value '{expr}', which is not valid ISO-8601.",
                suggested_fix=f"Use a valid ISO-8601 {timer_type} expression, e.g. 'P2D' for a 2-day duration.",
                element_id=el.id, locator=el.locator,
            ))
    return diagnostics
