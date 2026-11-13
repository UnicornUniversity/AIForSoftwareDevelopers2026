"""Local WhisperX + pyannote adapter.

The vendor boundary is ``engine.py``; normalization and export know nothing
about WhisperX. Raw output is preserved before it is normalized so a report can
always be traced back to what the model actually returned.
"""
