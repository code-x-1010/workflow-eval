from __future__ import annotations

from wfeval.core.testcase import TaskStub

from services.sandbox.src.runners.spiff.stubs import TaskStubResolver


def test_resolves_by_element_id_and_cycles_per_invocation():
    resolver = TaskStubResolver([TaskStub(element_id="Task_extract", outputs=[{"n": 1}, {"n": 2}])])
    assert resolver.resolve("Task_extract") == {"n": 1}
    assert resolver.resolve("Task_extract") == {"n": 2}


def test_last_output_repeats_past_the_end_of_the_list():
    resolver = TaskStubResolver([TaskStub(element_id="Task_extract", outputs=[{"n": 1}, {"n": 2}])])
    resolver.resolve("Task_extract")
    resolver.resolve("Task_extract")
    assert resolver.resolve("Task_extract") == {"n": 2}


def test_falls_back_to_asset_ref_when_element_id_unmatched():
    resolver = TaskStubResolver(
        [TaskStub(asset_ref="ExtractInvoiceFields", outputs=[{"vendor": "Acme"}])],
        asset_ref_by_element={"Task_extract": "ExtractInvoiceFields"},
    )
    assert resolver.resolve("Task_extract") == {"vendor": "Acme"}


def test_unstubbed_element_resolves_to_none():
    resolver = TaskStubResolver([TaskStub(element_id="Task_extract", outputs=[{"n": 1}])])
    assert resolver.resolve("Task_autopay") is None


def test_invocation_counters_are_independent_per_element():
    resolver = TaskStubResolver([
        TaskStub(element_id="A", outputs=[{"v": "a1"}, {"v": "a2"}]),
        TaskStub(element_id="B", outputs=[{"v": "b1"}]),
    ])
    assert resolver.resolve("A") == {"v": "a1"}
    assert resolver.resolve("B") == {"v": "b1"}
    assert resolver.resolve("A") == {"v": "a2"}
