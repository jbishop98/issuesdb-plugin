"""Make the repo root importable so `import pilot` works without installation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
