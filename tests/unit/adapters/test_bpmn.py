"""wfeval-adapters BPMN parser tests.

Three fixtures, three jobs:
- contracts/examples/artifact.bpmn: the shared golden fixture. Structurally
  broken on purpose (see tests/fixtures/spiff/executable_invoice.bpmn's
  comment) -- the adapter must still parse it into an AST; catching the
  brokenness is L3's job (Validation), not this package's.
- tests/fixtures/spiff/executable_invoice.bpmn: same story, gateway-default
  and conditionExpression fixed -- proves default-flow and condition
  extraction against real, already-verified-executable markup.
- tests/fixtures/bpmn/adapter_rich.bpmn: this session's own fixture, covering
  everything the other two don't -- timer, multi-instance loop, agent-vs-
  service task, variable read/write markers. See its header comment for what
  is verified BPMN vs. provisional UiPath convention.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from wfeval.adapters.bpmn import parse
from wfeval.adapters.errors import AdapterParseError
from wfeval.core.ast import ElementKind

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_BPMN = (ROOT / "contracts/examples/artifact.bpmn").read_text()
EXECUTABLE_BPMN = (ROOT / "tests/fixtures/spiff/executable_invoice.bpmn").read_text()
RICH_BPMN = (ROOT / "tests/fixtures/bpmn/adapter_rich.bpmn").read_text()


def test_shared_golden_fixture_parses():
    ast = parse(ARTIFACT_BPMN)
    assert ast.process_id == "Process_invoice_approval"
    assert ast.platform == "uipath_maestro"
    assert len(ast.elements) == 7
    assert len(ast.flows) == 7
    assert ast.digest is not None and ast.digest.startswith("sha256:")
    assert all(e.locator for e in ast.elements)


def test_every_locator_is_id_qualified_and_matches_the_diagnostics_convention():
    ast = parse(ARTIFACT_BPMN)
    notify = ast.element("Task_notify")
    assert notify is not None
    assert notify.locator == "/definitions/process/serviceTask[@id='Task_notify']"


def test_default_flow_and_condition_expression_extracted():
    ast = parse(EXECUTABLE_BPMN)
    by_id = {f.id: f for f in ast.flows}
    assert by_id["Flow_4"].is_default is True
    assert by_id["Flow_3"].is_default is False
    assert by_id["Flow_3"].condition_expr == "amount > 10000"


def test_element_kind_mapping():
    ast = parse(RICH_BPMN)
    assert ast.element("Task_extract").kind == ElementKind.AGENT_TASK
    assert ast.element("Task_autopay").kind == ElementKind.SERVICE_TASK
    assert ast.element("Task_approval").kind == ElementKind.USER_TASK
    assert ast.element("Gateway_amount").kind == ElementKind.GATEWAY_EXCLUSIVE
    assert ast.element("Timer_approval_sla").kind == ElementKind.TIMER


def test_variables_read_and_written():
    ast = parse(RICH_BPMN)
    extract = ast.element("Task_extract")
    assert extract.variables_read == []
    assert extract.variables_written == ["vendor", "amount", "line_items"]

    approval = ast.element("Task_approval")
    assert approval.variables_read == ["amount"]
    assert approval.variables_written == ["approved"]


def test_asset_ref():
    ast = parse(RICH_BPMN)
    assert ast.element("Task_autopay").asset_ref == "ChargePayment"
    assert ast.element("Task_notify_line_item").asset_ref == "NotifyVendor"
    assert ast.element("Task_extract").asset_ref is None


def test_multi_instance_loop_with_symbolic_cardinality():
    ast = parse(RICH_BPMN)
    loop = ast.element("Task_notify_line_item").loop
    assert loop is not None
    assert loop.cardinality_expr == "line_items.count"
    assert loop.max_iterations is None
    assert loop.is_parallel is True


def test_elements_without_loop_characteristics_have_no_loop_spec():
    ast = parse(RICH_BPMN)
    assert ast.element("Task_extract").loop is None


def test_timer_expression_extracted():
    ast = parse(RICH_BPMN)
    timer = ast.element("Timer_approval_sla")
    assert timer.attributes["timer_type"] == "duration"
    assert timer.attributes["timer_expression"] == "P2D"


def test_uipath_extension_attributes_captured_generically():
    ast = parse(RICH_BPMN)
    attrs = ast.element("Task_autopay").attributes
    assert attrs["activityType"] == "Process"
    assert attrs["assetRef"] == "ChargePayment"


def test_malformed_xml_raises_adapter_parse_error():
    with pytest.raises(AdapterParseError):
        parse("<definitions><process id='p'>")


def test_missing_process_raises_adapter_parse_error():
    with pytest.raises(AdapterParseError):
        parse('<?xml version="1.0"?><definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"/>')


def test_unsupported_element_raises_rather_than_silently_dropping():
    xml = """<?xml version="1.0"?>
    <definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
      <process id="p">
        <startEvent id="s"/>
        <callActivity id="ca" name="Sub-process call"/>
      </process>
    </definitions>"""
    with pytest.raises(AdapterParseError, match="callActivity"):
        parse(xml)


def test_unsupported_event_definition_raises_rather_than_silently_dropping():
    xml = """<?xml version="1.0"?>
    <definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
      <process id="p">
        <intermediateCatchEvent id="msg">
          <messageEventDefinition/>
        </intermediateCatchEvent>
      </process>
    </definitions>"""
    with pytest.raises(AdapterParseError, match="messageEventDefinition|intermediateCatchEvent"):
        parse(xml)


def test_platform_is_passed_through():
    ast = parse(ARTIFACT_BPMN, platform="n8n")
    assert ast.platform == "n8n"
