"""Sandbox execution. The only service holding UiPath credentials.

Service: sandbox  |  Port: 8003  |  Owner: P3
Charter: docs/agents/P3-*.md      Contract: contracts/sandbox.openapi.yaml

Spiff is the PRIMARY runner (runners/spiff/): free, local, seconds,
CI-friendly, no consumption units, no tenant required. UiPath
(runners/uipath/) is a DEFERRED stub -- we have no sandbox tenant. See
docs/decisions/0002-spiff-primary-runner.md and docs/agents/P3-sandbox.md.

L5 platform acceptance ("does this artifact actually deploy to Maestro") is
the one thing Spiff cannot substitute for. /v1/deploy below is a pass-through
no-op until a tenant exists -- deferred, not deleted.
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI
from wfeval.core.diagnostics import Diagnostic, Severity
from wfeval.core.report import ExecutionReport, ExecutionResult
from wfeval.core.stubs import golden
from wfeval.core.testcase import MockDefinition, TestCase
from wfeval.core.trace import RunnerFidelity

from .runners.spiff.engine import RUNNER_NAME
from .runners.spiff.runner import SpiffRunner

app = FastAPI(title="wfeval-sandbox", version="0.1.0")

SERVICE = "sandbox"
OWNER = "P3"

_RUNNER = SpiffRunner()
# execution_id -> ExecutionReport, JSON-mode dumped. In-memory is fine for a
# single-process dev service; a real queue is only worth building the day
# this needs to survive a restart or scale past one worker -- Spiff being
# seconds-fast removed the original reason (a slow UiPath run) to build one
# on D7 as originally planned.
_EXECUTIONS: dict[str, dict] = {}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/deploy")
def deploy(body: dict) -> dict:
    """L5 platform acceptance -- DEFERRED, not deleted. We have no UiPath
    sandbox tenant (see docs/decisions/0002-spiff-primary-runner.md). Spiff
    cannot substitute for this: it never talks to Maestro, so it has no way to
    know whether Maestro would actually accept the artifact. Always accepts
    for now; real acceptance checking resumes the day runners/uipath/ stops
    raising NotImplementedError.
    """
    return {
        "accepted": True,
        "diagnostics": [Diagnostic(
            code="PLT-DEPLOY-DEFERRED", severity=Severity.INFO,
            message="No UiPath sandbox tenant configured; deploy acceptance was not checked.",
            suggested_fix="None required from the generator. This artifact has not been "
                           "verified against the real uipath_maestro deploy path -- treat "
                           "platform_acceptance as unverified, not confirmed, until it has.",
        ).model_dump(mode="json")],
    }


@app.post("/v1/executions")
def start_execution(body: dict) -> dict:
    execution_id = f"ex_{uuid.uuid4().hex[:8]}"
    artifact = body.get("artifact", {})
    test_cases = [TestCase(**tc) for tc in body.get("test_cases", [])]
    mocks = [MockDefinition(**m) for m in body.get("mocks", [])]
    timeout_s = body.get("timeout_s", 60)

    # Spiff is the fast tier -- seconds, not minutes -- so there's no real
    # need to defer this onto a worker queue the way a UiPath run would need.
    # Kept 202-shaped for contract parity with the (future) UiPath runner.
    report = _run_report(artifact, test_cases, mocks, timeout_s)
    _EXECUTIONS[execution_id] = report.model_dump(mode="json")
    return {"execution_id": execution_id, "poll_url": f"/v1/executions/{execution_id}"}


@app.get("/v1/executions/{execution_id}")
def get_execution(execution_id: str) -> dict:
    if execution_id in _EXECUTIONS:
        return _EXECUTIONS[execution_id]
    # Unknown id (including the conventional ex_stub_0001): still contract-valid,
    # never a hang -- WFEVAL_STUB_DEPS callers get the golden example.
    return golden("execution.response.json")


@app.get("/v1/assets")
def assets() -> dict:
    # Consumed by P1's L2 reference checks. Spiff has no orchestrator asset
    # folder concept, so this stays a golden stub until there's a real
    # registry to back it -- tracked in docs/agents/P3-sandbox.md, not blocking.
    return golden("assets.response.json")


def _run_report(
    artifact: dict, test_cases: list[TestCase], mocks: list[MockDefinition], timeout_s: int,
) -> ExecutionReport:
    results: list[ExecutionResult] = []
    traces = []
    diagnostics: list[Diagnostic] = []
    passed = 0

    for tc in test_cases:
        trace, case_diagnostics, status, failed_assertion = _RUNNER.execute(artifact, tc, mocks, timeout_s)
        traces.append(trace)
        diagnostics.extend(case_diagnostics)
        results.append(ExecutionResult(
            case_id=tc.case_id, status=status, failed_assertion=failed_assertion, actual_path=trace.path,
        ))
        if status == "pass":
            passed += 1

    scored = [r for r in results if r.status in ("pass", "fail")]
    pass_rate = (passed / len(scored)) if scored else None

    return ExecutionReport(
        # Mirrors /v1/deploy's deferred, always-accepted result -- see the
        # docstring on `deploy()` above. Not re-checked here.
        gates={"platform_acceptance": True},
        scores={"execution_pass_rate": pass_rate} if pass_rate is not None else {},
        confidence="medium",  # fidelity=reduced caps this below "high" -- enforced in report.py
        runner=RUNNER_NAME,
        fidelity=RunnerFidelity.REDUCED,
        results=results,
        traces=traces,
        diagnostics=diagnostics,
    )
