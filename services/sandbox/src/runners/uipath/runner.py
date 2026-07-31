"""DEFERRED. We have no UiPath sandbox tenant -- see
docs/decisions/0002-spiff-primary-runner.md.

Keeps the Runner interface implemented so this class can be dropped in the day
a tenant exists (main.py's runner selection doesn't change), but every method
raises for now. L5 platform acceptance -- "does this artifact actually deploy
to and run on Maestro" -- is the one thing Spiff cannot substitute for; this is
where that real check will live once this class stops raising. Everything this
class will eventually need -- OAuth2 client-credentials token refresh, the
deploy/instance-start/status/history endpoints, WireMock-seeded HTTP
interception for MockDefinition, the Action Center human-task poller, and the
reaper -- was all designed before the tenant-access assumption changed; see
docs/handoff/P3.md for the D1-D2 access-spike notes this superseded.
"""
from __future__ import annotations

from typing import Any

from wfeval.core.testcase import MockDefinition, TestCase
from wfeval.core.trace import Trace

from ..base import Runner

_NO_TENANT = (
    "No UiPath sandbox tenant configured. Spiff is the primary runner for "
    "everything except L5 platform acceptance -- see docs/agents/P3-sandbox.md "
    "and docs/decisions/0002-spiff-primary-runner.md."
)


class UiPathRunner(Runner):
    name = "uipath_maestro"
    fidelity = "production"

    def deploy(self, artifact: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(_NO_TENANT)

    def execute(
        self, artifact: dict[str, Any], test_case: TestCase, mocks: list[MockDefinition], timeout_s: int,
    ) -> tuple[Trace, list, str, str | None]:
        raise NotImplementedError(_NO_TENANT)
