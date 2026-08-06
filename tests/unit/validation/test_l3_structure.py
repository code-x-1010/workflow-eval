"""One broken-BPMN case per STR-* code, per the charter's D4-D5 requirement.

Most cases build a WorkflowAST directly -- l3_structure.check() operates on
the AST, not raw XML, and hand-built ASTs make each broken scenario a single
obvious line rather than a full BPMN document. The two real-fixture tests at
the bottom close the loop against actual XML: the shared artifact.bpmn (which
has a planted defect -- see tests/fixtures/spiff/executable_invoice.bpmn's
comment) and its fixed counterpart.
"""
from __future__ import annotations

from pathlib import Path

from services.validation.src import l3_structure
from wfeval.adapters.bpmn import parse
from wfeval.core.ast import Element, ElementKind, Flow, WorkflowAST

ROOT = Path(__file__).resolve().parents[3]


def _ast(elements: list[Element], flows: list[Flow]) -> WorkflowAST:
    return WorkflowAST(platform="uipath_maestro", process_id="p", elements=elements, flows=flows)


def _el(id_: str, kind: ElementKind, **kw: object) -> Element:
    return Element(id=id_, kind=kind, locator=f"/definitions/process/x[@id='{id_}']", **kw)  # type: ignore[arg-type]


def test_str_no_start_event():
    ast = _ast([_el("e", ElementKind.END_EVENT)], [])
    diagnostics = l3_structure.check(ast)
    assert any(d.code == "STR-NO-START-EVENT" for d in diagnostics)


def test_str_multiple_start_events():
    ast = _ast([_el("s1", ElementKind.START_EVENT), _el("s2", ElementKind.START_EVENT)], [])
    diagnostics = l3_structure.check(ast)
    codes = [d.code for d in diagnostics]
    assert "STR-MULTIPLE-START-EVENTS" in codes


def test_str_unreachable_task():
    ast = _ast(
        [_el("s", ElementKind.START_EVENT), _el("e", ElementKind.END_EVENT), _el("orphan", ElementKind.SERVICE_TASK)],
        [Flow(id="f1", source="s", target="e")],
    )
    diagnostics = l3_structure.check(ast)
    unreachable = [d for d in diagnostics if d.code == "STR-UNREACHABLE-TASK"]
    assert len(unreachable) == 1
    assert unreachable[0].element_id == "orphan"
    assert unreachable[0].severity == "warning"


def test_str_no_end_event_when_none_exists():
    ast = _ast([_el("s", ElementKind.START_EVENT)], [])
    diagnostics = l3_structure.check(ast)
    assert any(d.code == "STR-NO-END-EVENT" and d.element_id is None for d in diagnostics)


def test_str_no_end_event_on_dead_end_mid_path():
    ast = _ast(
        [_el("s", ElementKind.START_EVENT), _el("dead", ElementKind.SERVICE_TASK), _el("e", ElementKind.END_EVENT)],
        [Flow(id="f1", source="s", target="dead")],  # "dead" has no outgoing flow; "e" is unreachable
    )
    diagnostics = l3_structure.check(ast)
    dead_end = [d for d in diagnostics if d.code == "STR-NO-END-EVENT" and d.element_id == "dead"]
    assert len(dead_end) == 1


def test_str_gateway_no_default():
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT), _el("g", ElementKind.GATEWAY_EXCLUSIVE),
            _el("a", ElementKind.SERVICE_TASK), _el("b", ElementKind.SERVICE_TASK), _el("e", ElementKind.END_EVENT),
        ],
        [
            Flow(id="f1", source="s", target="g"),
            Flow(id="f2", source="g", target="a"),  # no condition, no default
            Flow(id="f3", source="g", target="b"),  # no condition, no default
            Flow(id="f4", source="a", target="e"), Flow(id="f5", source="b", target="e"),
        ],
    )
    diagnostics = l3_structure.check(ast)
    assert any(d.code == "STR-GATEWAY-NO-DEFAULT" and d.element_id == "g" for d in diagnostics)


