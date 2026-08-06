"""A MockDefinition per external integration, and a TaskStub per agent step. D9.

> *"P3's WireMock seeds from your output without transformation."* -- the charter

Taken literally. Every `MockDefinition` here carries a concrete host, path,
method, status and response body, because a mock missing any of those is one P3
has to fill in -- and a field P3 fills in is a field P2 decided not to decide.

## Two different mechanisms, for two different things

`MockDefinition` and `TaskStub` are not alternatives and `testcase.py` says so:

* **`MockDefinition`** intercepts a real outbound *HTTP call*. Only a runner that
  actually attempts network calls needs it -- today that is the deferred UiPath
  runner. Spiff never touches the network and ignores this list entirely.
* **`TaskStub`** is the canned output of a *task invocation* -- what a connector
  or agent would have returned, resolved locally with no network at all. This is
  what Spiff consumes, so it is what matters for every execution run happening
  today.

Emitting both is not redundancy; it is the difference between the runner P3 has
and the runner P3 is building toward.

## Keyed by `asset_ref`, never by `element_id`

`TaskStub` accepts either. P2 emits only `asset_ref`, always, and the reason is
the whole anti-circularity guarantee: **an element id exists only in the artifact,
and this package never sees the artifact.** Decision `0005` §3 settled the shape;
`tc_006` in the golden example is the committed preview of it.

Owner: P2. Imports `wfeval.core` types only.
"""
from __future__ import annotations

from typing import Any

from wfeval.core.ir import Spec
from wfeval.core.testcase import MockDefinition, TaskStub

# integration name -> (host, path, method, response body)
#
# Hosts are the real vendor endpoints where the vocabulary names a vendor, and a
# readable placeholder where it names a category. A placeholder host is honest:
# "the prompt said 'the CRM' and did not say which", which is the same fact
# SPEC-UNSPECIFIED-INTEGRATION reports at D5.
#
# Response bodies are minimal and *shaped like the real thing* -- an id and a
# status, which is what a workflow branches on. A richer invented body would be
# P2 guessing at a schema nobody stated.
_ENDPOINTS: dict[str, tuple[str, str, str, dict[str, Any]]] = {
    "email":           ("smtp.example.com", "/v1/messages", "POST", {"id": "msg_1", "status": "sent"}),
    "slack":           ("slack.com", "/api/chat.postMessage", "POST", {"ok": True, "ts": "1.0"}),
    "teams":           ("graph.microsoft.com", "/v1.0/teams/messages", "POST", {"id": "msg_1"}),
    "sms":             ("api.twilio.com", "/2010-04-01/Messages.json", "POST", {"sid": "SM1", "status": "queued"}),
    "payments_api":    ("api.stripe.com", "/v1/payment_intents", "POST", {"id": "pi_1", "status": "succeeded"}),
    "crm":             ("crm.example.com", "/v1/records", "POST", {"id": "rec_1", "status": "created"}),
    "erp":             ("erp.example.com", "/v1/documents", "POST", {"id": "doc_1", "status": "posted"}),
    "accounting":      ("api.quickbooks.com", "/v3/company/1/bill", "POST", {"Id": "1", "status": "created"}),
    "ticketing":       ("api.atlassian.com", "/rest/api/3/issue", "POST", {"id": "10001", "key": "OPS-1"}),
    "hris":            ("api.workday.com", "/v1/workers", "POST", {"id": "wkr_1", "status": "updated"}),
    "esignature":      ("api.docusign.net", "/restapi/v2.1/envelopes", "POST", {"envelopeId": "env_1", "status": "sent"}),
    "spreadsheet":     ("sheets.googleapis.com", "/v4/spreadsheets/1/values/A1:append", "POST", {"updates": {"updatedRows": 1}}),
    "object_storage":  ("s3.amazonaws.com", "/bucket/object", "PUT", {"ETag": "etag_1"}),
    "document_store":  ("graph.microsoft.com", "/v1.0/drive/root/children", "POST", {"id": "file_1"}),
    "database":        ("db.example.com", "/v1/query", "POST", {"rows": 1, "status": "ok"}),
    "sftp":            ("sftp.example.com", "/upload", "PUT", {"status": "ok"}),
    "calendar":        ("www.googleapis.com", "/calendar/v3/calendars/primary/events", "POST", {"id": "evt_1"}),
    "shipping":        ("api.fedex.com", "/ship/v1/shipments", "POST", {"trackingNumber": "TRK1"}),
    "identity":        ("api.okta.com", "/api/v1/users", "POST", {"id": "usr_1", "status": "ACTIVE"}),
}

_FALLBACK = ("integration.example.com", "/v1/invoke", "POST", {"status": "ok"})


def mocks_for(spec: Spec) -> list[MockDefinition]:
    """One mock per integration the prompt named, in a stable order.

    Sorted rather than in spec order so that regenerating a suite for an
    unchanged prompt produces a byte-identical list. P3 seeds these into
    WireMock; a list that reshuffles turns every regeneration into a diff.
    """
    out = []
    for integration in sorted(set(spec.integrations)):
        host, path, method, response = _ENDPOINTS.get(integration, _FALLBACK)
        out.append(MockDefinition(
            host=host,
            path=path,
            method=method,
            status=200,
            response=response,
            # Non-zero and small. A mock that answers instantly hides the
            # timeout handling the prompt may or may not have asked for; a slow
            # one makes every corpus run slower for no signal.
            latency_ms=50,
        ))
    return out


def failure_mock_for(spec: Spec) -> list[MockDefinition]:
    """A 500 from the first integration, for the adversarial case that exercises
    the failure path -- but only when the prompt actually stated one.

    Without a stated failure behaviour there is nothing to assert about what
    should happen, so a failing mock would just produce an unexplained `error`
    status. That gap is `SPEC-NO-ERROR-BEHAVIOUR`, and reporting it is more
    useful than testing against a behaviour nobody specified.
    """
    if spec.error_behaviour is None or not spec.integrations:
        return []
    integration = min(set(spec.integrations))
    host, path, method, _ = _ENDPOINTS.get(integration, _FALLBACK)
    return [MockDefinition(
        host=host, path=path, method=method, status=500,
        response={"error": "upstream unavailable"}, latency_ms=50,
    )]


def task_stubs_for(spec: Spec) -> list[TaskStub]:
    """Canned outputs for the agent and decision steps, keyed by `asset_ref`.

    The `asset_ref` is derived from the step's own description, so it is stable
    across regenerations and readable in a failure report. It is a *name P2
    chose*, and P3 resolves it against the artifact's asset references at
    execution time -- which is exactly the indirection that lets this package
    stay blind to element ids.
    """
    out = []
    for step in spec.steps:
        if step.kind_hint not in {"agent", "decision"}:
            continue
        out.append(TaskStub(
            element_id=None,  # never. See the module docstring.
            asset_ref=_asset_ref(step.description),
            outputs=[{"status": "ok", "confidence": 0.9}],
        ))
    return out


def _asset_ref(description: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", description.lower()).strip("_")
    return slug[:60] or "step"
