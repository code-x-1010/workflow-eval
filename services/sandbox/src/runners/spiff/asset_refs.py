"""Optional element_id -> asset_ref map, via P1's wfeval-adapters.

wfeval-adapters may not exist yet (it's P1's package; `packages/wfeval-adapters`
is empty as of this writing). Never hard-depend on another agent's package
landing on schedule -- same philosophy as P1's own "L2 skipped when the asset
registry is down" graceful degradation. If the adapter isn't importable, or
parsing fails for any reason, asset_ref-keyed TaskStub lookups are simply
unavailable and element_id-keyed lookups (always available -- Spiff's own BPMN
parser gives us element ids directly) carry the whole load.
"""
from __future__ import annotations

from typing import Any


def asset_ref_map(artifact: dict[str, Any]) -> dict[str, str]:
    try:
        from wfeval.adapters import parse
    except ImportError:
        return {}
    try:
        ast = parse(artifact)
    except Exception:  # noqa: BLE001 -- an unfinished/unstable adapter must degrade, not crash the runner
        return {}
    return {el.id: el.asset_ref for el in ast.elements if el.asset_ref}
