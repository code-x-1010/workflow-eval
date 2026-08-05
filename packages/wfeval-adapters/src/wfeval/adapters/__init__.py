"""wfeval-adapters — platform XML -> canonical WorkflowAST.

Owner: P1. Depends on wfeval.core (never the reverse -- see
.importlinter contract 1). NEVER imported by services/intent/src/testgen/**
(.importlinter contract 2): testgen must never see the artifact, only the
prompt, or the execution tier becomes a tautology. See AGENTS.md and
docs/agents/P2-intent-testgen.md.

`parse` is the cross-service entry point -- P3 already depends on this exact
name and call shape for BPMN (services/sandbox/src/runners/spiff/asset_refs.py,
written defensively against this package not existing yet via
`from wfeval.adapters import parse` inside a try/except ImportError). It
takes the same `artifact` shape as every service contract
(`{"format": "bpmn"|"dmn", "content": "<xml>"}`, or a bare XML string as a
convenience), matching how services/sandbox/.../engine.py already unwraps
`artifact.get("content", artifact)`.

For `format="bpmn"` this always returns a `WorkflowAST`, unchanged from
before -- P3's existing call site is untouched. For `format="dmn"` it
returns a `DecisionModel` instead: a decision table is rows-and-columns, not
nodes-and-edges, and forcing it into `WorkflowAST`'s shape would be the kind
of "guessed at" modelling this codebase's house style explicitly avoids (see
wfeval.core.dmn's module docstring). Callers that need to know which they
got should check `artifact["format"]` themselves, or call `parse_bpmn`/
`parse_dmn` directly.
"""
from __future__ import annotations

from typing import Any

from wfeval.core.ast import WorkflowAST
from wfeval.core.dmn import DecisionModel

from .bpmn import parse as parse_bpmn
from .dmn import parse as parse_dmn
from .errors import AdapterParseError


def parse(artifact: dict[str, Any] | str, *, platform: str = "uipath_maestro") -> WorkflowAST | DecisionModel:
    if isinstance(artifact, dict):
        content = artifact.get("content", "")
        fmt = artifact.get("format", "bpmn")
    else:
        content, fmt = artifact, "bpmn"
    if fmt == "dmn":
        return parse_dmn(content)
    return parse_bpmn(content, platform=platform)


__all__ = ["AdapterParseError", "DecisionModel", "WorkflowAST", "parse", "parse_bpmn", "parse_dmn"]
