from __future__ import annotations

import sys
from pathlib import Path


V1_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = V1_ROOT.parents[2]
BACKEND = V1_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

