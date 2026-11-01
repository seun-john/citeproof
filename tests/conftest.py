"""Make the browser demo's logic importable.

docs/py is appended, not prepended, so `import citeproof` keeps resolving to src/ (the editable
install). tests/test_demo_logic.py separately proves docs/py/citeproof is an exact copy of src/.
"""

from __future__ import annotations

import sys
from pathlib import Path

DEMO_PY = Path(__file__).resolve().parent.parent / "docs" / "py"
if str(DEMO_PY) not in sys.path:
    sys.path.append(str(DEMO_PY))
