"""Gateway fan-out, short-circuit, aggregate. Owner: P1.

Assembles the four services' slices into one EvaluationReport and implements
the short-circuit; does NOT implement the scoring formula -- that's P4's
domain (score.py, weights.yaml, see AGENTS.md ownership map). As of this
commit services/gateway/src/score.py has no callable function yet (just a
docstring), so `_stopgap_score()` below is a clearly temporary placeholder
using the publicly documented formula (README.md "Scoring") and the values
already committed in weights.yaml (read, never written, from here). Delete
`_stopgap_score()` and call P4's real score() the moment it ships.

Every dependency call goes over real HTTP -- this file has no special-cased
"read the golden example directly" branch. Each service already handles its
own WFEVAL_STUB_DEPS stubbing internally (see wfeval.core.stubs.golden and
every services/*/src/main.py), so calling the real endpoint gives the right
answer in both stubbed and real modes without this file needing to know
which one it's in. Tests mock the HTTP layer instead (see
tests/unit/gateway/test_orchestrate.py).

Sandbox execution runs synchronously inside the request handler rather than
on a background worker queue, same reasoning P3 documented for /v1/executions:
Spiff is seconds-fast, not minutes, so there is no real async need yet. Kept
202-shaped for contract parity with a future slow runner and D9's planned
real queue. See docs/agents/P1-validation.md D9 and
services/sandbox/src/main.py's start_execution() docstring.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml
from wfeval.core.report import (
    CostReport,
    EvaluationReport,
    ExecutionReport,
    IntentReport,
    ValidationReport,
    Verdict,
)

from . import webhook

VALIDATION_URL = os.environ.get("VALIDATION_URL", "http://validation:8001")
INTENT_URL = os.environ.get("INTENT_URL", "http://intent:8002")
SANDBOX_URL = os.environ.get("SANDBOX_URL", "http://sandbox:8003")
COST_URL = os.environ.get("COST_URL", "http://cost:8004")

_WEIGHTS_PATH = Path(__file__).resolve().parent / "weights.yaml"
_HTTP_TIMEOUT_S = 30.0

# In-memory evaluation_id -> EvaluationReport (JSON-mode dumped). Same
# rationale and same limitation as services/sandbox/src/main.py's
# _EXECUTIONS: fine for a single-process dev service, not durable across a
# restart. Still in-memory even after D9 hardening below -- a durable store
# is orthogonal to idempotency and not needed to satisfy the charter's D9
# "done when" (replaying request_id returns the cached report).
_EVALUATIONS: dict[str, dict[str, Any]] = {}

# request_id -> evaluation_id. D9 idempotency: per the contract
# ("Idempotent on request_id: replaying the same request_id returns the
# cached evaluation_id for the original run rather than starting a second
# one"), keyed on request_id alone -- the contract doesn't ask us to also
# compare artifact content, so we don't; a caller reusing a request_id with
# a different artifact gets the *first* run's result, by design.
_REQUEST_ID_INDEX: dict[str, str] = {}


class DependencyUnavailable(Exception):
    """A downstream service could not be reached at all (connection refused,
    timeout, DNS failure) -- distinct from that service responding with an
    error status, which is a bug in that service, not an outage."""

    def __init__(self, service: str, detail: str) -> None:
        self.service = service
        super().__init__(f"{service} unavailable: {detail}")


async def _call(method: str, base_url: str, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            resp = await client.request(method, f"{base_url}{path}", json=json_body)
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise DependencyUnavailable(base_url, str(e)) from e


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _artifact_body(request: dict[str, Any]) -> dict[str, Any]:
    """Reads the nested `artifact: {format, content}` shape the contract
    (contracts/gateway.openapi.yaml's ArtifactSubmission) actually defines,
    same as Validation's own main.py. This was previously reading `format`/
    `content` as flat top-level request fields -- contradicting the
    published contract and every real client (and this file's own module
    docstring's claim that no branch special-cases stub/real mode; nothing
    stubbed this, it was just wrong) -- found while writing the D10
    integration guide's sample client against the real contract. See
    docs/handoff/P1.md, 2026-08-06 entry."""
    artifact = request.get("artifact") or {}
    return {"format": artifact.get("format", "bpmn"), "content": artifact.get("content", "")}


async def run_predeploy_validate(request: dict[str, Any]) -> EvaluationReport:
    """POST /v1/validate: sync, sub-2s. Validation (L1-L4) + Cost only --
    never Sandbox or Intent, those are minutes not seconds. See README.md."""
    evaluation_id = f"ev_{uuid.uuid4().hex[:8]}"
    request_id = request.get("request_id") or f"req_{uuid.uuid4().hex[:8]}"
    platform = request.get("platform", "uipath_maestro")
    timings: dict[str, int] = {}

    t0 = _now_ms()
    validation_raw = await _call("POST", VALIDATION_URL, "/v1/validate", json_body={
        "request_id": request_id, "platform": platform,
        "artifact": _artifact_body(request), "prompt": request.get("prompt"),
    })
    timings["validation"] = _now_ms() - t0
    validation = ValidationReport.model_validate(validation_raw)

    if not all(validation.gates.values()):
        return _assemble(
            evaluation_id=evaluation_id, request_id=request_id, platform=platform, verdict=Verdict.FAIL,
            validation=validation, intent=None, execution=None, cost=None,
            timings_ms=timings, short_circuited_at="validation",
        )

    t1 = _now_ms()
    cost_raw = await _call("POST", COST_URL, "/v1/cost", json_body={"artifact": _artifact_body(request)})
    timings["cost"] = _now_ms() - t1
    cost = CostReport.model_validate(cost_raw)

    overall, verdict = _stopgap_score(validation=validation, intent=None, execution=None)
    return _assemble(
        evaluation_id=evaluation_id, request_id=request_id, platform=platform, verdict=verdict,
        validation=validation, intent=None, execution=None, cost=cost,
        timings_ms=timings, short_circuited_at=None, overall=overall,
    )


async def run_full_evaluation(request: dict[str, Any]) -> str:
    """POST /v1/evaluations: full pipeline, computed synchronously (see
    module docstring), stashed under a fresh evaluation_id. Returns the id;
    callers get it back immediately via the 202 response and poll
    GET /v1/evaluations/{id}.

    Idempotent on request_id (D9, decision 0018): a request_id already seen
    returns the original evaluation_id immediately, without re-running the
    pipeline (no second Sandbox deploy, no second webhook delivery)."""
    request_id = request.get("request_id")
    if request_id and request_id in _REQUEST_ID_INDEX:
        return _REQUEST_ID_INDEX[request_id]

    evaluation_id = f"ev_{uuid.uuid4().hex[:8]}"
    report = await _run_full_pipeline(request, evaluation_id=evaluation_id)
    _EVALUATIONS[evaluation_id] = report.model_dump(mode="json")
    if request_id:
        _REQUEST_ID_INDEX[request_id] = evaluation_id

    callback_url = request.get("callback_url")
    if callback_url:
        await webhook.deliver(callback_url, report)

    return evaluation_id


async def _run_full_pipeline(request: dict[str, Any], *, evaluation_id: str) -> EvaluationReport:
    request_id = request.get("request_id") or f"req_{uuid.uuid4().hex[:8]}"
    platform = request.get("platform", "uipath_maestro")
    timings: dict[str, int] = {}
    artifact = _artifact_body(request)
    prompt = request.get("prompt")

    # Stage 1: Validation. Any gate false -> fail, skip everything else.
    t0 = _now_ms()
    validation_raw = await _call("POST", VALIDATION_URL, "/v1/validate", json_body={
        "request_id": request_id, "platform": platform, "artifact": artifact, "prompt": prompt,
    })
    timings["validation"] = _now_ms() - t0
    validation = ValidationReport.model_validate(validation_raw)
    if not all(validation.gates.values()):
        return _assemble(
            evaluation_id=evaluation_id, request_id=request_id, platform=platform, verdict=Verdict.FAIL,
            validation=validation, intent=None, execution=None, cost=None,
            timings_ms=timings, short_circuited_at="validation",
        )

    # Stage 2: parallel -- Intent (+testcases), Cost, Sandbox deploy.
    t1 = _now_ms()
    intent_raw = await _call("POST", INTENT_URL, "/v1/intent", json_body={"prompt": prompt, "artifact": artifact["content"]})
    testcases_raw = await _call("POST", INTENT_URL, "/v1/testcases", json_body={"prompt": prompt})
    cost_raw = await _call("POST", COST_URL, "/v1/cost", json_body={"artifact": artifact})
    deploy_raw = await _call("POST", SANDBOX_URL, "/v1/deploy", json_body={"artifact": artifact, "platform": platform})
    timings["deploy"] = _now_ms() - t1
    intent = IntentReport.model_validate(intent_raw)
    cost = CostReport.model_validate(cost_raw)

    if not deploy_raw.get("accepted", False):
        return _assemble(
            evaluation_id=evaluation_id, request_id=request_id, platform=platform, verdict=Verdict.FAIL,
            validation=validation, intent=intent, execution=None, cost=cost,
            timings_ms=timings, short_circuited_at="deploy",
        )

    # Stage 3: Sandbox executions, consuming stage 2's test cases.
    #
    # /v1/executions is 202-shaped per contracts/sandbox.openapi.yaml -- the
    # POST returns {execution_id, poll_url}, not the report itself (kept
    # 202-shaped for contract parity with a future UiPath runner; Sandbox's
    # own main.py already computes the report synchronously and stores it
    # before returning, since Spiff is seconds-fast). This used to skip the
    # GET entirely and try to parse the POST's {execution_id, poll_url} as
    # an ExecutionReport directly -- a real bug, found while building the
    # D10 integration guide's sample client against live services (mocked
    # HTTP-layer tests never caught it because the mock routes only ever
    # returned golden("execution.response.json") for BOTH the POST and any
    # GET, regardless of shape). See docs/handoff/P1.md, 2026-08-06 entry.
    #
    # One GET immediately after POST is correct for today's synchronous-
    # underneath Sandbox; a real async runner that can still be "running" on
    # first GET would need an actual poll loop here, which is out of scope
    # for the same reason decision 0018 scoped out a real async queue --
    # nothing in this repo to build or test that against yet.
    t2 = _now_ms()
    deploy_response = await _call("POST", SANDBOX_URL, "/v1/executions", json_body={
        "artifact": artifact,
        "test_cases": testcases_raw.get("test_cases", []),
        "mocks": testcases_raw.get("mocks", []),
    })
    execution_id = deploy_response["execution_id"]
    execution_raw = await _call("GET", SANDBOX_URL, f"/v1/executions/{execution_id}")
    timings["execution"] = _now_ms() - t2
    execution = ExecutionReport.model_validate(execution_raw)

    # Stage 4: score (stopgap -- see module docstring) + assemble. render()
    # doesn't exist yet either (services/gateway/src/render.py is not
    # created); skipped until P4 ships it, same "call it, don't build it"
    # rule applies there too.
    overall, verdict = _stopgap_score(validation=validation, intent=intent, execution=execution)
    return _assemble(
        evaluation_id=evaluation_id, request_id=request_id, platform=platform, verdict=verdict,
        validation=validation, intent=intent, execution=execution, cost=cost,
        timings_ms=timings, short_circuited_at=None, overall=overall,
    )


def get_evaluation(evaluation_id: str) -> dict[str, Any] | None:
    return _EVALUATIONS.get(evaluation_id)


# ---------- stopgap scoring (P1, TEMPORARY -- see module docstring) ----------

def _load_weights() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(_WEIGHTS_PATH.read_text())
    return data


def _stopgap_score(
    *, validation: ValidationReport, intent: IntentReport | None, execution: ExecutionReport | None,
) -> tuple[float, Verdict]:
    """overall = 0 if any gate fails, else the weighted sum of whichever
    dimension scores are actually present; an unimplemented tier (None
    report, or a null score inside one) contributes 0 to the sum and its
    weight is simply not collected -- never faked as a measurement. This is
    P4's formula (README.md "Scoring", weights.yaml), reproduced here only
    because score.py has nothing callable yet."""
    weights = _load_weights()["weights"]
    thresholds = _load_weights()["thresholds"]

    gates_ok = all(validation.gates.values())
    if not gates_ok:
        return 0.0, Verdict.FAIL

    total = 0.0
    collected_weight = 0.0
    structural = validation.scores.get("structural_soundness")
    if structural is not None:
        total += weights["structural_soundness"] * structural
        collected_weight += weights["structural_soundness"]
    if intent is not None:
        coverage = intent.scores.get("intent_coverage")
        if coverage is not None:
            total += weights["intent_coverage"] * coverage
            collected_weight += weights["intent_coverage"]
    if execution is not None:
        pass_rate = execution.scores.get("execution_pass_rate")
        if pass_rate is not None:
            total += weights["execution_pass_rate"] * pass_rate
            collected_weight += weights["execution_pass_rate"]

    overall = (total / collected_weight) if collected_weight > 0 else 0.0

    if overall < thresholds["fail_below"]:
        verdict = Verdict.FAIL
    elif overall < thresholds["pass_with_warnings_below"]:
        verdict = Verdict.PASS_WITH_WARNINGS
    else:
        verdict = Verdict.PASS
    return round(overall, 4), verdict


def _assemble(
    *, evaluation_id: str, request_id: str, platform: str, verdict: Verdict,
    validation: ValidationReport | None, intent: IntentReport | None,
    execution: ExecutionReport | None, cost: CostReport | None,
    timings_ms: dict[str, int], short_circuited_at: str | None, overall: float = 0.0,
) -> EvaluationReport:
    weights = _load_weights()
    return EvaluationReport(
        evaluation_id=evaluation_id,
        request_id=request_id,
        platform=platform,
        verdict=verdict,
        scoring_version=weights["scoring_version"],
        overall=overall,
        validation=validation,
        intent=intent,
        execution=execution,
        cost=cost,
        timings_ms=timings_ms,
        short_circuited_at=short_circuited_at,
    )
