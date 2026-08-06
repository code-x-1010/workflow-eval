"""Test generation. Derived from the PROMPT and the Spec, NEVER from the artifact.

**This package must never import `wfeval.core.ast` or `wfeval.adapters`, and
there is no code path by which it could receive an artifact.** That is leg 2 of
the three-legged anti-circularity guarantee in docs/agents/P2-intent-testgen.md,
enforced by `.importlinter` contract 2 (live from D8 -- see decision 0013 for why
it sat commented out until this package existed).

The reason is the whole point of the execution tier: tests derived from the
generated workflow are tests the generated workflow passes. A suite built that
way reports 100% and means nothing. Alignment -- which *does* read the artifact --
lives one directory up in `align.py`, and the two must not meet.

If you find yourself wanting an element id in here, that is the signal you have
drifted. Express the assertion semantically and let P3's matcher resolve it.
"""
from __future__ import annotations

from .generate import generate

__all__ = ["generate"]