def test_str_gateway_no_default_not_raised_when_default_present():
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT), _el("g", ElementKind.GATEWAY_EXCLUSIVE),
            _el("a", ElementKind.SERVICE_TASK), _el("b", ElementKind.SERVICE_TASK), _el("e", ElementKind.END_EVENT),
        ],
        [
            Flow(id="f1", source="s", target="g"),
            Flow(id="f2", source="g", target="a", is_default=True),
            Flow(id="f3", source="g", target="b", condition_expr="x > 1"),
            Flow(id="f4", source="a", target="e"), Flow(id="f5", source="b", target="e"),
        ],
    )
    diagnostics = l3_structure.check(ast)
    assert not any(d.code == "STR-GATEWAY-NO-DEFAULT" for d in diagnostics)


def test_str_gateway_unexpected_condition():
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT), _el("g", ElementKind.GATEWAY_PARALLEL),
            _el("a", ElementKind.SERVICE_TASK), _el("b", ElementKind.SERVICE_TASK), _el("e", ElementKind.END_EVENT),
        ],
        [
            Flow(id="f1", source="s", target="g"),
            Flow(id="f2", source="g", target="a", condition_expr="x > 1"),  # parallel gateways ignore conditions
            Flow(id="f3", source="g", target="b"),
            Flow(id="f4", source="a", target="e"), Flow(id="f5", source="b", target="e"),
        ],
    )
    diagnostics = l3_structure.check(ast)
    assert any(d.code == "STR-GATEWAY-UNEXPECTED-CONDITION" and d.element_id == "g" for d in diagnostics)


def test_str_timer_missing_value():
    ast = _ast(
        [_el("s", ElementKind.START_EVENT), _el("t", ElementKind.TIMER), _el("e", ElementKind.END_EVENT)],
        [Flow(id="f1", source="s", target="t"), Flow(id="f2", source="t", target="e")],
    )
    diagnostics = l3_structure.check(ast)
    assert any(d.code == "STR-TIMER-MISSING-VALUE" and d.element_id == "t" for d in diagnostics)


def test_str_timer_invalid_iso8601():
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT),
            _el("t", ElementKind.TIMER, attributes={"timer_type": "duration", "timer_expression": "next tuesday"}),
            _el("e", ElementKind.END_EVENT),
        ],
        [Flow(id="f1", source="s", target="t"), Flow(id="f2", source="t", target="e")],
    )
    diagnostics = l3_structure.check(ast)
    assert any(d.code == "STR-TIMER-INVALID-ISO8601" and d.element_id == "t" for d in diagnostics)


def test_str_timer_valid_iso8601_duration_raises_nothing():
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT),
            _el("t", ElementKind.TIMER, attributes={"timer_type": "duration", "timer_expression": "P2D"}),
            _el("e", ElementKind.END_EVENT),
        ],
        [Flow(id="f1", source="s", target="t"), Flow(id="f2", source="t", target="e")],
    )
    diagnostics = l3_structure.check(ast)
    assert not any(d.code.startswith("STR-TIMER") for d in diagnostics)


# ---------- against real fixtures ----------

def test_shared_artifact_bpmn_flags_its_planted_gateway_defect():
    ast = parse((ROOT / "contracts/examples/artifact.bpmn").read_text())
    diagnostics = l3_structure.check(ast)
    assert any(d.code == "STR-GATEWAY-NO-DEFAULT" and d.element_id == "Gateway_amount" for d in diagnostics)


def test_executable_invoice_bpmn_is_structurally_clean():
    ast = parse((ROOT / "tests/fixtures/spiff/executable_invoice.bpmn").read_text())
    diagnostics = l3_structure.check(ast)
    assert diagnostics == []
    assert l3_structure.score(diagnostics, len(ast.elements)) == 1.0
