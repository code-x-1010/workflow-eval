"""L4 dataflow: every referenced variable must be assigned on all incoming paths.

"Assigned on all paths reaching use U" is a *set* domination question, not a
single-node one: it's not enough to ask whether one specific writer dominates
U, because two writers on two different branches of a split can jointly cover
every path even though neither dominates U alone (see
test_variable_written_on_every_branch_is_clean). The general, still-not-naive
way to answer "does writer-set W dominate U" is a standard equivalence: W
dominates U if and only if U is unreachable from the start event in the graph
with every node in W removed (any path that reached U would have had to pass
through some node of W, since removing W is exactly what would have broken
that path). That's `_guaranteed_assigned` below -- reachability in a
deliberately *modified* graph (writers cut out), which is what makes this
"dominators, not naive reachability" per the charter: naive reachability would
ask "was there some path where a write happened", the wrong question; this
asks "is there a path where NO write happened", the right one.

Two sources of "reads":
  - `Element.variables_read` -- explicit, from the adapter's `<uipath:variables>`
    markers. Checked against dominance at that element.
  - Identifiers inside `Flow.condition_expr` -- extracted with a small `lark`
    grammar (comparisons/boolean logic/parens, enough for the "amount > 10000"
    style conditions seen in the fixtures; see the adapter's own documented
    limitation that `Element.expressions` is always empty today). Checked
    against dominance at the flow's *source* element, since that's where the
    condition is evaluated.

`declared_variables` is always `{}` today (adapter limitation, see
wfeval/adapters/bpmn.py) -- this deliberately does not require a variable
to appear there. A variable with zero writers anywhere in the process falls
out of the dominance check naturally (no writer can dominate anything), which
is exactly the documented "first-write-wins, nothing declared" fallback.

Ships at `warning` severity, same reasoning as l4_soundness.py.
"""
from __future__ import annotations

import networkx as nx
from lark import Lark, Token, Tree
from lark.exceptions import LarkError

from wfeval.core.ast import WorkflowAST
from wfeval.core.diagnostics import Diagnostic, Severity

_GRAMMAR = r"""
?start: or_expr
?or_expr: and_expr (OR and_expr)*
?and_expr: not_expr (AND not_expr)*
?not_expr: NOT not_expr | comparison
?comparison: sum (COMPARATOR sum)?
?sum: product ((PLUS|MINUS) product)*
?product: atom ((STAR|SLASH) atom)*
?atom: NUMBER -> number
     | ESCAPED_STRING -> string
     | TRUE -> true_
     | FALSE -> false_
     | "(" or_expr ")"
     | CNAME -> identifier

OR: "or" | "||"
AND: "and" | "&&"
NOT: "not" | "!"
TRUE: "true"
FALSE: "false"
COMPARATOR: ">=" | "<=" | "==" | "!=" | ">" | "<"
PLUS: "+"
MINUS: "-"
STAR: "*"
SLASH: "/"

%import common.CNAME
%import common.NUMBER
%import common.ESCAPED_STRING
%import common.WS
%ignore WS
"""

_parser = Lark(_GRAMMAR, parser="lalr")
_RESERVED = {"true", "false", "and", "or", "not"}


def _identifiers(expr: str) -> set[str]:
    tree = _parser.parse(expr)
    names: set[str] = set()
    for node in _walk(tree):
        if isinstance(node, Token) and node.type == "CNAME" and node.value not in _RESERVED:
            names.add(str(node.value))
    return names


def _walk(node: Tree[Token] | Token) -> list[Tree[Token] | Token]:
    if isinstance(node, Token):
        return [node]
    out: list[Tree[Token] | Token] = []
    for child in node.children:
        out.extend(_walk(child))
    return out


def check(ast: WorkflowAST) -> list[Diagnostic]:
    starts = [e for e in ast.elements if e.kind.value == "start_event"]
    if not starts:
        return []  # nothing to dominate from; L3 already reports STR-NO-START-EVENT

    graph = nx.DiGraph()
    graph.add_nodes_from(e.id for e in ast.elements)
    for flow in ast.flows:
        graph.add_edge(flow.source, flow.target)

    root = starts[0].id
    if root not in graph:
        return []
    reachable_from_root = nx.descendants(graph, root) | {root}

    writers_by_var: dict[str, set[str]] = {}
    for el in ast.elements:
        for var in el.variables_written:
            writers_by_var.setdefault(var, set()).add(el.id)

    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, str]] = set()

    def guaranteed_assigned(node: str, var: str) -> bool:
        writers = writers_by_var.get(var)
        if not writers:
            return False
        if root in writers:
            return True  # written at (or before) the very first step -- trivially on every path
        cut = writers - {node}  # a write AT node doesn't protect node's own read of the same var
        if not cut:
            return False
        reduced = graph.copy()
        reduced.remove_nodes_from(cut)  # root is never in `cut` -- excluded above when root writes `var`
        return node not in nx.descendants(reduced, root) | {root}

    for el in ast.elements:
        if el.id not in reachable_from_root:
            continue  # unreachable from start; L3 already reports this
        for var in el.variables_read:
            key = (el.id, var)
            if key in seen:
                continue
            seen.add(key)
            if not guaranteed_assigned(el.id, var):
                diagnostics.append(_violation(var, element_id=el.id, locator=el.locator))

    for flow in ast.flows:
        if not flow.condition_expr or flow.source not in reachable_from_root:
            continue
        try:
            names = _identifiers(flow.condition_expr)
        except LarkError:
            diagnostics.append(Diagnostic(
                code="FLW-EXPR-UNPARSEABLE", severity=Severity.INFO,
                message=f"Flow '{flow.id}' condition '{flow.condition_expr}' could not be parsed "
                "for dataflow analysis; it may use platform-specific syntax not yet understood.",
                suggested_fix=None, element_id=flow.id,
            ))
            continue
        for var in names:
            key = (flow.source, var)
            if key in seen:
                continue
            seen.add(key)
            source_el = ast.element(flow.source)
            if not guaranteed_assigned(flow.source, var):
                diagnostics.append(_violation(
                    var, element_id=flow.source,
                    locator=source_el.locator if source_el else None,
                    detail=f"in the condition of flow '{flow.id}'",
                ))
    return diagnostics


def _violation(var: str, *, element_id: str, locator: str | None, detail: str = "") -> Diagnostic:
    where = f" {detail}" if detail else ""
    return Diagnostic(
        code="FLW-VARIABLE-NOT-ASSIGNED", severity=Severity.WARNING,
        message=f"Variable '{var}' is read at '{element_id}'{where}, but no path from the start "
        f"event guarantees it was written first.",
        suggested_fix=f"Ensure every path reaching '{element_id}' writes '{var}' before it is read "
        f"-- e.g. add a default/initial assignment, or move the read after a gateway join where "
        f"all branches write it.",
        element_id=element_id, locator=locator,
    )


def score(diagnostics: list[Diagnostic]) -> float:
    """Heuristic, not calibrated -- see l3_structure.score()."""
    warnings = sum(1 for d in diagnostics if d.severity == Severity.WARNING)
    return round(1.0 / (1.0 + warnings), 4)
