"""Intent alignment and test generation. Everything derived from the PROMPT.

Service: intent  |  Port: 8002  |  Owner: P2
Charter: docs/agents/P2-*.md      Contract: contracts/intent.openapi.yaml

STUB. Returns contract-valid golden data so the other three agents are never
blocked on you. Replace endpoint bodies with real logic; do not change the
response SHAPES without a decision record.
"""
from fastapi import FastAPI

from wfeval.core.stubs import golden

app = FastAPI(title="wfeval-intent", version="0.1.0")

SERVICE = "intent"
OWNER = "P2"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/spec")
def extract_spec(body: dict) -> dict:
    # TODO(P2 D3-D4): structured extraction from body["prompt"], disk-cached.
    return golden("spec.response.json")


@app.post("/v1/intent")
def intent(body: dict) -> dict:
    # TODO(P2 D6-D7): deterministic Spec<->AST diff, then judge for the residue.
    # Never ship scores without judge_agreement.
    return golden("intent.response.json")


@app.post("/v1/testcases")
def testcases(body: dict) -> dict:
    """ANTI-CIRCULARITY: this endpoint takes NO artifact and never will.

    Tests derived from the generated workflow are tests the workflow passes.
    Enforced by .importlinter contract 2. See docs/agents/P2-intent-testgen.md.
    """
    assert "artifact" not in body, "testcases must never receive the artifact"
    return golden("testcases.response.json")
