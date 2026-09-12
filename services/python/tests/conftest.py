"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

# Ensure src/ is on the path for imports
src_dir = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_dir))
