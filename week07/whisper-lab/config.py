"""Every tunable for Whisper Lab lives here.

Change a value in this file instead of hunting through the CLI, server, and
engine. The same settings are reused by every entry point.
"""

import os
from pathlib import Path

# --- Paths ---------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
SAMPLES_DIR = ROOT / "samples"
MODELS_DIR = ROOT / "models"  # faster-whisper downloads weights here
JOBS_DIR = ROOT / "jobs"  # uploads + generated transcripts

# --- Models --------------------------------------------------------------

# Curated list shown by the CLI and the web UI. Sizes are the approximate
# float16 download size of the CTranslate2 weights (roughly twice the parameter
# count); speed is relative to large-v3 on the same machine. "turbo" is the
# OpenAI Whisper large-v3-turbo distilled variant.
MODEL_CATALOG = [
    {"name": "tiny", "size": "~72 MB", "speed": "~32x", "note": "Draft quality; fastest"},
    {"name": "base", "size": "~138 MB", "speed": "~16x", "note": "Good for clean English"},
    {"name": "small", "size": "~461 MB", "speed": "~6x", "note": "Best default for a laptop"},
    {"name": "medium", "size": "~1.5 GB", "speed": "~2x", "note": "Noticeably better, slower"},
    {"name": "large-v3-turbo", "size": "~1.5 GB", "speed": "~8x", "note": "Large-v3 quality, much faster"},
    {"name": "large-v3", "size": "~3 GB", "speed": "1x", "note": "Best accuracy, most VRAM"},
    {"name": "distil-large-v3", "size": "~1.5 GB", "speed": "~12x", "note": "English-only, near large-v3"},
]

MODEL_NAMES = [model["name"] for model in MODEL_CATALOG]

# "small" runs comfortably on a CPU. Switch to "large-v3-turbo" when you have
# a GPU with at least 6 GB of free VRAM.
DEFAULT_MODEL = "small"

# Device and precision. "auto" resolves to CUDA/float16 when a GPU is visible,
# otherwise CPU/int8.
DEFAULT_DEVICE = "auto"
DEFAULT_COMPUTE_TYPE = "auto"

BEAM_SIZE = 5
VAD_FILTER = True
VAD_MIN_SILENCE_MS = 500
WORD_TIMESTAMPS = False
INITIAL_PROMPT = ""  # e.g. names, product terms, acronyms Whisper keeps missing

# Whisper supports 90+ languages; the UI offers a short list plus auto-detect.
LANGUAGES = [
    ("auto", "Auto-detect"),
    ("en", "English"),
    ("cs", "Czech"),
    ("de", "German"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("it", "Italian"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
]

# --- Local LLM (Ollama) ---------------------------------------------------

# Ollama's native HTTP API. Start it with `ollama serve`; there is no /v1
# suffix because the OpenAI-compatible endpoint is not used.
LLM_BASE_URL = os.getenv("WHISPER_LAB_LLM_BASE_URL", "http://localhost:11434")

# Empty means "use the first installed completion model". Pin one to be
# explicit, e.g. set WHISPER_LAB_LLM_MODEL=qwen3.5:4b before starting.
LLM_MODEL = os.getenv("WHISPER_LAB_LLM_MODEL", "").strip()

LLM_TIMEOUT_S = 120.0

# Context window requested per request; 24,000 characters is roughly 6,000
# tokens, and Ollama's own default is too small for that plus the answer.
LLM_NUM_CTX = 16_384

# Keep the prompt inside a local model's context window. Larger transcripts
# still transcribe fine; they are just truncated for the summary.
LLM_MAX_CHARS = 24_000

# --- Web UI --------------------------------------------------------------

HOST = "127.0.0.1"
PORT = 8000
MAX_UPLOAD_MB = 200
JOB_TTL_S = 6 * 3600

AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mkv", ".mov", ".webm", ".avi",  # video: faster-whisper decodes the audio track
}
