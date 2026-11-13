"""Evaluation and comparison of the two ASR routes.

This package is the only place that is *allowed* to see the ground truth and an
ASR output together. It never feeds anything back into an ASR system; it reads
the files each route already wrote under ``outputs/``.

Modules:

- :mod:`src.evaluation.text` — tokenization and word-level alignment (WER).
- :mod:`src.evaluation.speakers` — cluster mapping, DER, turn boundaries.
- :mod:`src.evaluation.compare` — builds the comparison document.
- :mod:`src.evaluation.report` — writes JSON, Markdown, and HTML.
- :mod:`src.evaluation.__main__` — the ``build`` CLI.
"""
