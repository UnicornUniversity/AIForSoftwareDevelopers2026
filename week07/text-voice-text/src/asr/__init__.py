"""Automatic speech recognition routes for the Meeting Voice AI Lab.

Each route is an adapter behind its own subpackage. Both normalize into the
shared ``src.schema.NormalizedTranscript`` so evaluation never depends on a
vendor response shape.
"""
