"""Single source of tunables for the Meeting Voice AI Lab.

Every model identifier, voice assignment, path, and audio parameter lives here.
Modules import from ``config`` instead of hard-coding values so an instructor can
change one place and keep the manual and API workflows aligned.

The Gemini model identifiers below were verified against the official
documentation on **2026-11-12**. Re-check the links in
``reference/OFFICIAL_LINKS.md`` before a new cohort; Google renames and retires
models regularly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
FIXTURE_DIR = DATA_DIR / "controlled-meeting"
ARCHIVE_DIR = DATA_DIR / "archive"

SCRIPT_PATH = FIXTURE_DIR / "meeting_script.json"
METADATA_PATH = FIXTURE_DIR / "meeting_metadata.json"
GROUND_TRUTH_PATH = FIXTURE_DIR / "ground_truth.json"

AUDIO_DIR = PROJECT_ROOT / "audio"
SEGMENTS_DIR = AUDIO_DIR / "generated_segments"
SEGMENTS_MANIFEST_PATH = SEGMENTS_DIR / "manifest.json"
MEETING_WAV_PATH = AUDIO_DIR / "meeting.wav"
MEETING_MANIFEST_PATH = AUDIO_DIR / "meeting_manifest.json"

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
WHISPERX_OUTPUT_DIR = OUTPUTS_DIR / "whisperx"
GEMINI_OUTPUT_DIR = OUTPUTS_DIR / "gemini"
COMPARISON_OUTPUT_DIR = OUTPUTS_DIR / "comparison"

# ---------------------------------------------------------------------------
# Gemini TTS models (verified 2026-11-12)
# ---------------------------------------------------------------------------

TTS_MODEL = "gemini-3.8-flash-tts"
TTS_MODEL_LITE = "gemini-3.8-flash-lite-tts"
TTS_MODEL_VERIFIED_ON = "2026-11-12"

#: The TTS models are served by the Interactions API on ``v1beta``. The
#: installed SDK defaults to ``v1``, where these models return 404, so the
#: version is pinned explicitly here and passed to the client.
TTS_API_VERSION = "v1beta"

TTS_DEFAULT_RESPONSE_MIME = "audio/wav"
TTS_REQUEST_TIMEOUT_SECONDS = 120

#: Each turn is an independent request, so several can be in flight at once.
#: Order in the output never depends on completion order: the manifest and the
#: assembled WAV are sorted by turn index. ``1`` restores strict serial runs.
#: A higher value only works if the account's per-minute limit allows that many
#: concurrent requests; it does not raise a daily cap.
TTS_CONCURRENCY = 4

#: The documented single-request multi-speaker cap for prebuilt voices.
#: The lab never submits all three participants in one request.
TTS_MAX_PREBUILT_SPEAKERS_PER_REQUEST = 2

# ---------------------------------------------------------------------------
# Audio target
# ---------------------------------------------------------------------------

#: Gemini unary TTS returns 24 kHz, mono, 16-bit PCM WAV by default.
TTS_NATIVE_SAMPLE_RATE = 24_000
TTS_NATIVE_CHANNELS = 1
TTS_NATIVE_SAMPLE_WIDTH_BYTES = 2

#: The assembled meeting keeps the native format so no resampling is needed in
#: the common path. Assembly can still resample imported or older segments.
MEETING_SAMPLE_RATE = 24_000
MEETING_CHANNELS = 1
MEETING_SAMPLE_WIDTH_BYTES = 2

#: Short silence between turns and a longer beat at section boundaries.
TURN_PAUSE_MS = 350
SECTION_PAUSE_MS = 900

# ---------------------------------------------------------------------------
# Environment variable names (never values)
# ---------------------------------------------------------------------------

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"
HF_TOKEN_ENV = "HF_TOKEN"
ENV_FILE = PROJECT_ROOT / ".env"

#: Official pages linked instead of quoting a price or a free-tier promise.
PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
USAGE_URL = "https://aistudio.google.com/usage"
TTS_DOCS_URL = "https://aistudio.google.com/docs/speech-generation"

# ---------------------------------------------------------------------------
# Local ASR: WhisperX + pyannote (versions verified 2026-11-12)
# ---------------------------------------------------------------------------

#: WhisperX accepts faster-whisper model names. ``small.en`` is the classroom
#: default because it runs on CPU in minutes; use ``large-v3`` on a CUDA GPU.
WHISPERX_MODEL = "small.en"
WHISPERX_LANGUAGE = "en"
WHISPERX_MODEL_VERIFIED_ON = "2026-11-12"

#: ``None`` lets WhisperX choose the documented default wav2vec2 alignment
#: model for the detected language. Set a name to pin one.
WHISPERX_ALIGN_MODEL: str | None = None

#: Current pyannote pipeline used by WhisperX 3.8.6. It is gated on Hugging
#: Face, so diarization needs ``HF_TOKEN`` and accepted model conditions.
WHISPERX_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

WHISPERX_BATCH_SIZE = 8
WHISPERX_CPU_COMPUTE_TYPE = "int8"
WHISPERX_CUDA_COMPUTE_TYPE = "float16"
WHISPERX_DEVICE_AUTO = "auto"
WHISPERX_DEVICES = ("auto", "cuda", "cpu")

#: WhisperX models expect 16 kHz mono float32. The meeting WAV stays untouched;
#: this is only the in-memory decoding target.
WHISPERX_SAMPLE_RATE = 16_000

#: The ``UNKNOWN`` label is preserved when diarization cannot attribute a
#: segment. Labels are never rewritten to participant names in this stage.
UNKNOWN_SPEAKER = "UNKNOWN"


# ---------------------------------------------------------------------------
# Cloud ASR: Gemini Transcribe (verified 2026-11-12)
# ---------------------------------------------------------------------------

#: The dedicated transcription model documented through the Interactions API.
#: A model ID is not a promise of access: the key's project must be allowed to
#: use it. Re-verify against TRANSCRIBE_DOCS_URL before a new cohort.
TRANSCRIBE_MODEL = "gemini-3.5-transcribe"
TRANSCRIBE_MODEL_VERIFIED_ON = "2026-11-12"
TRANSCRIBE_API_VERSION = "v1beta"
TRANSCRIBE_DOCS_URL = "https://aistudio.google.com/docs/transcribe"

#: BCP-47 hints. The fixture is en-US, and WhisperX is also configured for
#: English, so the comparison is not confounded by language setup. Pass an
#: empty sequence to let the model detect the language instead.
TRANSCRIBE_DEFAULT_LANGUAGE_CODES: tuple[str, ...] = ("en-US",)

#: Verbatim mode preserves fillers and repetitions. Diarization uses the
#: documented ``speaker`` mode. Word timestamps are documented as compatible
#: with diarization but may reduce accuracy; the lab enables them so both
#: routes can be compared on the same fields.
TRANSCRIBE_DIARIZATION_MODE = "speaker"
TRANSCRIBE_DEFAULT_DIARIZE = True
TRANSCRIBE_DEFAULT_WORD_TIMESTAMPS = True

#: Documented limits: 1 hour for a unary request, 30 minutes when diarization
#: or word timestamps are requested. Audio past the active limit is truncated
#: by the service, so this lab refuses it instead of silently losing speech.
TRANSCRIBE_UNARY_MAX_SECONDS = 3600
TRANSCRIBE_DIARIZATION_MAX_SECONDS = 1800

TRANSCRIBE_REQUEST_TIMEOUT_SECONDS = 600
TRANSCRIBE_UPLOAD_ACTIVE_TIMEOUT_SECONDS = 180

#: ``store=False`` asks the API not to retain the interaction for later
#: retrieval. The uploaded file is deleted after the run either way.
TRANSCRIBE_DEFAULT_STORE_REMOTE = False

#: Word-level output has no segment boundaries, so the normalizer starts a new
#: segment on a speaker change or a silence longer than this gap.
TRANSCRIBE_SEGMENT_GAP_SECONDS = 1.0

#: Documented: diarization supports up to eight speakers, and attribution for
#: three or more is experimental. The lab says so instead of implying accuracy.
TRANSCRIBE_MAX_SPEAKERS = 8


# ---------------------------------------------------------------------------
# Voice plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoiceProfile:
    """One stable synthetic voice assigned to one participant.

    ``style`` becomes the ``speech_metadata`` annotation on every turn. It
    carries the delivery note from the fixture, never the participant's name.
    """

    speaker_id: str
    full_name: str
    gender: str
    voice_name: str
    style: str
    rationale: str


#: The three voices are deliberately distinct; Bob and Greg are both male, so
#: they must not share a voice. All names below are documented prebuilt Gemini
#: voices (30 available at verification time). Nothing is cloned or impersonated.
VOICE_PLAN: dict[str, VoiceProfile] = {
    "ANN": VoiceProfile(
        speaker_id="ANN",
        full_name="Ann Smith",
        gender="female",
        voice_name="Kore",
        style="calm, clear, mid-range, organized",
        rationale=(
            "Kore is a clear mid-range female prebuilt voice; it matches the "
            "fixture's calm project-manager delivery note."
        ),
    ),
    "BOB": VoiceProfile(
        speaker_id="BOB",
        full_name="Bob Hawkins",
        gender="male",
        voice_name="Puck",
        style="measured, thoughtful, lower-mid range",
        rationale=(
            "Puck is a male prebuilt voice with a measured timbre; kept "
            "distinct from Greg's voice so diarization has two clean male "
            "clusters."
        ),
    ),
    "GREG": VoiceProfile(
        speaker_id="GREG",
        full_name="Greg Cox",
        gender="male",
        voice_name="Charon",
        style="firm, direct, lower range",
        rationale=(
            "Charon is a lower, firmer male prebuilt voice; clearly different "
            "from Bob without using an exaggerated accent."
        ),
    ),
}

#: Documented prebuilt voices at verification time. A voice outside this set is
#: rejected unless the caller explicitly opts in, which prevents a typo or a
#: retired name from silently reaching the API.
PREBUILT_VOICES: frozenset[str] = frozenset(
    {
        "Zephyr",
        "Puck",
        "Charon",
        "Kore",
        "Fenrir",
        "Leda",
        "Orus",
        "Aoede",
        "Callirrhoe",
        "Autonoe",
        "Enceladus",
        "Iapetus",
        "Umbriel",
        "Algieba",
        "Despina",
        "Erinome",
        "Algenib",
        "Rasalgethi",
        "Laomedeia",
        "Achernar",
        "Alnilam",
        "Schedar",
        "Gacrux",
        "Pulcherrima",
        "Achird",
        "Zubenelgenubi",
        "Vindemiatrix",
        "Sadachbia",
        "Sadaltager",
        "Sulafat",
    }
)
