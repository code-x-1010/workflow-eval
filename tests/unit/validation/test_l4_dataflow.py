"""L4 dataflow: hand-built cases plus the real fixture where a variable is
assigned on one branch only, per the charter's D7 requirement.
"""
from __future__ import annotations

from pathlib import Path

from wfeval.adapters.bpmn import parse
from wfeval.core.ast import Element, ElementKind, Flow, WorkflowAST

from services.validation.src import l4_dataflow

ROOT = Path(__file__).resolve().parents[3]


def _ast(elements: list[Element], flows: list[Flow]) -> WorkflowAST:
    return WorkflowAST(platform="uipath_maestro", process_id="p", elements=elements, flows=flows)


def _el(id_: str, kind: ElementKind, **kw: object) -> Element:
    return Element(id=id_, kind=kind, locator=f"/definitions/process/x[@id='{id_}']", **kw)  # type: ignore[arg-type]


def test_no_start_event_returns_nothing_l3_owns_that_diagnostic():
    ast = _ast([_el("t", ElementKind.SERVICE_TASK, variables_read=["x"])], [])
    assert l4_dataflow.check(ast) == []


def test_variable_written_before_read_on_a_linear_path_is_clean():
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT),
            _el("writer", ElementKind.SERVICE_TASK, variables_written=["amount"]),
            _el("reader", ElementKind.SERVICE_TASK, variables_read=["amount"]),
        ],
        [Flow(id="f1", source="s", target="writer"), Flow(id="f2", source="writer", target="reader")],
    )
    assert l4_dataflow.check(ast) == []


def test_variable_never_written_anywhere_is_flagged():
    ast = _ast(
        [_el("s", ElementKind.START_EVENT), _el("reader", ElementKind.SERVICE_TASK, variables_read=["amount"])],
        [Flow(id="f1", source="s", target="reader")],
    )
    diagnostics = l4_dataflow.check(ast)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "FLW-VARIABLE-NOT-ASSIGNED"
    assert diagnostics[0].element_id == "reader"
    assert diagnostics[0].severity.value == "warning"


def test_variable_written_on_only_one_branch_is_flagged():
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT),
            _el("split", ElementKind.GATEWAY_EXCLUSIVE),
            _el("a", ElementKind.SERVICE_TASK, variables_written=["risk_score"]),
            _el("b", ElementKind.SERVICE_TASK),
            _el("reader", ElementKind.SERVICE_TASK, variables_read=["risk_score"]),
        ],
        [
            Flow(id="f1", source="s", target="split"),
            Flow(id="f2", source="split", target="a", is_default=True),
            Flow(id="f3", source="split", target="b", condition_expr="false"),
            Flow(id="f4", source="a", target="reader"),
            Flow(id="f5", source="b", target="reader"),
        ],
    )
    diagnostics = l4_dataflow.check(ast)
    assert len(diagnostics) == 1
    assert diagnostics[0].element_id == "reader"


def test_variable_written_on_every_branch_is_clean():
    """Same shape as above, but both branches write the variable -- the read
    is safe regardless of which branch ran."""
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT),
            _el("split", ElementKind.GATEWAY_EXCLUSIVE),
            _el("a", ElementKind.SERVICE_TASK, variables_written=["risk_score"]),
            _el("b", ElementKind.SERVICE_TASK, variables_written=["risk_score"]),
            _el("reader", ElementKind.SERVICE_TASK, variables_read=["risk_score"]),
        ],
        [
            Flow(id="f1", source="s", target="split"),
            Flow(id="f2", source="split", target="a", is_default=True),
            Flow(id="f3", source="split", target="b", condition_expr="false"),
            Flow(id="f4", source="a", target="reader"),
            Flow(id="f5", source="b", target="reader"),
        ],
    )
    assert l4_dataflow.check(ast) == []


def test_flow_condition_expression_variables_are_checked():
    ast = _ast(
        [_el("s", ElementKind.START_EVENT), _el("gw", ElementKind.GATEWAY_EXCLUSIVE), _el("t", ElementKind.SERVICE_TASK)],
        [
            Flow(id="f1", source="s", target="gw"),
            Flow(id="f2", source="gw", target="t", condition_expr="amount > 10000"),
        ],
    )
    diagnostics = l4_dataflow.check(ast)
    assert len(diagnostics) == 1
    assert diagnostics[0].element_id == "gw"
    assert "amount" in diagnostics[0].message


def test_unparseable_condition_expression_is_info_not_a_violation():
    ast = _ast(
        [_el("s", ElementKind.START_EVENT), _el("gw", ElementKind.GATEWAY_EXCLUSIVE), _el("t", ElementKind.SERVICE_TASK)],
        [
            Flow(id="f1", source="s", target="gw"),
            Flow(id="f2", source="gw", target="t", condition_expr="amount ?? ~~ 10000"),
        ],
    )
    diagnostics = l4_dataflow.check(ast)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "FLW-EXPR-UNPARSEABLE"
    assert diagnostics[0].severity.value == "info"


def test_dataflow_fixture_flags_exactly_the_planted_gap():
    content = (ROOT / "tests/fixtures/bpmn/dataflow_variable_assigned_one_branch.bpmn").read_text()
    ast = parse(content, platform="uipath_maestro")
    diagnostics = l4_dataflow.check(ast)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "FLW-VARIABLE-NOT-ASSIGNED"
    assert diagnostics[0].element_id == "Task_review"
    assert "risk_score" in diagnostics[0].message


def test_score_reflects_finding_count():
    assert l4_dataflow.score([]) == 1.0
    content = (ROOT / "tests/fixtures/bpmn/dataflow_variable_assigned_one_branch.bpmn").read_text()
    ast = parse(content, platform="uipath_maestro")
    assert l4_dataflow.score(l4_dataflow.check(ast)) < 1.0


def test_real_clean_fixtures_have_no_dataflow_findings():
    """adapter_rich.bpmn declares every variable it reads via uipath:variables
    markers, dominated by the writer -- see the fixture's own docstring."""
    ast = parse((ROOT / "tests/fixtures/bpmn/adapter_rich.bpmn").read_text(), platform="uipath_maestro")
    assert l4_dataflow.check(ast) == []
