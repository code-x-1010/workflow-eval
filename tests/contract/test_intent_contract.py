"""The intent service (:8002, P2) satisfies contracts/intent.openapi.yaml.

This is the D3 milestone test: every endpoint returns a contract-valid response,
even though every value is still the committed golden example. AGENTS.md section
5 — `make contract` must be green from D3 onward, and going red is a stop-work
event for whoever broke it.

Validation is against the frozen OpenAPI document itself (Draft 2020-12, which
OpenAPI 3.1 schemas are), not against a hand-copied subset of it. If the service
and the contract ever drift, this file is what notices.

Owner: P2. Other agents: this asserts nothing about your services.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from services.intent.src.main import app

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "intent.openapi.yaml"
EXAMPLES = ROOT / "contracts" / "examples"

_SPEC: dict[str, Any] = yaml.safe_load(CONTRACT.read_text())
_BASE = "urn:intent-openapi"
_REGISTRY = Registry().with_resource(
    uri=_BASE, resource=Resource.from_contents(_SPEC, default_specification=DRAFT202012)
)

client = TestClient(app)

# A realistic request per endpoint. Each is itself validated against the request
# schema before it is sent -- a contract test that sends contract-invalid input
# proves nothing.
PROMPT = (EXAMPLES / "prompt.txt").read_text()
ARTIFACT = (EXAMPLES / "artifact.bpmn").read_text()

REQUESTS: dict[str, dict[str, Any]] = {
    "/v1/spec": {"prompt": PROMPT, "platform": "uipath_maestro"},
    "/v1/intent": {"prompt": PROMPT, "artifact": ARTIFACT},
    "/v1/testcases": {"prompt": PROMPT, "kinds": ["happy", "boundary", "adversarial"]},
}

# endpoint -> (request schema, response schema, golden example file)
ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "/v1/spec": ("SpecRequest", "SpecResponse", "spec.response.json"),
    "/v1/intent": ("IntentRequest", "IntentReport", "intent.response.json"),
    "/v1/testcases": ("TestCasesRequest", "TestCasesResponse", "testcases.response.json"),
}


def validate(instance: Any, schema_name: str) -> None:
    """Validate against components/schemas/<schema_name> in the frozen contract."""
    validator = Draft202012Validator(
        {"$ref": f"{_BASE}#/components/schemas/{schema_name}"}, registry=_REGISTRY
    )
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(
        f"{schema_name}{''.join(f'[{p!r}]' for p in e.absolute_path)}: {e.message}" for e in errors
    )


# ---------- the D3 milestone: contract-valid responses from every endpoint ----------


@pytest.mark.parametrize("path", sorted(ENDPOINTS))
def test_request_fixture_is_itself_contract_valid(path: str) -> None:
    request_schema, _, _ = ENDPOINTS[path]
    validate(REQUESTS[path], request_schema)


@pytest.mark.parametrize("path", sorted(ENDPOINTS))
def test_endpoint_returns_a_contract_valid_response(path: str) -> None:
    _, response_schema, _ = ENDPOINTS[path]
    r = client.post(path, json=REQUESTS[path])
    assert r.status_code == 200, r.text
    validate(r.json(), response_schema)


@pytest.mark.parametrize("path", sorted(ENDPOINTS))
def test_golden_example_on_disk_is_contract_valid(path: str) -> None:
    """P3 and P1 build against the committed file, not against the running
    service. It has to validate on its own."""
    _, response_schema, filename = ENDPOINTS[path]
    validate(json.loads((EXAMPLES / filename).read_text()), response_schema)


def test_healthz() -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    inline = _SPEC["paths"]["/healthz"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    Draft202012Validator(inline, registry=_REGISTRY).validate(r.json())
    assert r.json() == {"status": "ok", "service": "intent", "owner": "P2"}


@pytest.mark.parametrize("path", sorted(ENDPOINTS))
def test_response_omits_the_golden_files_note(path: str) -> None:
    """`_note` documents the committed example to the agent reading it; the
    contract says it is never present in a real response. A consumer must not be
    able to tell a stubbed response from a real one by a field that will vanish."""
    r = client.post(path, json=REQUESTS[path])
    assert "_note" not in r.json()


# ---------- the contract's own rules, exercised over HTTP ----------


def test_missing_prompt_is_a_422() -> None:
    for path in ENDPOINTS:
        body = {k: v for k, v in REQUESTS[path].items() if k != "prompt"}
        assert client.post(path, json=body).status_code == 422, path


def test_empty_prompt_is_a_422() -> None:
    """minLength: 1 on every request schema. An empty prompt is not a spec with
    no steps, it is a caller bug."""
    for path in ENDPOINTS:
        body = dict(REQUESTS[path], prompt="")
        assert client.post(path, json=body).status_code == 422, path


def test_unknown_field_is_a_422_everywhere() -> None:
    """additionalProperties: false on all three request schemas. A typo'd field
    silently ignored is how a caller ends up believing an option took effect."""
    for path in ENDPOINTS:
        body = dict(REQUESTS[path], nonsense_field=1)
        assert client.post(path, json=body).status_code == 422, path


def test_testcases_rejects_a_smuggled_artifact_over_http() -> None:
    """The schema leg of the three-legged anti-circularity guarantee, exercised
    live rather than by reading main.py, and for the names a caller would
    plausibly reach for. See tests/contract/test_anti_circularity.py for the
    other two legs."""
    for field in ("artifact", "bpmn", "workflow", "generated_artifact"):
        r = client.post("/v1/testcases", json={"prompt": PROMPT, field: ARTIFACT})
        assert r.status_code == 422, f"/v1/testcases accepted {field!r}"


def test_intent_requires_the_artifact() -> None:
    assert client.post("/v1/intent", json={"prompt": PROMPT}).status_code == 422


def test_supplied_spec_is_accepted_on_both_endpoints() -> None:
    """`spec` is optional everywhere: supplied by the generation team it is used,
    absent P2 extracts its own. That optionality keeps the only external
    dependency off the project's critical path, so it has to actually work."""
    upstream = json.loads((EXAMPLES / "spec.response.json").read_text())["spec"]
    validate(upstream, "Spec")
    for path in ("/v1/intent", "/v1/testcases"):
        r = client.post(path, json=dict(REQUESTS[path], spec=upstream))
        assert r.status_code == 200, r.text
        validate(r.json(), ENDPOINTS[path][1])


