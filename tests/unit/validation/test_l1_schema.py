"""One broken-BPMN case per SCH-* code, per the charter's D4-D5 requirement."""
from __future__ import annotations

from pathlib import Path

from services.validation.src import l1_schema

ROOT = Path(__file__).resolve().parents[3]
GOOD_BPMN = (ROOT / "contracts/examples/artifact.bpmn").read_text()

DUPLICATE_ID_BPMN = """<?xml version="1.0"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <process id="p">
    <startEvent id="s"/>
    <serviceTask id="dup" name="First"/>
    <serviceTask id="dup" name="Second"/>
    <endEvent id="e"/>
    <sequenceFlow id="f1" sourceRef="s" targetRef="dup"/>
    <sequenceFlow id="f2" sourceRef="dup" targetRef="e"/>
  </process>
</definitions>"""


def test_sch_parse_failed_on_malformed_xml():
    ast, diagnostics, schema_validity = l1_schema.check("<definitions><process id='p'>", platform="uipath_maestro")
    assert ast is None
    assert schema_validity is False
    assert diagnostics[0].code == "SCH-PARSE-FAILED"
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].suggested_fix


def test_sch_duplicate_id():
    ast, diagnostics, schema_validity = l1_schema.check(DUPLICATE_ID_BPMN, platform="uipath_maestro")
    assert ast is not None  # the adapter itself doesn't reject duplicate ids
    assert schema_validity is False
    codes = [d.code for d in diagnostics]
    assert "SCH-DUPLICATE-ID" in codes
    dup = next(d for d in diagnostics if d.code == "SCH-DUPLICATE-ID")
    assert dup.element_id == "dup"
    assert dup.suggested_fix


def test_valid_artifact_has_no_sch_diagnostics_and_is_schema_valid():
    ast, diagnostics, schema_validity = l1_schema.check(GOOD_BPMN, platform="uipath_maestro")
    assert ast is not None
    assert diagnostics == []
    assert schema_validity is True
