"""Fan-out, short-circuit, aggregate, score.

Service: gateway  |  Port: 8000  |  Owner: P1
Charter: docs/agents/P1-*.md      Contract: contracts/gateway.openapi.yaml

STUB. Returns contract-valid golden data so the other three agents are never
blocked on you. Replace endpoint bodies with real logic; do not change the
response SHAPES without a decision record.
"""
from fastapi import FastAPI

from wfeval.core.stubs import golden

app = FastAPI(title="wfeval-gateway", version="0.1.0")

SERVICE = "gateway"
OWNER = "P1"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/evaluations")
def create_evaluation(body: dict) -> dict:
    # TODO(P1 D3): fan-out with short-circuit (see orchestrate.py).
    return {"evaluation_id": "ev_stub_0001", "status": "queued",
            "poll_url": "/v1/evaluations/ev_stub_0001"}


@app.get("/v1/evaluations/{evaluation_id}")
def get_evaluation(evaluation_id: str) -> dict:
    return golden("evaluation.response.json")
