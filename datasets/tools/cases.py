"""The whole corpus: 30 reverse-generated pairs + 10 hand-written under-specified."""
from __future__ import annotations

from .case import Case
from .cases_reverse import REVERSE
from .cases_underspecified import UNDERSPECIFIED

ALL_CASES: list[Case] = [*REVERSE, *UNDERSPECIFIED]

__all__ = ["ALL_CASES", "REVERSE", "UNDERSPECIFIED", "Case"]
