"""DMN gap + overlap analysis. Most cases build a DecisionModel directly,
same convention as test_l3_structure.py; the three fixture tests at the
bottom close the loop against real XML."""
from __future__ import annotations

from pathlib import Path

from wfeval.adapters.dmn import parse
from wfeval.core.dmn import Decision, DecisionModel, DecisionTable, HitPolicy, InputClause, OutputClause, Rule

from services.validation.src import dmn_analysis

ROOT = Path(__file__).resolve().parents[3]


def _model(table: DecisionTable) -> DecisionModel:
    return DecisionModel(definitions_id="d", decisions=[Decision(id="dec", table=table)])


def _table(rules: list[Rule], *, hit_policy: HitPolicy = HitPolicy.UNIQUE, n_inputs: int = 1) -> DecisionTable:
    inputs = [InputClause(id=f"i{i}", expression=f"x{i}") for i in range(n_inputs)]
    return DecisionTable(hit_policy=hit_policy, inputs=inputs, outputs=[OutputClause(id="o", name="out")], rules=rules)


def test_full_coverage_no_gap():
    table = _table([
        Rule(id="r1", input_entries=["< 10"], output_entries=["a"]),
        Rule(id="r2", input_entries=[">= 10"], output_entries=["b"]),
    ])
    assert dmn_analysis.check(_model(table)) == []


def test_gap_in_the_middle():
    table = _table([
        Rule(id="r1", input_entries=["< 5"], output_entries=["a"]),
        Rule(id="r2", input_entries=[">= 10"], output_entries=["b"]),
    ])
    diagnostics = dmn_analysis.check(_model(table))
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DMN-INPUT-GAP"
    assert "5.0" in diagnostics[0].message and "10.0" in diagnostics[0].message


def test_gap_at_the_edges():
    """Only one rule, covering a single point -- everything else is a gap.
    Both uncovered ranges are bundled into one diagnostic per decision
    (avoids one diagnostic per gap flooding a table with many small gaps)."""
    table = _table([Rule(id="r1", input_entries=["10"], output_entries=["a"])])
    diagnostics = dmn_analysis.check(_model(table))
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DMN-INPUT-GAP"
    assert "-inf, 10.0" in diagnostics[0].message
    assert "10.0, +inf" in diagnostics[0].message


def test_wildcard_covers_everything():
    table = _table([Rule(id="r1", input_entries=[None], output_entries=["a"])])
    assert dmn_analysis.check(_model(table)) == []


def test_overlap_under_unique_is_flagged():
    table = _table([
        Rule(id="r1", input_entries=["< 10"], output_entries=["a"]),
        Rule(id="r2", input_entries=[">= 8"], output_entries=["b"]),
    ])
    diagnostics = dmn_analysis.check(_model(table))
    codes = [d.code for d in diagnostics]
    assert "DMN-RULE-OVERLAP" in codes


def test_no_overlap_when_disjoint():
    table = _table([
        Rule(id="r1", input_entries=["< 10"], output_entries=["a"]),
        Rule(id="r2", input_entries=[">= 10"], output_entries=["b"]),
    ])
    diagnostics = dmn_analysis.check(_model(table))
    assert not any(d.code == "DMN-RULE-OVERLAP" for d in diagnostics)


def test_overlap_not_flagged_for_any_hit_policy():
    """ANY explicitly tolerates multiple matches -- not a defect."""
    table = _table(
        [Rule(id="r1", input_entries=["< 10"], output_entries=["a"]),
         Rule(id="r2", input_entries=[">= 8"], output_entries=["b"])],
        hit_policy=HitPolicy.ANY,
    )
    assert dmn_analysis.check(_model(table)) == []


def test_multi_column_overlap_requires_every_column_to_intersect():
    table = _table(
        [Rule(id="r1", input_entries=["< 10", "< 10"], output_entries=["a"]),
         Rule(id="r2", input_entries=[">= 8", ">= 20"], output_entries=["b"])],
        n_inputs=2,
    )
    # column 0 overlaps ([8,10)); column 1 does not (<10 vs >=20) -> disjoint overall
    diagnostics = dmn_analysis.check(_model(table))
    assert not any(d.code == "DMN-RULE-OVERLAP" for d in diagnostics)


def test_multi_input_table_skips_gap_analysis():
    """Gap detection only runs on single-input tables -- documented scope limit."""
    table = _table(
        [Rule(id="r1", input_entries=["< 10", "< 10"], output_entries=["a"])],
        n_inputs=2,
    )
    assert not any(d.code == "DMN-INPUT-GAP" for d in dmn_analysis.check(_model(table)))


def test_unparseable_entry_skips_analysis_with_info_diagnostic():
    table = _table([Rule(id="r1", input_entries=["[10..20)"], output_entries=["a"])])
    diagnostics = dmn_analysis.check(_model(table))
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DMN-ANALYSIS-SKIPPED"
    assert diagnostics[0].severity.value == "info"


def test_score_reflects_finding_count():
    assert dmn_analysis.score([]) == 1.0
    table = _table([Rule(id="r1", input_entries=["< 5"], output_entries=["a"]),
                     Rule(id="r2", input_entries=[">= 10"], output_entries=["b"])])
    assert dmn_analysis.score(dmn_analysis.check(_model(table))) < 1.0


def test_clean_fixture_has_no_findings():
    model = parse((ROOT / "tests/fixtures/dmn/approval_decision.dmn").read_text())
    assert dmn_analysis.check(model) == []


def test_gap_fixture_is_flagged():
    model = parse((ROOT / "tests/fixtures/dmn/gap_missing_middle_range.dmn").read_text())
    diagnostics = dmn_analysis.check(model)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DMN-INPUT-GAP"


def test_overlap_fixture_is_flagged():
    model = parse((ROOT / "tests/fixtures/dmn/overlap_two_rules_match.dmn").read_text())
    diagnostics = dmn_analysis.check(model)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "DMN-RULE-OVERLAP"
