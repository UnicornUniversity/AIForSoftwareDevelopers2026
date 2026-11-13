"""Text-to-Speech stage: script -> per-turn segments -> one meeting WAV.

The TTS stage is deliberately separate from ASR. Its output is one WAV file and
a manifest of time-aligned turns; neither ASR route knows the participant names
or the voice assignments.
"""

from src.tts.voices import VoiceAssignment, validate_voice_plan, voice_assignments

__all__ = ["VoiceAssignment", "validate_voice_plan", "voice_assignments"]
