"""Intent alignment and test generation. Everything derived from the PROMPT.

Service: intent  |  Port: 8002  |  Owner: P2
Charter: docs/agents/P2-*.md      Contract: contracts/intent.openapi.yaml

D3 STUB. Every endpoint returns the committed golden example from
`contracts/examples/`, so the other three agents are never blocked on P2's
generator. The *shapes* here are real and frozen; the *values* are the golden
data and do not vary with the request. Replace endpoint bodies with real logic;
do not change the response SHAPES without a decision record.

Three things are already real, and must stay real when the bodies are replaced:

* Request validation. The three request models mirror the `*Request` schemas in
  `contracts/intent.openapi.yaml` exactly, `extra="forbid"` included, so a
  malformed request 422s here the same way it will in production.
* The anti-circularity guarantee on `/v1/testcases` — see that endpoint.
* `_note` stripping. The golden files carry a `_note` explaining themselves to
  the agent reading the file; the OpenAPI says it is "present only in the
  committed golden example, never in a real response", so a response served
  *from* one drops it. A consumer must not be able to tell a stubbed response
  from a real one by a field that is going to vanish.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from wfeval.core.ir import Spec
from wfeval.core.stubs import golden
from wfeval.core.testcase import CaseKind

app = FastAPI(title="wfeval-intent", version="0.1.0")

SERVICE = "intent"
OWNER = "P2"

Prompt = Annotated[str, Field(min_length=1, description="The user's natural-language request, verbatim.")]


class SpecRequest(BaseModel):
    """Mirrors SpecRequest in contracts/intent.openapi.yaml."""

    model_config = ConfigDict(extra="forbid")

    prompt: Prompt
    platform: Literal["uipath_maestro", "n8n"] = "uipath_maestro"


class IntentRequest(BaseModel):
    """Mirrors IntentRequest. The one P2 endpoint that receives the artifact —
    alignment lives in align.py, outside testgen/, and that separation is the
    whole anti-circularity guarantee."""

    model_config = ConfigDict(extra="forbid")

    prompt: Prompt
    artifact: str = Field(description="BPMN 2.0 XML (or DMN) as produced by the generator.")
    spec: Spec | None = None


class TestCasesRequest(BaseModel):
    """Mirrors TestCasesRequest.

    ANTI-CIRCULARITY: there is deliberately no `artifact` field, and
    `extra="forbid"` means a caller cannot add one — an unknown field is a 422,
    not a silently ignored field. Do not relax either. See the endpoint below,
    .importlinter contract 2, and tests/contract/test_anti_circularity.py.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: Prompt
    spec: Spec | None = None
    kinds: list[CaseKind] = Field(
        default=[CaseKind.HAPPY, CaseKind.BOUNDARY, CaseKind.ADVERSARIAL],
        min_length=1,
        description="Which case kinds to generate. Omitted means all three.",
    )


def _served(name: str) -> dict[str, Any]:
    """The golden example as a *service response*: identical but for `_note`,
    which documents the committed file and is not part of any real response."""
    return {k: v for k, v in golden(name).items() if k != "_note"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/spec")
def extract_spec(body: SpecRequest) -> dict[str, Any]:
    # TODO(P2 D3-D4): structured extraction from body.prompt, disk-cached by
    # sha256(prompt) so the same prompt twice costs zero LLM calls.
    # TODO(P2 D5): real SPEC-* sufficiency diagnostics (registry: docs/decisions/0008).
    return _served("spec.response.json")


@app.post("/v1/intent")
def intent(body: IntentRequest) -> dict[str, Any]:
    # TODO(P2 D6-D7): deterministic Spec<->AST diff, then judge for the residue.
    # Never ship scores without judge_agreement.
    return _served("intent.response.json")


@app.post("/v1/testcases")
def testcases(body: TestCasesRequest) -> dict[str, Any]:
    """ANTI-CIRCULARITY: this endpoint takes NO artifact and never will.

    Tests derived from the generated workflow are tests the workflow passes.
    Enforced by .importlinter contract 2. See docs/agents/P2-intent-testgen.md.
    """
    # Belt and braces. TestCasesRequest forbids extras, so an artifact is
    # rejected with a 422 before this runs; this fires if that is ever relaxed.
    assert "artifact" not in body.model_dump(), "testcases must never receive the artifact"
    # TODO(P2 D8-D9): generate from body.prompt / body.spec, honouring body.kinds.
    return _served("testcases.response.json")
