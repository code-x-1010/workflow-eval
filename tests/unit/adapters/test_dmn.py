"""wfeval-adapters DMN parser tests. See tests/fixtures/dmn/*.dmn headers for
what each fixture is for."""
from __future__ import annotations

from pathlib import Path

import pytest

from wfeval.adapters.dmn import parse
from wfeval.adapters.errors import AdapterParseError
from wfeval.core.dmn import HitPolicy

ROOT = Path(__file__).resolve().parents[3]
APPROVAL_DMN = (ROOT / "tests/fixtures/dmn/approval_decision.dmn").read_text()


def test_clean_fixture_parses():
    model = parse(APPROVAL_DMN)
    assert model.definitions_id == "Defs_approval"
    assert model.digest is not None and model.digest.startswith("sha256:")
    assert len(model.decisions) == 1

    decision = model.decisions[0]
    assert decision.id == "Decision_approval"
    assert decision.name == "Approval Decision"
    assert decision.locator == "/definitions/decision[@id='Decision_approval']"
    assert decision.table is not None
    assert decision.table.hit_policy == HitPolicy.UNIQUE


def test_input_output_clauses():
    table = parse(APPROVAL_DMN).decisions[0].table
    assert table is not None
    assert len(table.inputs) == 1
    assert table.inputs[0].expression == "amount"
    assert table.inputs[0].label == "Invoice amount"
    assert len(table.outputs) == 1
    assert table.outputs[0].name == "approved"


def test_rule_entries_and_wildcard():
    table = parse(APPROVAL_DMN).decisions[0].table
    assert table is not None
    assert len(table.rules) == 2
    low, high = table.rules
    assert low.input_entries == ["< 10000"]
    assert low.output_entries == ["true"]
    assert high.input_entries == [">= 10000"]

    range_dmn = (ROOT / "tests/fixtures/dmn/unsupported_range_syntax.dmn").read_text()
    table2 = parse(range_dmn).decisions[0].table
    assert table2 is not None
    assert table2.rules[1].input_entries == [None]  # "-" -> wildcard


def test_malformed_xml_raises():
    with pytest.raises(AdapterParseError, match="Malformed XML"):
        parse("<definitions><decision id='d'>")


def test_wrong_root_element_raises():
    with pytest.raises(AdapterParseError, match="Expected a DMN"):
        parse("<not-dmn/>")


def test_no_decisions_raises():
    with pytest.raises(AdapterParseError, match="No <decision>"):
        parse('<definitions id="d" xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"/>')


def test_missing_id_raises():
    with pytest.raises(AdapterParseError, match="no id"):
        parse('<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"/>')


def test_rule_with_wrong_entry_count_raises():
    bad = """<?xml version="1.0"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="d">
  <decision id="dec">
    <decisionTable id="t" hitPolicy="UNIQUE">
      <input id="i1"><inputExpression id="ie1"><text>amount</text></inputExpression></input>
      <output id="o1" name="approved"/>
      <rule id="r1">
        <outputEntry id="oe1"><text>true</text></outputEntry>
      </rule>
    </decisionTable>
  </decision>
</definitions>"""
    with pytest.raises(AdapterParseError, match="inputEntry"):
        parse(bad)


def test_unrecognized_hit_policy_raises():
    bad = """<?xml version="1.0"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="d">
  <decision id="dec">
    <decisionTable id="t" hitPolicy="NOT-A-REAL-POLICY">
      <input id="i1"><inputExpression id="ie1"><text>amount</text></inputExpression></input>
      <output id="o1" name="approved"/>
      <rule id="r1">
        <inputEntry id="ie2"><text>10</text></inputEntry>
        <outputEntry id="oe1"><text>true</text></outputEntry>
      </rule>
    </decisionTable>
  </decision>
</definitions>"""
    with pytest.raises(AdapterParseError, match="hitPolicy"):
        parse(bad)


def test_literal_expression_decision_has_no_table():
    """A <decision> using <literalExpression> instead of <decisionTable> is
    recognized, not rejected -- table stays None rather than guessed at."""
    content = """<?xml version="1.0"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="d">
  <decision id="dec" name="Computed">
    <literalExpression id="le1"><text>amount * 1.1</text></literalExpression>
  </decision>
</definitions>"""
    from wfeval.adapters.dmn import parse as parse_dmn
    model = parse_dmn(content)
    assert model.decisions[0].table is None


def test_dispatch_via_adapters_parse_returns_decision_model():
    from wfeval.adapters import parse as dispatch_parse
    from wfeval.core.dmn import DecisionModel
    result = dispatch_parse({"format": "dmn", "content": APPROVAL_DMN})
    assert isinstance(result, DecisionModel)
