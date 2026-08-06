"""Intent alignment and test generation. Everything derived from the PROMPT.

Service: intent  |  Port: 8002  |  Owner: P2
Charter: docs/agents/P2-*.md      Contract: contracts/intent.openapi.yaml

D3 STUB. Stubbed -- which is the default, and what `make dev` runs -- every
endpoint returns the committed golden example from `contracts/examples/`, so
the other three agents are never blocked on P2's generator. The *shapes* are
real and frozen; the *values* are the golden data and do not vary with the
request. Replace endpoint bodies with real logic; do not change the response
SHAPES without a decision record.

`WFEVAL_STUB_DEPS=0` (`make dev-real`) runs what is real so far: today that is
`/v1/spec`'s deterministic extraction plus the optional LLM residue pass, both
behind one content-hash disk cache. Real output is thinner than the golden
example on purpose -- see extract.py on residue, and refine.py on why a refined
value must quote the prompt to survive.

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
from wfeval.core.stubs import golden, stubbing
from wfeval.core.testcase import CaseKind

from .cache import DiskCache
from .extract import EXTRACTOR_VERSION, extract
from .refine import cache_version, refiner_from_env
from .sufficiency import SUFFICIENCY_VERSION, diagnose

app = FastAPI(title="wfeval-intent", version="0.1.0")

SERVICE = "intent"
OWNER = "P2"

# None unless WFEVAL_SPEC_REFINER says otherwise -- there is no LLM client and no
# API key in this repo, so on-by-default would mean a failed call per request.
REFINER = refiner_from_env()

# Keyed by *everything that produced the response*, not just the prompt: the
# extractor's rules, the refiner's identity, and the sufficiency rules. Changing
# any of them while the key stays the same means serving output from a pipeline
# that no longer exists, and you debug the old output for an hour before noticing.
SPEC_CACHE = DiskCache(
    namespace="spec",
    version=f"{cache_version(EXTRACTOR_VERSION, REFINER)}/{SUFFICIENCY_VERSION}",
)

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
    """Stubbed (the default) this returns the golden example, so anyone wiring
    against :8002 today gets the same fully-populated Spec every time.

    `WFEVAL_STUB_DEPS=0` runs the real pipeline: deterministic rules over the
    prompt, then the refiner for the residue if one is wired, disk-cached by
    sha256(prompt) + the version of everything that produced the spec. The split
    matches `make dev` vs `make dev-real` -- real output is thinner than the
    golden example on purpose (see extract.py on residue) and would otherwise
    surprise three agents who are building against the example.

    The cache wraps `extract` **and** the refiner, which is what makes the
    charter's D3-D4 bar mean anything: the same prompt twice is zero model calls
    the second time, and a 40-case corpus re-run costs nothing after the first.
    """
    if stubbing():
        return _served("spec.response.json")
    body_out, _cached = SPEC_CACHE.get_or_compute(body.prompt, lambda: _spec_response(body.prompt))
    return body_out


def _spec_response(prompt: str) -> dict[str, Any]:
    """Extract, refine, then diagnose -- cached as one unit.

    Diagnostics run **after** refinement, on the spec that is actually served.
    That is deliberate and it is the only defensible order: a `SPEC-*` code is a
    claim about what the response contains, so a refiner that legitimately
    recovers a trigger from the prompt must also silence `SPEC-NO-TRIGGER`.
    Diagnosing the pre-refinement draft would ship a spec with a trigger next to
    a diagnostic saying it has none.

    `diagnose()` gets the prompt too, because most of these are properties of the
    wording that the Spec does not preserve -- see sufficiency.py on why reading
    an empty Spec field is not the same as reading an under-specified prompt.
    """
    spec = extract(prompt, REFINER)
    return {
        "spec": spec.model_dump(),
        "sufficiency_diagnostics": [d.model_dump() for d in diagnose(prompt, spec)],
    }


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
