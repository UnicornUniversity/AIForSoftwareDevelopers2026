"""Gemini cloud transcription route (prompt 04).

The vendor boundary is :mod:`src.asr.gemini.client`; everything else in this
package works on ordinary dicts so tests run offline with no network, no key,
and no SDK call.

Both ASR routes normalize into :class:`src.schema.NormalizedTranscript`. This
route keeps Gemini's anonymous speaker labels (``spk_1``, ``spk_2``) exactly as
returned and never maps them to participants.
"""

from __future__ import annotations
