"""Composite scoring. Owner: P4 (inside P1's service dir -- see AGENTS.md).

overall = 0 if any gate fails, else
    0.35*structural_soundness + 0.35*intent_coverage + 0.30*execution_pass_rate

Cost is deliberately NOT in `overall`: a cheap wrong workflow is not better than
an expensive correct one, and mixing them makes both numbers uninterpretable.

An unimplemented tier scores `null` -- never a default that looks like a
measurement.
"""
from __future__ import annotations

# TODO(P4 D5): load weights.yaml, stamp scoring_version on every report.
