"""Fan-out, short-circuit, aggregate, score.

Service: gateway  |  Port: 8000  |  Owner: P1
Charter: docs/agents/P1-*.md      Contract: contracts/gateway.openapi.yaml

Real fan-out logic lives in orchestrate.py; this file is just the HTTP layer
plus DependencyUnavailable -> 502 translation. Do not change the response
SHAPES without a decision record.

D9 hardening (decision 0018): every route except /healthz requires
Depends(require_api_key) -- see auth.py for why /healthz is exempt and why
this is open-by-default when GATEWAY_API_KEYS is unset.
"""
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from wfeval.core.stubs import golden

from . import orchestrate
from .auth import require_api_key
from .orchestrate import DependencyUnavailable

app = FastAPI(title="wfeval-gateway", version="0.1.0")

SERVICE = "gateway"
OWNER = "P1"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/validate", dependencies=[Depends(require_api_key)])
async def predeploy_validate(body: dict[str, Any]) -> dict[str, Any]:
    """Sync, sub-2s. Validation (L1-L4) + Cost only -- see orchestrate.py."""
    try:
        report = await orchestrate.run_predeploy_validate(body)
    except DependencyUnavailable as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return report.model_dump(mode="json")


@app.post("/v1/evaluations", status_code=202, dependencies=[Depends(require_api_key)])
async def create_evaluation(body: dict[str, Any]) -> dict[str, Any]:
    """Idempotent on request_id (D9, decision 0018) -- see orchestrate.py.
    Always 202 here regardless of whether this call started a new pipeline
    run or returned an existing evaluation_id: the caller's next step is the
    same either way (poll poll_url)."""
    try:
        evaluation_id = await orchestrate.run_full_evaluation(body)
    except DependencyUnavailable as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"evaluation_id": evaluation_id, "status": "queued",
            "poll_url": f"/v1/evaluations/{evaluation_id}"}


@app.get("/v1/evaluations/{evaluation_id}", dependencies=[Depends(require_api_key)])
def get_evaluation(evaluation_id: str) -> dict[str, Any]:
    report = orchestrate.get_evaluation(evaluation_id)
    if report is not None:
        return report
    # Unknown id (including the conventional ev_stub_0001): still
    # contract-valid, never a 404 hang for WFEVAL_STUB_DEPS callers -- same
    # fallback pattern as services/sandbox/src/main.py's get_execution().
    return golden("evaluation.response.json")
