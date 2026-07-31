"""Path setup so `pytest tests/unit/sandbox` works without a full `uv sync`.

Mirrors the Dockerfile's PYTHONPATH (packages/wfeval-core/src on the path,
repo root on the path for `services.*` imports). Scoped to this test
subtree only -- not a repo-wide conftest.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT, ROOT / "packages" / "wfeval-core" / "src", ROOT / "packages" / "wfeval-adapters" / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
