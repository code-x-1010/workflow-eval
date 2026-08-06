"""ExecutionReport.confidence must never be 'high' on a non-production runner
-- see docs/decisions/0004-runner-fidelity.md. A substitute engine (Spiff)
cannot earn high confidence on its own, no matter how many cases pass.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wfeval.core.report import ExecutionReport


def test_reduced_fidelity_defaults_to_a_non_high_confidence():
    report = ExecutionReport(runner="spiff")
    assert report.fidelity == "reduced"
    assert report.confidence != "high"


def test_reduced_fidelity_rejects_high_confidence():
    with pytest.raises(ValidationError):
        ExecutionReport(runner="spiff", fidelity="reduced", confidence="high")


def test_production_fidelity_allows_high_confidence():
    report = ExecutionReport(runner="uipath_maestro", fidelity="production", confidence="high")
    assert report.confidence == "high"
