"""Static cost analysis. No execution required.

Service: cost  |  Port: 8004  |  Owner: P4
Charter: docs/agents/P4-*.md      Contract: contracts/cost.openapi.yaml

STUB. Returns contract-valid golden data so the other three agents are never
blocked on you. Replace endpoint bodies with real logic; do not change the
response SHAPES without a decision record.
"""
from fastapi import FastAPI
from wfeval.core.stubs import golden

app = FastAPI(title="wfeval-cost", version="0.1.0")

SERVICE = "cost"
OWNER = "P4"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/cost")
def cost(body: dict) -> dict:
    # TODO(P4 D4-D5): AND-collapse, min/max via weighted DAG longest/shortest path.
    # D6: bounded enumeration for expected, symbolic loops.
    # `assumptions` is MANDATORY whenever confidence is low.
    return golden("cost.response.json")


@app.post("/v1/calibrate")
def calibrate(body: dict) -> dict:
    # TODO(P4 D9): refit priors from P3's Trace.Actuals; report MAPE honestly.
    return {"mape": None, "priors_updated": [], "note": "insufficient calibration runs"}


@app.get("/v1/pricing")
def pricing() -> dict:
    return {"version": "2026-07-15", "currency": "USD"}
