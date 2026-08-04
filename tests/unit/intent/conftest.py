"""Path setup so `pytest tests/unit/intent` works without a full `uv sync`.

Mirrors the Dockerfile's PYTHONPATH. Same approach as tests/unit/sandbox/
conftest.py, scoped to this subtree. See docs/decisions/0007.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT, ROOT / "packages" / "wfeval-core" / "src", ROOT / "packages" / "wfeval-adapters" / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
