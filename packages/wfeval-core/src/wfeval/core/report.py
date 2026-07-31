"""Report and scoring types. Assembled by the Gateway (P1) from all four services.

Each service returns its own slice; nobody returns the whole EvaluationReport
except the Gateway.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .diagnostics import Diagnostic
from .trace import RunnerFidelity, Trace


class Verdict(str, Enum):
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    FAIL = "fail"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------- per-service slices ----------

class ValidationReport(BaseModel):
    """P1 -> Gateway"""
    gates: dict[str, bool] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    ast_digest: str | None = None
    tiers_run: list[str] = Field(default_factory=list)
    tiers_skipped: dict[str, str] = Field(
        default_factory=dict, description="tier -> reason. e.g. L2 skipped when Sandbox asset registry is down."
    )


class IntentReport(BaseModel):
    """P2 -> Gateway"""
    scores: dict[str, float] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    judge_agreement: float | None = Field(
        None, description="Judge/human agreement on the calibration set. Ship the score WITH this or not at all."
    )
    spec_source: str = "extracted"


class ExecutionResult(BaseModel):
    case_id: str
    status: str = Field(..., description="pass | fail | error | skipped")
    failed_assertion: str | None = None
    expected_path: list[str] | None = None
    actual_path: list[str] | None = None


class ExecutionReport(BaseModel):
    """P3 -> Gateway"""
    gates: dict[str, bool] = Field(default_factory=dict)
    scores: dict[str, float | None] = Field(
        default_factory=dict,
        description="null for an unimplemented tier (e.g. 'robustness' before the stretch "
        "goal lands) -- never a default number that looks like a measurement.",
    )
    confidence: Confidence = Field(
        Confidence.MEDIUM,
        description="Never 'high' when fidelity != 'production' -- a substitute engine "
        "(Spiff) can't earn high confidence on its own, no matter how many cases pass.",
    )
    runner: str = Field(..., description="Execution engine used for this report, e.g. 'spiff' or 'uipath_maestro'.")
    fidelity: RunnerFidelity = Field(
        RunnerFidelity.REDUCED,
        description="'production' only when `runner` is the actual target platform engine "
        "(uipath_maestro). See docs/decisions/0002-spiff-primary-runner.md.",
    )
    results: list[ExecutionResult] = Field(default_factory=list)
    traces: list[Trace] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cap_confidence_on_reduced_fidelity(self) -> ExecutionReport:
        if self.fidelity != RunnerFidelity.PRODUCTION and self.confidence == Confidence.HIGH:
            raise ValueError(
                "ExecutionReport.confidence cannot be 'high' when fidelity is not "
                f"'production' (runner={self.runner!r}). A substitute engine cannot earn high "
                "confidence regardless of pass rate."
            )
        return self


class CostReport(BaseModel):
    """P4 -> Gateway"""
    currency: str = "USD"
    pricing_version: str
    confidence: Confidence = Confidence.LOW
    per_instance: dict[str, float] = Field(default_factory=dict, description="min / expected / max")
    expression: str | None = Field(None, description="Symbolic form when a term is unknown, e.g. '0.031 + 0.012*N'.")
    unbounded: bool = False
    by_resource: dict[str, float] = Field(default_factory=dict)
    hotspots: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(
        default_factory=list, description="MANDATORY when confidence is low. Never ship a bare number."
    )
    diagnostics: list[Diagnostic] = Field(default_factory=list)


# ---------- assembled ----------

class EvaluationReport(BaseModel):
    evaluation_id: str
    request_id: str
    platform: str
    verdict: Verdict
    scoring_version: str
    overall: float
    validation: ValidationReport | None = None
    intent: IntentReport | None = None
    execution: ExecutionReport | None = None
    cost: CostReport | None = None
    timings_ms: dict[str, int] = Field(default_factory=dict)
    short_circuited_at: str | None = Field(
        None, description="Which stage stopped the pipeline, if any. Downstream slices will be null."
    )
