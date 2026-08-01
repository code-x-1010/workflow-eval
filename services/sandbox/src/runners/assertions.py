"""Assertion evaluation against a Trace. Runner-agnostic -- works the same
whether the trace came from Spiff or (eventually) UiPath.
"""
from __future__ import annotations

import ast
from collections import Counter
from typing import Any, cast

from wfeval.core.testcase import Assertion, AssertionType, TestCase
from wfeval.core.trace import Trace


def evaluate(test_case: TestCase, trace: Trace) -> tuple[str, str | None]:
    """Returns (status, failed_assertion) where status is 'pass' or 'fail'.
    Caller is responsible for 'error'/'skipped', which come from the runner
    failing to produce a trace at all, not from assertion evaluation."""
    path = set(trace.path)
    context = _context(trace)
    for assertion in test_case.assertions:
        failure = _check(assertion, path, trace, context)
        if failure:
            return "fail", failure
    return "pass", None


def _check(assertion: Assertion, path: set[str], trace: Trace, context: dict[str, Any]) -> str | None:
    if assertion.type == AssertionType.PATH:
        return _check_path(assertion, path)
    if assertion.type == AssertionType.OUTPUT:
        return _check_output(assertion, trace)
    if assertion.type == AssertionType.INVARIANT:
        return _check_invariant(assertion, context)
    if assertion.type == AssertionType.BUDGET:
        return _check_budget(assertion, trace)
    return cast(str, assertion.description)


def _check_path(assertion: Assertion, path: set[str]) -> str | None:
    for required in assertion.must_traverse or []:
        if required not in path:
            return cast(str, assertion.description)
    for forbidden in assertion.must_not_traverse or []:
        if forbidden in path:
            return cast(str, assertion.description)
    return None


def _check_output(assertion: Assertion, trace: Trace) -> str | None:
    if assertion.field is None:
        return cast(str, assertion.description)
    sentinel = object()
    actual = _lookup(trace.final_variables, assertion.field, sentinel)
    if actual != assertion.equals:
        return cast(str, assertion.description)
    return None


def _check_invariant(assertion: Assertion, context: dict[str, Any]) -> str | None:
    if not assertion.expr:
        return cast(str, assertion.description)
    try:
        if _eval_expr(assertion.expr, context):
            return None
    except (SyntaxError, ValueError, TypeError, KeyError, ZeroDivisionError):
        pass
    return cast(str, assertion.description)


def _check_budget(assertion: Assertion, trace: Trace) -> str | None:
    if assertion.max_cost is None:
        return cast(str, assertion.description)
    cost = _first_present(
        trace.final_variables,
        ("actual_cost_usd", "cost_usd", "estimated_cost_usd", "cost", "total_cost"),
    )
    if not isinstance(cost, int | float) or cost > assertion.max_cost:
        return cast(str, assertion.description)
    return None


def _context(trace: Trace) -> dict[str, Any]:
    values = dict(trace.final_variables)
    terminal_events = sum(1 for element_id in trace.path if element_id.lower().startswith("endevent"))
    values.update({
        "status": trace.status,
        "terminal_events": terminal_events,
        "task_executions": Counter(trace.path),
        "path": trace.path,
        "totals": trace.totals.model_dump(),
    })
    return values


def _lookup(values: dict[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = values
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return default
    return current


def _first_present(values: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in values:
            return values[key]
    return None


def _eval_expr(expr: str, context: dict[str, Any]) -> bool:
    node = ast.parse(expr, mode="eval")
    return bool(_eval_node(node.body, context))


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in context:
            raise KeyError(node.id)
        return context[node.id]
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, context)
        key = _eval_node(node.slice, context)
        return value[key]
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(value, context) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, context)
    if isinstance(node, ast.BinOp):
        return _eval_binop(node, context)
    if isinstance(node, ast.Compare):
        return _eval_compare(node, context)
    raise ValueError(f"Unsupported assertion expression: {ast.dump(node)}")


def _eval_binop(node: ast.BinOp, context: dict[str, Any]) -> Any:
    left = _eval_node(node.left, context)
    right = _eval_node(node.right, context)
    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        return left * right
    if isinstance(node.op, ast.Div):
        return left / right
    raise ValueError(f"Unsupported arithmetic operator: {ast.dump(node.op)}")


def _eval_compare(node: ast.Compare, context: dict[str, Any]) -> bool:
    left = _eval_node(node.left, context)
    for op, comparator in zip(node.ops, node.comparators, strict=True):
        right = _eval_node(comparator, context)
        if not _compare(left, op, right):
            return False
        left = right
    return True


def _compare(left: Any, op: ast.cmpop, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return bool(left == right)
    if isinstance(op, ast.NotEq):
        return bool(left != right)
    if isinstance(op, ast.Lt):
        return bool(left < right)
    if isinstance(op, ast.LtE):
        return bool(left <= right)
    if isinstance(op, ast.Gt):
        return bool(left > right)
    if isinstance(op, ast.GtE):
        return bool(left >= right)
    if isinstance(op, ast.In):
        return bool(left in right)
    if isinstance(op, ast.NotIn):
        return bool(left not in right)
    raise ValueError(f"Unsupported comparison operator: {ast.dump(op)}")
