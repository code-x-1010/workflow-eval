"""L2: reference integrity -- every task's asset_ref must resolve against
Sandbox's deployed asset registry (`GET /v1/assets`).

Never hard-depends on Sandbox being up -- per the charter, "a validation
service that goes down when the sandbox goes down is a validation service
nobody can rely on." `check()` returns `(diagnostics, gate_value)` where
`gate_value` is `None` specifically when the registry was unreachable, kept
distinct from `True`/`False` (a real answer about references) so the caller
records `tiers_skipped["L2"]` rather than a `gates["reference_integrity"]`
value it can't actually vouch for.

DEFERRED, not implemented here -- the charter's L2 row also lists two more
checks that don't have anything to run against yet:
  - "referenced decisions exist" -- there is no DMN adapter yet (D8), so
    there are no decision references to check.
  - "variables declared before use" -- `l4_dataflow.py` already does a
    considerably more rigorous version of this (CFG-dominance based, not a
    flat existence check); a second, weaker implementation here would be
    redundant, not complementary.
"""
from __future__ import annotations

import httpx

from wfeval.core.ast import Element, WorkflowAST
from wfeval.core.diagnostics import Diagnostic, Severity

_TIMEOUT_SECONDS = 2.0


def check(ast: WorkflowAST, *, assets_url: str) -> tuple[list[Diagnostic], bool | None]:
    """Returns (diagnostics, gate_value). gate_value is None iff the asset
    registry was unreachable -- an artifact with no asset_ref at all trivially
    passes (True) without even calling out, since there's nothing to check."""
    refs: dict[str, list[str]] = {}
    for el in ast.elements:
        if el.asset_ref:
            refs.setdefault(el.asset_ref, []).append(el.id)
    if not refs:
        return [], True

    try:
        resp = httpx.get(assets_url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError):
        return [], None

    assets = {a["name"]: a for a in body.get("assets", []) if isinstance(a, dict) and "name" in a}
    folder = body.get("folder", "the deployed asset registry")

    diagnostics: list[Diagnostic] = []
    for ref, element_ids in refs.items():
        asset = assets.get(ref)
        for element_id in element_ids:
            owner: Element | None = ast.element(element_id)
            locator = owner.locator if owner else None
            name = (owner.name or element_id) if owner else element_id
            if asset is None:
                diagnostics.append(Diagnostic(
                    code="REF-ASSET-NOT-FOUND", severity=Severity.ERROR,
                    message=f"'{name}' references asset '{ref}', which is not in {folder}.",
                    suggested_fix=f"Deploy an asset named '{ref}', or fix the reference on "
                    f"'{element_id}' to match an existing asset name.",
                    element_id=element_id, locator=locator,
                ))
            elif not asset.get("deployed", False):
                diagnostics.append(Diagnostic(
                    code="REF-ASSET-NOT-DEPLOYED", severity=Severity.ERROR,
                    message=f"'{name}' references asset '{ref}', which exists in {folder} but "
                    f"is not deployed.",
                    suggested_fix=f"Deploy '{ref}', or point '{element_id}' at an asset that's "
                    f"already live.",
                    element_id=element_id, locator=locator,
                ))

    gate_value = not any(d.severity == Severity.ERROR for d in diagnostics)
    return diagnostics, gate_value
