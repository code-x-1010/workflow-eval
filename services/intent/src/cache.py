"""Content-addressed disk cache for prompt-derived work.

Built on day one rather than as a week-2 optimisation, because the corpus gets
re-run dozens of times: 40 prompts x an LLM call each is a 40-minute run, and
the same 40 prompts out of cache is 40 seconds. Ten times more iterations for an
afternoon's work. `datasets/corpus/manifest.json` already records
`prompt_sha256` per case for exactly this key.

Two properties matter more than speed:

* **The key includes a version.** A cache keyed on the prompt alone keeps
  serving specs produced by an extractor you have since changed, and you debug
  the old output for an hour before realising. Bump `version` whenever the
  producing code changes shape.
* **A bad entry is a miss, never an exception.** A truncated or hand-edited
  cache file must not take the service down; it is recomputed and overwritten.

Owner: P2. Nothing here imports an artifact, an AST or an adapter -- it caches
functions of a string.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(os.environ.get("WFEVAL_CACHE_DIR", ".cache/wfeval-intent"))


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0


@dataclass
class DiskCache:
    """JSON values on disk, keyed by sha256 of (namespace, version, payload).

    `enabled=False` turns the whole thing into a pass-through, which is what a
    test that wants to observe every computation uses.
    """

    root: Path = field(default_factory=lambda: DEFAULT_ROOT)
    namespace: str = "spec"
    version: str = "v1"
    enabled: bool = True
    stats: CacheStats = field(default_factory=CacheStats)

    def key(self, payload: str) -> str:
        # NUL-separated because it cannot occur in any of the three parts, so no
        # pair of (namespace, version, payload) can run together into the same
        # material string and collide. Byte-identical to the previous join form.
        material = f"{self.namespace}\x00{self.version}\x00{payload}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def path_for(self, payload: str) -> Path:
        return self.root / self.namespace / f"{self.key(payload)}.json"

    def get(self, payload: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self.path_for(payload)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Missing, unreadable or corrupt -- all three are a miss. A cache
            # that can fail a request is worse than no cache.
            return None
        value = entry.get("value")
        if not isinstance(value, dict):
            return None
        return value

    def put(self, payload: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self.path_for(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"namespace": self.namespace, "version": self.version, "value": value}
        # Write-then-rename: a reader never sees a half-written entry, and two
        # processes racing on the same key both end up with a complete file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entry, fh)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.stats.writes += 1

    def get_or_compute(
        self, payload: str, compute: Callable[[], dict[str, Any]]
    ) -> tuple[dict[str, Any], bool]:
        """Returns (value, was_cached). `compute` runs only on a miss -- that is
        the charter's D3-D4 bar: the same prompt twice costs zero LLM calls the
        second time."""
        cached = self.get(payload)
        if cached is not None:
            self.stats.hits += 1
            return cached, True
        self.stats.misses += 1
        value = compute()
        self.put(payload, value)
        return value, False
