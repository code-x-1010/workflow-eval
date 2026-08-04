"""One corpus entry: a prompt, a reference artifact, and its provenance."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# How the (prompt, artifact) pair came to exist. Recorded per case in
# manifest.json because it changes how the pair may be used:
#
#   reverse_generated  -- the reference artifact was authored first from a
#                         common process template, then described in natural
#                         language and that description became the prompt. The
#                         reference is genuine ground truth: it is what the
#                         prompt was written from. The prompt is unrealistically
#                         detailed -- real users do not write like this.
#
#   hand_written       -- the prompt was written first, deliberately
#                         under-specified, in the register real users actually
#                         use. The reference artifact is ONE reasonable reading
#                         of an ambiguous prompt, not ground truth. Scoring
#                         alignment strictly against it will punish a generator
#                         for making a different but equally defensible choice.
PROVENANCE = ("reverse_generated", "hand_written")


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    domain: str
    provenance: str
    prompt: str
    process_id: str
    nodes: list[dict[str, Any]]
    patterns: tuple[str, ...] = ()
    # SPEC-* codes /v1/spec is expected to raise for this prompt. Ground truth
    # for the D5 sufficiency work; see docs/decisions/0008-spec-code-registry.md.
    expected_diagnostics: tuple[str, ...] = ()
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCE:
            raise ValueError(f"{self.id}: unknown provenance {self.provenance!r}")

    @property
    def under_specified(self) -> bool:
        return self.provenance == "hand_written"

    @property
    def reference_is_ground_truth(self) -> bool:
        """False when the reference is one reading of an ambiguous prompt."""
        return self.provenance == "reverse_generated"
