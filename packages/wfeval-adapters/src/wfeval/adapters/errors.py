"""Adapter-level parse errors.

Raised when input cannot be walked into a WorkflowAST at all: malformed XML,
a missing <definitions>/<process> root, or a BPMN construct this adapter does
not yet map to an ElementKind. Structural/schema *validity* of an otherwise-
parseable artifact is Validation's job (L1), not this package's.
"""
from __future__ import annotations


class AdapterParseError(Exception):
    """The artifact could not be turned into a WorkflowAST."""
