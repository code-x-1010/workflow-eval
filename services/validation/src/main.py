"""Structural validation: schema, references, structure, soundness, dataflow.

Service: validation  |  Port: 8001  |  Owner: P1
Charter: docs/agents/P1-*.md      Contract: contracts/validation.openapi.yaml

STUB. Returns contract-valid golden data so the other three agents are never
blocked on you. Replace endpoint bodies with real logic; do not change the
response SHAPES without a decision record.
"""
from typing import Any

from fastapi import FastAPI
from wfeval.core.stubs import golden

app = FastAPI(title="wfeval-validation", version="0.1.0")

SERVICE = "validation"
OWNER = "P1"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/validate")
def validate(body: dict[str, Any]) -> dict[str, Any]:
    # TODO(P1 D4-D5): L1 schema, L3 structure. D6-D8: L2, L4.
    # Short-circuit inside the ladder: don't run L4 if L1 failed.
    return golden("validation.response.json")


@app.get("/v1/diagnostics/codes")
def codes() -> dict[str, Any]:
    from wfeval.core.diagnostics import PREFIX_OWNER
    return {"prefixes": PREFIX_OWNER, "codes": []}
