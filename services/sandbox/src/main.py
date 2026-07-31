"""Sandbox execution. The only service holding UiPath credentials.

Service: sandbox  |  Port: 8003  |  Owner: P3
Charter: docs/agents/P3-*.md      Contract: contracts/sandbox.openapi.yaml

STUB. Returns contract-valid golden data so the other three agents are never
blocked on you. Replace endpoint bodies with real logic; do not change the
response SHAPES without a decision record.
"""
from fastapi import FastAPI

from wfeval.core.stubs import golden

app = FastAPI(title="wfeval-sandbox", version="0.1.0")

SERVICE = "sandbox"
OWNER = "P3"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/deploy")
def deploy(body: dict) -> dict:
    # TODO(P3 D4-D5): real deploy to the sandbox folder. Map errors to PLT-*.
    return {"accepted": True, "diagnostics": []}


@app.post("/v1/executions")
def start_execution(body: dict) -> dict:
    # TODO(P3 D7): async start; poll to terminal; reaper enforces timeout_s.
    return {"execution_id": "ex_stub_0001", "poll_url": "/v1/executions/ex_stub_0001"}


@app.get("/v1/executions/{execution_id}")
def get_execution(execution_id: str) -> dict:
    # TODO(P3 D8): instance history -> canonical Trace.
    # Populate Actuals from day one -- P4 cannot fabricate them later.
    return golden("execution.response.json")


@app.get("/v1/assets")
def assets() -> dict:
    # Consumed by P1's L2 reference checks. P1 degrades gracefully if we're down.
    return golden("assets.response.json")
