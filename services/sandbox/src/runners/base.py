"""Runner abstraction.

Spiff (runners/spiff/) is PRIMARY: free, local, seconds, CI-friendly, no
consumption units, no tenant. UiPath (runners/uipath/) is a DEFERRED stub --
we have no sandbox tenant. Both implement this interface so main.py can swap
runners without touching the service contract. See
docs/decisions/0002-spiff-primary-runner.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from wfeval.core.testcase import MockDefinition, TestCase
from wfeval.core.trace import Trace


class RunnerError(Exception):
    """A runner cannot even attempt this artifact (e.g. it fails to parse at
    all). Distinct from a single unresolvable task within an otherwise-valid
    artifact -- that's EXE-RUNNER-UNSUPPORTED plus a skipped result, not this.
    """


class Runner(ABC):
    name: str          # "spiff" | "uipath_maestro"
    fidelity: str      # wfeval.core.trace.RunnerFidelity value

    @abstractmethod
    def deploy(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """L5 platform acceptance. Returns {accepted, diagnostics}."""

    @abstractmethod
    def execute(
        self,
        artifact: dict[str, Any],
        test_case: TestCase,
        mocks: list[MockDefinition],
        timeout_s: int,
    ) -> tuple[Trace, list, str, str | None]:
        """Run one test case to completion or timeout.

        Returns (trace, diagnostics, result_status, failed_assertion) where
        result_status is "pass" | "fail" | "error" | "skipped" -- the same
        vocabulary as ExecutionResult.status.
        """
