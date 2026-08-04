"""The disk cache. Built on day one, not as a week-2 optimisation.

The charter's D3-D4 bar is literally "same prompt twice = zero LLM calls the
second time", so that is the first test here, asserted by counting calls rather
than by timing anything.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.intent.src.cache import DiskCache


def make(tmp_path: Path, **kw: object) -> DiskCache:
    return DiskCache(root=tmp_path, **kw)  # type: ignore[arg-type]


def test_the_same_payload_twice_computes_once(tmp_path: Path) -> None:
    cache = make(tmp_path)
    calls = 0

    def compute() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"spec": {"trigger": "an invoice arrives"}}

    first, cached_first = cache.get_or_compute("a prompt", compute)
    second, cached_second = cache.get_or_compute("a prompt", compute)

    assert calls == 1, "the second call recomputed -- a corpus run would cost 40 LLM calls, not 0"
    assert (cached_first, cached_second) == (False, True)
    assert first == second
    assert (cache.stats.hits, cache.stats.misses) == (1, 1)


def test_a_different_payload_is_a_different_entry(tmp_path: Path) -> None:
    cache = make(tmp_path)
    cache.get_or_compute("prompt a", lambda: {"v": 1})
    value, was_cached = cache.get_or_compute("prompt b", lambda: {"v": 2})
    assert (value, was_cached) == ({"v": 2}, False)


def test_bumping_the_version_invalidates(tmp_path: Path) -> None:
    """The failure this prevents: you change the extractor, re-run the corpus,
    and spend an hour debugging output the previous extractor produced."""
    old = make(tmp_path, version="d3.1")
    old.get_or_compute("a prompt", lambda: {"from": "old"})

    new = make(tmp_path, version="d3.2")
    value, was_cached = new.get_or_compute("a prompt", lambda: {"from": "new"})

    assert (value, was_cached) == ({"from": "new"}, False)
    assert old.get("a prompt") == {"from": "old"}, "the old entry should still be there, just unused"


def test_a_corrupt_entry_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    """A truncated or hand-edited cache file must not be able to 500 the
    service. It is recomputed and overwritten."""
    cache = make(tmp_path)
    cache.get_or_compute("a prompt", lambda: {"v": 1})
    cache.path_for("a prompt").write_text("{not json", encoding="utf-8")

    value, was_cached = cache.get_or_compute("a prompt", lambda: {"v": 2})

    assert (value, was_cached) == ({"v": 2}, False)
    assert json.loads(cache.path_for("a prompt").read_text())["value"] == {"v": 2}


def test_an_entry_of_the_wrong_shape_is_a_miss(tmp_path: Path) -> None:
    cache = make(tmp_path)
    path = cache.path_for("a prompt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"value": "not an object"}), encoding="utf-8")
    assert cache.get("a prompt") is None


def test_disabled_cache_is_a_pass_through(tmp_path: Path) -> None:
    cache = make(tmp_path, enabled=False)
    calls = 0

    def compute() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"v": calls}

    assert cache.get_or_compute("p", compute) == ({"v": 1}, False)
    assert cache.get_or_compute("p", compute) == ({"v": 2}, False)
    assert not list(tmp_path.rglob("*.json"))


def test_key_is_stable_and_namespaced(tmp_path: Path) -> None:
    a = make(tmp_path, namespace="spec")
    b = make(tmp_path, namespace="testcases")
    assert a.key("p") == a.key("p")
    assert a.key("p") != b.key("p"), "two namespaces must not collide on one prompt"
    assert len(a.key("p")) == 64
