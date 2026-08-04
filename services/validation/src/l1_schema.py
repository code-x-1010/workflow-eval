"""L1: schema conformance.

Full formal BPMN 2.0 / DMN 1.3 XSD validation is NOT implemented here. The
official schema is a multi-file bundle (Semantic.xsd, BPMNDI.xsd, DI.xsd,
DC.xsd, BPMN20.xsd, plus imports) and embedding it from memory risked getting
it subtly wrong -- the house rules are explicit that an unvalidated analyser
that hard-fails good artifacts destroys trust in the whole layer and doesn't
get it back. What's here is real and verified instead: XML well-formedness
and every BPMN construct wfeval-adapters understands (which already covers
"is this valid enough to reason about at all"), plus duplicate-id detection,
which the adapter itself does not check. See docs/handoff/P1.md for the
XSD gap and how to close it properly (a real official schema file, not a
memory reconstruction).
"""
from __future__ import annotations

from wfeval.adapters.bpmn import parse as parse_bpmn
from wfeval.adapters.errors import AdapterParseError
from wfeval.core.ast import WorkflowAST
from wfeval.core.diagnostics import Diagnostic, Severity


def check(content: str, *, platform: str) -> tuple[WorkflowAST | None, list[Diagnostic], bool]:
    """Returns (ast, diagnostics, schema_validity). ast is None only when
    parsing failed outright -- callers must short-circuit L2-L4 in that case,
    there is nothing to run them against."""
    try:
        ast = parse_bpmn(content, platform=platform)
    except AdapterParseError as e:
        return None, [Diagnostic(
            code="SCH-PARSE-FAILED",
            severity=Severity.ERROR,
            message=str(e),
            suggested_fix="Fix the reported XML/BPMN construct and resubmit. "
                           "L2-L4 do not run against an artifact that fails to parse.",
        )], False

    diagnostics = _duplicate_ids(ast)
    schema_validity = not any(d.severity == Severity.ERROR for d in diagnostics)
    return ast, diagnostics, schema_validity


def _duplicate_ids(ast: WorkflowAST) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()
    for el in ast.elements:
        if el.id in seen:
            diagnostics.append(Diagnostic(
                code="SCH-DUPLICATE-ID", severity=Severity.ERROR,
                message=f"Element id '{el.id}' is used more than once.",
                suggested_fix=f"Rename one of the elements sharing id '{el.id}' to a unique id.",
                element_id=el.id, locator=el.locator,
            ))
        else:
            seen.add(el.id)
    for flow in ast.flows:
        if flow.id in seen:
            diagnostics.append(Diagnostic(
                code="SCH-DUPLICATE-ID", severity=Severity.ERROR,
                message=f"Flow id '{flow.id}' is used more than once.",
                suggested_fix=f"Rename one of the flows sharing id '{flow.id}' to a unique id.",
                element_id=flow.id,
            ))
        else:
            seen.add(flow.id)
    return diagnostics
