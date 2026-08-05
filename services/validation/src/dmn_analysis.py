"""DMN gap + overlap analysis (charter D8).

Two questions per decision table:
  - **Gap**: is there an input value no rule covers at all?
  - **Overlap**: can two rules both match the same input, which is
    ambiguous under a hit policy that expects at most one match?

Scope, deliberately limited rather than guessed at (same house rule as
l1_schema.py's XSD gap and l4_soundness.py's inclusive-gateway
approximation): this only understands rule entries that are a bare number
(equality) or a `<`/`<=`/`>`/`>=` comparison against a number. FEEL range
syntax (`[10000..20000)`), string/enum equality, and anything else is left
alone -- a decision table using them gets a single `DMN-ANALYSIS-SKIPPED`
info note instead of wrong or noisy findings. **Overlap** detection works
across any number of input columns once every entry parses. **Gap**
detection only runs on single-input tables -- multi-column coverage is a
genuinely different (Cartesian interval-set) algorithm, not implemented.
All uncovered ranges for one decision are bundled into a single
`DMN-INPUT-GAP` diagnostic rather than one per range, so a table with many
small gaps doesn't flood the report.

Overlap is only checked for hit policies where it's actually a problem
(`UNIQUE`, `FIRST`, `PRIORITY`). `ANY`/`COLLECT`/`RULE ORDER`/`OUTPUT ORDER`
are explicitly designed to tolerate multiple matches.

Ships at `warning` severity, same reasoning as l4_soundness.py: the interval
model here is an approximation of FEEL semantics, not a full evaluator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from wfeval.adapters.dmn import parse as parse_dmn
from wfeval.adapters.errors import AdapterParseError
from wfeval.core.diagnostics import Diagnostic, Severity
from wfeval.core.dmn import Decision, DecisionModel, DecisionTable, HitPolicy, Rule

_OVERLAP_SENSITIVE = {HitPolicy.UNIQUE, HitPolicy.FIRST, HitPolicy.PRIORITY}


def check_schema(content: str) -> tuple[DecisionModel | None, list[Diagnostic], bool]:
    """Same shape/contract as l1_schema.check(): (model, diagnostics,
    schema_validity). model is None only when parsing failed outright --
    callers must not run gap/overlap analysis in that case."""
    try:
        model = parse_dmn(content)
    except AdapterParseError as e:
        return None, [Diagnostic(
            code="SCH-PARSE-FAILED", severity=Severity.ERROR, message=str(e),
            suggested_fix="Fix the reported XML/DMN construct and resubmit. Gap/overlap analysis "
            "does not run against an artifact that fails to parse.",
        )], False
    return model, [], True


@dataclass(frozen=True)
class _Interval:
    lo: float
    hi: float
    lo_inclusive: bool
    hi_inclusive: bool


_WILDCARD = _Interval(-math.inf, math.inf, True, True)


class _Unparseable(Exception):
    pass


def check(model: DecisionModel) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for decision in model.decisions:
        if decision.table is not None:
            diagnostics.extend(_check_table(decision, decision.table))
    return diagnostics


def score(diagnostics: list[Diagnostic]) -> float:
    """Heuristic, not calibrated -- see l3_structure.score()."""
    warnings = sum(1 for d in diagnostics if d.severity == Severity.WARNING)
    return round(1.0 / (1.0 + warnings), 4)


def _check_table(decision: Decision, table: DecisionTable) -> list[Diagnostic]:
    try:
        parsed = [(rule, [_parse_entry(e) for e in rule.input_entries]) for rule in table.rules]
    except _Unparseable as e:
        return [Diagnostic(
            code="DMN-ANALYSIS-SKIPPED", severity=Severity.INFO,
            message=f"Decision '{decision.name or decision.id}': gap/overlap analysis skipped -- "
            f"input entry {e.args[0]!r} uses FEEL syntax this analysis doesn't parse (only bare "
            f"numbers and <, <=, >, >= comparisons are supported).",
            suggested_fix=None, element_id=decision.id, locator=decision.locator,
        )]

    diagnostics = _overlap(decision, table, parsed)
    if len(table.inputs) == 1:
        diagnostics += _gap(decision, table, parsed)
    return diagnostics


def _overlap(
    decision: Decision, table: DecisionTable, parsed: list[tuple[Rule, list[_Interval]]],
) -> list[Diagnostic]:
    if table.hit_policy not in _OVERLAP_SENSITIVE:
        return []
    diagnostics: list[Diagnostic] = []
    for i in range(len(parsed)):
        rule_a, intervals_a = parsed[i]
        for j in range(i + 1, len(parsed)):
            rule_b, intervals_b = parsed[j]
            if all(_intersects(a, b) for a, b in zip(intervals_a, intervals_b)):
                consequence = (
                    "exactly one match is required" if table.hit_policy == HitPolicy.UNIQUE
                    else "the result depends on rule order, which is easy to get wrong silently"
                )
                diagnostics.append(Diagnostic(
                    code="DMN-RULE-OVERLAP", severity=Severity.WARNING,
                    message=f"Rules '{rule_a.id}' and '{rule_b.id}' in decision "
                    f"'{decision.name or decision.id}' can both match the same input under hit "
                    f"policy {table.hit_policy.value} -- {consequence}.",
                    suggested_fix=f"Narrow the input conditions on '{rule_a.id}' and '{rule_b.id}' "
                    f"so they can't both match, or change the hit policy if overlap is intended.",
                    element_id=rule_a.id, locator=rule_a.locator,
                ))
    return diagnostics


def _gap(
    decision: Decision, table: DecisionTable, parsed: list[tuple[Rule, list[_Interval]]],
) -> list[Diagnostic]:
    intervals = sorted((intervals[0] for _, intervals in parsed), key=lambda iv: iv.lo)
    covered_until = -math.inf
    gaps: list[str] = []
    for iv in intervals:
        if iv.lo > covered_until:
            gaps.append(_describe_gap(covered_until, iv.lo))
        covered_until = max(covered_until, iv.hi)
    if covered_until < math.inf:
        gaps.append(_describe_gap(covered_until, math.inf))
    if not gaps:
        return []

    label = table.inputs[0].label or table.inputs[0].expression
    return [Diagnostic(
        code="DMN-INPUT-GAP", severity=Severity.WARNING,
        message=f"Decision '{decision.name or decision.id}': no rule covers {label} for "
        f"{', '.join(gaps)}.",
        suggested_fix=f"Add a rule covering {gaps[0]} for '{label}', or confirm those values "
        f"genuinely can't occur.",
        element_id=decision.id, locator=decision.locator,
    )]


def _describe_gap(lo: float, hi: float) -> str:
    lo_s = "-inf" if lo == -math.inf else str(lo)
    hi_s = "+inf" if hi == math.inf else str(hi)
    return f"({lo_s}, {hi_s})"


def _intersects(a: _Interval, b: _Interval) -> bool:
    lo = max(a.lo, b.lo)
    hi = min(a.hi, b.hi)
    if lo < hi:
        return True
    if lo > hi:
        return False
    a_incl = a.lo_inclusive if lo == a.lo else a.hi_inclusive
    b_incl = b.lo_inclusive if lo == b.lo else b.hi_inclusive
    return a_incl and b_incl


def _parse_entry(entry: str | None) -> _Interval:
    if entry is None:
        return _WILDCARD
    text = entry.strip()
    if text.startswith("<="):
        return _Interval(-math.inf, _as_float(text[2:]), True, True)
    if text.startswith(">="):
        return _Interval(_as_float(text[2:]), math.inf, True, True)
    if text.startswith("<"):
        return _Interval(-math.inf, _as_float(text[1:]), True, False)
    if text.startswith(">"):
        return _Interval(_as_float(text[1:]), math.inf, False, True)
    n = _as_float(text)
    return _Interval(n, n, True, True)


def _as_float(text: str) -> float:
    try:
        return float(text.strip())
    except ValueError:
        raise _Unparseable(text.strip()) from None
