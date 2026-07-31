from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "packages" / "wfeval-core" / "src",):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
