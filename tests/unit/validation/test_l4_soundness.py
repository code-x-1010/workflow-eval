"""L4 soundness: hand-built Petri-net-shape cases plus the real deadlock
fixture, per the charter's D6-D7 requirement ("fixtures for deadlock and
dead-transition"). Most cases build a WorkflowAST directly, same convention
as test_l3_structure.py.
"""
from __future__ import annotations

from pathlib import Path

from services.validation.src import l4_soundness
from wfeval.adapters.bpmn import parse
from wfeval.core.ast import Element, ElementKind, Flow, WorkflowAST

ROOT = Path(__file__).resolve().parents[3]


def _ast(elements: list[Element], flows: list[Flow]) -> WorkflowAST:
    return WorkflowAST(platform="uipath_maestro", process_id="p", elements=elements, flows=flows)


def _el(id_: str, kind: ElementKind, **kw: object) -> Element:
    return Element(id=id_, kind=kind, locator=f"/definitions/process/x[@id='{id_}']", **kw)  # type: ignore[arg-type]


def test_simple_linear_process_is_sound():
    ast = _ast(
        [_el("s", ElementKind.START_EVENT), _el("t", ElementKind.SERVICE_TASK), _el("e", ElementKind.END_EVENT)],
        [Flow(id="f1", source="s", target="t"), Flow(id="f2", source="t", target="e")],
    )
    assert l4_soundness.check(ast) == []


def test_parallel_split_and_join_is_sound():
    """AND-split feeding an AND-join, correctly paired -- both branches always
    run, the join always gets both tokens. Sound."""
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT),
            _el("split", ElementKind.GATEWAY_PARALLEL),
            _el("a", ElementKind.SERVICE_TASK),
            _el("b", ElementKind.SERVICE_TASK),
            _el("join", ElementKind.GATEWAY_PARALLEL),
            _el("e", ElementKind.END_EVENT),
        ],
        [
            Flow(id="f1", source="s", target="split"),
            Flow(id="f2", source="split", target="a"),
            Flow(id="f3", source="split", target="b"),
            Flow(id="f4", source="a", target="join"),
            Flow(id="f5", source="b", target="join"),
            Flow(id="f6", source="join", target="e"),
        ],
    )
    assert l4_soundness.check(ast) == []


def test_xor_split_into_and_join_is_a_deadlock():
    """The anti-pattern: only one branch ever gets a token, but the join
    downstream waits for both. Not sound."""
    ast = _ast(
        [
            _el("s", ElementKind.START_EVENT),
            _el("split", ElementKind.GATEWAY_EXCLUSIVE),
            _el("a", ElementKind.SERVICE_TASK),
            _el("b", ElementKind.SERVICE_TASK),
            _el("join", ElementKind.GATEWAY_PARALLEL),
            _el("e", ElementKind.END_EVENT),
        ],
        [
            Flow(id="f1", source="s", target="split"),
            Flow(id="f2", source="split", target="a", is_default=True),
            Flow(id="f3", source="split", target="b", condition_expr="false"),
            Flow(id="f4", source="a", target="join"),
            Flow(id="f5", source="b", target="join"),
            Flow(id="f6", source="join", target="e"),
        ],
    )
    diagnostics = l4_soundness.check(ast)
    assert diagnostics
    assert all(d.severity.value == "warning" for d in diagnostics)
    codes = [d.code for d in diagnostics]
    assert codes[0] in ("FLW-DEAD-TRANSITION", "FLW-NOT-SOUND")


def test_deadlock_fixture_is_flagged():
    content = (ROOT / "tests/fixtures/bpmn/deadlock_xor_split_and_join.bpmn").read_text()
    ast = parse(content, platform="uipath_maestro")
    diagnostics = l4_soundness.check(ast)
    assert diagnostics
    assert all(d.severity.value == "warning" for d in diagnostics)


def test_score_is_lower_when_not_sound():
    assert l4_soundness.score([]) == 1.0
    content = (ROOT / "tests/fixtures/bpmn/deadlock_xor_split_and_join.bpmn").read_text()
    ast = parse(content, platform="uipath_maestro")
    assert l4_soundness.score(l4_soundness.check(ast)) < 1.0


def test_real_fixtures_are_sound():
    """Closes the loop against real XML, same convention as
    test_l3_structure.py's fixture tests at the bottom of that file."""
    for name in (
        "contracts/examples/artifact.bpmn",
        "tests/fixtures/spiff/executable_invoice.bpmn",
        "tests/fixtures/bpmn/adapter_rich.bpmn",
    ):
        ast = parse((ROOT / name).read_text(), platform="uipath_maestro")
        assert l4_soundness.check(ast) == [], f"{name} should be sound"
