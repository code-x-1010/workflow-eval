# 0017 — Added `DMN` to `ValidationTier`; DMN artifacts run a separate two-tier path

**Author:** P1   **Date:** 2026-08-06   **Status:** accepted   **Affects:** P1, P4 (Gateway aggregation)

## Context

Charter D8 calls for DMN gap + overlap analysis (`DMN-INPUT-GAP`,
`DMN-RULE-OVERLAP`), and `wfeval.adapters` already accepted
`artifact.format: dmn` in its request shape from D2 -- but `/v1/validate`
silently ran the BPMN parser against it regardless (nothing in `main.py`
ever actually read `artifact.format`).

A decision table has no element graph. `L2` (asset references) and `L3`
(structure: start/end events, gateway balance) don't apply to it at all --
forcing DMN through the same four-tier ladder built for BPMN would mean
either lying about which tiers ran, or leaving `L2`/`L3` permanently in
`tiers_skipped` with a confusing "not applicable to this format" reason
wedged into a field designed for "not yet implemented" / "dependency down".

## Decision

- New module `wfeval.core.dmn`: `DecisionModel`/`Decision`/`DecisionTable`/
  `InputClause`/`OutputClause`/`Rule`/`HitPolicy`. Additive to the frozen D2
  core -- a new file, doesn't touch `ast.py` at all.
- New `wfeval.adapters.dmn.parse()`: real DMN 1.3 XML parsing (not a
  memory-reconstructed XSD validator, same conscious scope limit as
  `bpmn.py`'s L1 gap -- see that module's docstring).
- `wfeval.adapters.parse()` now actually dispatches on `format`: returns
  `WorkflowAST` for `bpmn` (unchanged, P3's existing call site is
  untouched) or `DecisionModel` for `dmn` (new).
- `services/validation/src/dmn_analysis.py`: gap/overlap analysis. Scoped to
  bare-number/comparison rule entries only -- FEEL range syntax and
  string/enum equality get a `DMN-ANALYSIS-SKIPPED` info note instead of a
  wrong or noisy finding. Ships at `warning`, same reasoning as L4 soundness.
- `/v1/validate` now branches on `artifact.format`. `dmn` gets its own path
  (`_validate_dmn` in `main.py`): `L1` (parse, reusing `SCH-PARSE-FAILED` and
  `gates.schema_validity` -- format-agnostic per `PREFIX_OWNER`) then `DMN`
  (gap/overlap). Default tiers when `options.tiers` is omitted: `[L1, L2,
  L3, L4]` for `bpmn` (unchanged), `[L1, DMN]` for `dmn` (new).
- Added `DMN` to `contracts/validation.openapi.yaml`'s `ValidationTier`
  enum. This is the shared, frozen-after-D2 contract, hence this record.

## Consequences

- Enum addition, not a removal/rename -- existing `L1`-`L4` consumers are
  unaffected. A DMN `ValidationReport` simply never contains `L2`/`L3` in
  either `tiers_run` or `tiers_skipped`, which is honest: those tiers don't
  exist for this format, rather than being skipped for some other reason.
- `scores.dmn_correctness` is a new score key, same status as
  `process_soundness`/`dataflow_correctness` (unweighted in P4's
  `weights.yaml`'s stopgap formula until P4 decides whether/how to fold it
  in -- not blocking, just flagging for P4's awareness).
- No DMN artifact exists yet in `contracts/examples/`, so nothing there
  needed regenerating.

## Sign-off

- [x] P1
- [ ] P4 — awareness (new unweighted score key `dmn_correctness`)
