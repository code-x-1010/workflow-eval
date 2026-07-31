"""Per-invocation TaskStub resolution.

A TestCase's task_stubs map element_id/asset_ref -> a queue of output dicts,
one per invocation (a loop calls the same task more than once and each
iteration may need different output). The invocation counter lives on this
resolver instance, which is constructed fresh per test case -- Sandbox starts
a fresh instance per case, so it's always correct to start back at zero.
"""
from __future__ import annotations

from wfeval.core.testcase import TaskStub


class TaskStubResolver:
    def __init__(self, task_stubs: list[TaskStub], asset_ref_by_element: dict[str, str] | None = None):
        self._by_element: dict[str, list[dict]] = {}
        self._by_asset: dict[str, list[dict]] = {}
        for stub in task_stubs:
            if stub.element_id:
                self._by_element[stub.element_id] = stub.outputs
            if stub.asset_ref:
                self._by_asset[stub.asset_ref] = stub.outputs
        self._asset_ref_by_element = asset_ref_by_element or {}
        self._invocations: dict[str, int] = {}

    def resolve(self, element_id: str) -> dict | None:
        """The output dict for this invocation of `element_id`, or None if
        nothing stubs it -- the caller's job to decide that's unsupported."""
        outputs = self._by_element.get(element_id)
        if outputs is None:
            asset_ref = self._asset_ref_by_element.get(element_id)
            if asset_ref:
                outputs = self._by_asset.get(asset_ref)
        if not outputs:
            return None
        n = self._invocations.get(element_id, 0)
        self._invocations[element_id] = n + 1
        return outputs[min(n, len(outputs) - 1)]
