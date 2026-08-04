"""Path setup so `make contract` works without a full `uv sync`.

Mirrors the Dockerfile's PYTHONPATH (the shared packages' src dirs, plus the
repo root for `services.*` imports). Same approach as tests/unit/sandbox/
conftest.py, scoped to this test subtree. Harmless once the workspace install
is fixed -- these entries are then already on the path and the loop is a no-op.
See docs/decisions/0007-uv-workspace-does-not-sync.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "packages" / "wfeval-core" / "src", ROOT / "packages" / "wfeval-adapters" / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
