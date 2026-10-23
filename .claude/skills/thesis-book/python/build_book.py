#!/usr/bin/env python3
"""Entry point for the corpus-to-book tool.

The program lives inside the skill; paths in the settings file resolve against
the settings file's own directory, so the current directory does not matter.
Examples from the repository root::

    python .claude/skills/thesis-book/python/build_book.py init \\
        --settings week04/kangaroo-skill/settings.json
    python .claude/skills/thesis-book/python/build_book.py status \\
        --settings week04/kangaroo-skill/settings.json
    python .claude/skills/thesis-book/python/build_book.py context \\
        --settings week04/kangaroo-skill/settings.json --chapter 1
    python .claude/skills/thesis-book/python/build_book.py render \\
        --settings week04/kangaroo-skill/settings.json --chapter 1
    python .claude/skills/thesis-book/python/build_book.py render \\
        --settings week04/kangaroo-skill/settings.json --all
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bookbuild.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
