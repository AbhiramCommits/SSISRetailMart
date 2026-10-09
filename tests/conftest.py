"""Shared pytest fixtures and path wiring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "data" / "generator"

for path in (ROOT, GENERATOR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
