"""Ensure the backend root is importable so ``import tests.fixtures...`` works."""

import sys
from pathlib import Path

_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
