"""Golden-example loader. This is how four isolated agents stay unblocked.

Every service supports WFEVAL_STUB_DEPS=1, in which case it serves the committed
examples in contracts/examples/ instead of calling a dependency that may not
exist yet. P3 builds their entire execution loop against P2's example test cases
on D3 -- six days before P2's generator actually works.

Keep your examples realistic. An unrealistic example is worse than none: the
agent consuming it builds against a fiction and breaks the day real output lands.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

EXAMPLES = Path(__file__).resolve().parents[4].parent / "contracts" / "examples"


def stubbing() -> bool:
    return os.environ.get("WFEVAL_STUB_DEPS", "1") == "1"


def golden(name: str) -> dict[str, Any]:
    """Load contracts/examples/<name>. Raises loudly -- a missing example means
    the producing agent has not met their D2 obligation."""
    path = EXAMPLES / name
    if not path.exists():
        raise FileNotFoundError(
            f"Missing golden example: {path}\n"
            f"The owning agent must commit this by D2 (see AGENTS.md section 4)."
        )
    data: dict[str, Any] = json.loads(path.read_text())
    return data
