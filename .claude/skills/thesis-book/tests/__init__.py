"""Tests for the corpus-to-book tool.

Run from this skill's directory with::

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