def test_kinds_may_be_narrowed_but_not_emptied() -> None:
    def post(kinds: list[str]) -> int:
        return client.post("/v1/testcases", json=dict(REQUESTS["/v1/testcases"], kinds=kinds)).status_code

    assert post(["happy"]) == 200
    assert post([]) == 422, "minItems: 1 -- an empty kinds list is a caller bug, not 'generate nothing'"
    assert post(["nope"]) == 422


# ---------- house rules that the schema encodes ----------


def test_a_score_never_ships_without_its_agreement_rate() -> None:
    """IntentReport's if/then: non-empty `scores` requires a numeric
    `judge_agreement`. Machine-checkable, not a convention -- assert the schema
    actually bites, so nobody later "simplifies" the if/then away."""
    r = client.post("/v1/intent", json=REQUESTS["/v1/intent"])
    report = r.json()
    assert report["scores"] and report["judge_agreement"] is not None

    with pytest.raises(AssertionError):
        validate(dict(report, judge_agreement=None), "IntentReport")
    # null is permitted only when no score is being reported.
    scoreless = {"scores": {}, "diagnostics": [], "judge_agreement": None, "spec_source": "extracted"}
    validate(scoreless, "IntentReport")


def test_served_app_matches_the_frozen_contracts_surface() -> None:
    """The routes FastAPI serves and the paths the contract declares are the same
    set. Catches an endpoint added to one and not the other."""
    served = {r.path for r in app.routes if r.path.startswith(("/v1", "/healthz"))}  # type: ignore[attr-defined]
    assert served == set(_SPEC["paths"])
