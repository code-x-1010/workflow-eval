"""SpiffRunner: the primary Runner. Thin wrapper around engine.run_case() that
satisfies the shared Runner interface -- see ../base.py.
"""
from __future__ import annotations

from typing import Any

from wfeval.core.testcase import MockDefinition, TestCase
from wfeval.core.trace import Trace

from ..base import Runner
from .engine import RUNNER_NAME, run_case


class SpiffRunner(Runner):
    name = RUNNER_NAME
    fidelity = "reduced"

    def deploy(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Spiff has no concept of a Maestro deploy -- see runners/uipath/
        for why L5 platform acceptance is deferred, not answered here."""
        raise NotImplementedError(
            "SpiffRunner does not implement L5 deploy acceptance -- it never talks to "
            "Maestro. main.py's /v1/deploy handles this as a deferred pass-through "
            "directly; it does not call into a runner."
        )

    def execute(
        self, artifact: dict[str, Any], test_case: TestCase, mocks: list[MockDefinition], timeout_s: int,
    ) -> tuple[Trace, list, str, str | None]:
        return run_case(artifact, test_case, mocks, timeout_s)
