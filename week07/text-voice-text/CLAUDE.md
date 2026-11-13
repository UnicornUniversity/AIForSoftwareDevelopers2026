# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This file is scoped to `week07/text-voice-text`. The repo-root `CLAUDE.md` describes the other
weeks; where the two touch the same subject, this one wins for this directory.

## What this project is

A self-contained "Meeting Voice AI Lab" (Python 3.11). It runs one controlled, fictional
three-speaker meeting through three stages for comparison:

1. **TTS** — turn script → per-turn WAVs → one meeting WAV (`src/tts`).
2. **ASR** — the same WAV through two routes, normalized to one schema (`src/asr`):
   local WhisperX + pyannote, and cloud Gemini Transcribe.
3. **Evaluation** — WER/DER against the fixture's ground truth, plus a confusion/mapping report
   (`src/evaluation`).

There is no package/build system beyond `requirements.txt`; everything is run as modules from this
directory.

## Commands

The project has its own `uv`-created virtualenv at `.venv` (Python 3.11). From
`week07/text-voice-text`:

```bash
# base install (TTS + evaluation + tests)
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

# optional local ASR stack (large: torch, whisperx, pyannote)
uv pip install --python .venv\Scripts\python.exe -r requirements-asr.txt

# full offline suite: 256 tests, ~8 s, no network, no API key, no model download
.venv\Scripts\python.exe -m pytest -q

# single file / single test
.venv\Scripts\python.exe -m pytest tests/evaluation/test_compare.py -q
.venv\Scripts\python.exe -m pytest tests/evaluation/test_text.py -q -k alignment
```

### Pipeline commands (all from this directory)

```bash
python -m src.tts plan                 # offline; prints voice + turn plan
python -m src.tts run --yes            # synthesize every turn with Gemini, then assemble
python -m src.tts synthesize --yes     # TTS only; --limit N and --concurrency N supported
python -m src.tts assemble             # segment manifest -> audio/meeting.wav + timeline manifest
python -m src.tts ingest --from DIR    # no-key/manual route: DIR/turn_001_ANN.wav, ...
python -m src.tts import-wav FILE      # bring an external meeting WAV in unchanged
python -m src.tts status               # what has been generated so far

python -m src.asr.whisperx check       # device/token/package/audio status; downloads nothing
python -m src.asr.whisperx run         # needs HF_TOKEN if diarizing; --no-diarize to skip
python -m src.asr.whisperx run --device cpu --no-diarize

python -m src.asr.gemini check         # key/SDK/model/audio status; uploads nothing
python -m src.asr.gemini run --yes     # uploads the WAV, transcribes, deletes the upload

python -m src.evaluation build         # -> outputs/comparison/comparison.{json,md,html}

python scripts/build_controlled_fixture.py   # regenerate data/ (the authored source of truth)
```

`python -m src.tts assemble` refuses to run on a partial segment set; `synthesize --limit` is for
iterating without producing a meeting WAV. The cloud commands print a cost/privacy notice and refuse
to proceed without `--yes` (or a TTY confirmation).

## Architecture and invariants

**Data flow (one direction):**

```
data/controlled-meeting/*  ->  TTS  ->  audio/meeting.wav + audio/meeting_manifest.json
                                         |
                          +--------------+--------------+
                          v                             v
              outputs/whisperx/                outputs/gemini/
        transcript.{json,txt,srt,vtt}     transcript.{json,txt,srt,vtt}
                          \                             /
                           +--------  evaluation  ------+
                                          |
                          outputs/comparison/comparison.{json,md,html}
```

### The blind-comparison rule is the core design constraint

The fixture's script, metadata, participant names, and `ground_truth.json` are **TTS and evaluation
truth only**. No ASR route may receive them. This is enforced structurally, not by convention:

- `src/evaluation/compare.py` is the only module that reads ground truth. ASR modules do not
  import anything that can expose it.
- The TTS request body carries only the spoken turn text plus a `speech_metadata` delivery-style
  annotation — never names, genders, roles, or the turn map (`src/tts/gemini_tts.py`).
- The Gemini ASR request body carries only the uploaded audio URI, MIME type, and explicit
  transcription options (`src/asr/gemini/request.py`).
- Speaker labels stay anonymous (`SPEAKER_00`, `spk_1`, `UNKNOWN`). Do not add a step that renames
  them to participants; mapping is an evaluation output.

Preserve that separation when adding features. A change that leaks the turn map or names into an
ASR request breaks the comparison even if every test passes.

### One WAV rule

Both ASR routes consume the exact same `audio/meeting.wav`. `import-wav` copies an external file
byte-for-byte; the ASR stages decode it in memory (16 kHz mono float32) and never rewrite it. Any
derived per-route file must be traceable to that one SHA-256.

### Shared schema is the contract

`src/schema.py` defines `NormalizedTranscript` (segments + words + anonymous speaker labels). Both
ASR routes normalize into it before anything else touches their output; exports
(`src/asr/export.py`) and evaluation are written against the schema, never vendor response types.
The raw vendor dump is kept separately for audit. When a vendor shape changes, fix the adapter
(`src/asr/gemini/parse.py`, `src/asr/whisperx/normalize.py`), not the schema or evaluators.

### `src/config.py` is the single source of tunables

Paths, model IDs, voice assignments, audio parameters, documented limits, and **environment
variable names** live there. Model IDs are pinned with a "verified on 2026-11-12" date; re-check
`reference/OFFICIAL_LINKS.md` before bumping. Note the TTS and transcription clients explicitly pin
the API version to `v1beta` (the SDK default `v1` 404s for these models).

### TTS stage

- Gemini prebuilt multi-speaker TTS supports at most **two** voices per request, so a three-person
  meeting is synthesized **one turn per request** and concatenated. Do not claim a single
  three-speaker request works.
- Order comes from `turn.index`, never call-completion order: synthesis may run concurrently, but
  the manifest and assembled WAV are always sorted by index (`src/tts/segments.py`).
- `src/tts/voices.py` validates the plan: every participant covered, voice gender matches metadata,
  two same-gender participants never share a voice, and voice names must be in the documented
  prebuilt allowlist.
- Segment filenames are `turn_%03d_%s.wav` and shared by the API and manual workflows.
- `assemble` derives the reference timeline from **actual segment durations plus configured pauses**,
  not from utterance order. That timeline is evaluation metadata and never reaches ASR. An imported
  WAV has no segment manifest, so its timeline is empty and DER must be reported as unavailable.
- The manifest records per-file SHA-256; an existing segment is reused only if its hash still
  matches, and the manifest is rewritten after every successful turn so an interrupted run resumes.

### WhisperX ASR route

- `src/asr/whisperx/engine.py` is the only module that knows WhisperX/pyannote; imports are lazy so
  normalization and export tests run without the multi-GB stack.
- Audio is decoded with `soundfile` and passed in memory as 16 kHz mono, deliberately avoiding
  WhisperX's `ffmpeg` subprocess and torchcodec. Do not switch to file-path decoding.
- `HF_TOKEN` is read from the environment only (no flag, no config field) and is never logged;
  diarization's gated pyannote model needs it. Use `--no-diarize` to run without it.
- `auto` device resolves to CUDA only when `torch.cuda.is_available()`; CPU defaults to `int8`.
  Error messages encode the verified PyTorch/CUDA combination — keep them actionable.

### Gemini ASR route

- Flow: upload via Files API → poll until ACTIVE → `interactions.create` → **delete the uploaded file
  in `finally`**, even on failure. Retention defaults to `store=False`.
- Duration limits are checked *before* upload because the service truncates past-limit audio while
  still reporting success (1 h unary, 30 min with diarization/word timestamps).
- `custom_vocabulary` is documented as incompatible with diarization and word timestamps; the lab
  refuses to build such a request instead of letting the API reject it.
- SDK errors are translated by HTTP status into student-readable classes
  (`src/asr/gemini/client.py`); never print the key.

### Evaluation stage

- WER is word-level and symmetric: `verbatim` (primary, keeps fillers/repetitions) and
  `filler_removed` (clearly supplementary). `src/evaluation/text.py` uses a deterministic
  Levenshtein backtrace so counts are reproducible.
- DER is computed **only** when a real TTS timeline exists. Without one it is reported as
  unavailable, never zero. `text_alignment` can still produce a cluster mapping/confusion table but
  not DER.
- Diarization labels are compared as **clusters** via an explicit maximum-overlap one-to-one
  mapping that is printed for inspection; literal label strings are never compared.
- `src/evaluation/report.py` writes JSON, Markdown, and one self-contained HTML file (inline CSS,
  no network/assets) with word-level diff highlighting.

## Conventions

- Python 3.11, standard library first. New third-party imports belong in `requirements.txt`
  (base) or `requirements-asr.txt` (local ASR only); pin versions and note the verified date.
- `.env` is gitignored; `.env.example` is the committed template. Keys are read from the
  environment only — never from a CLI flag, a file argument, or a manifest. CLI entry points call
  `load_environment()` at start, not at import, and `tests/conftest.py` neutralizes that loader so
  the suite can never pick up a developer's real key.
- `audio/`, `outputs/`, `.venv/`, model caches, and `*.pt`/`*.bin`/etc. are gitignored and
  regenerable. `data/` is committed.
- Files generated by `scripts/build_controlled_fixture.py` say so; edit the script, not the JSON or
  the Markdown it produces (`data/meeting-metadata.md`, `data/meeting-transcript.txt`, and
  `data/controlled-meeting/*`).
- Error messages in this project are intentionally long and student-facing (setup steps, why a
  fallback exists, what a limit means). Keep them that way instead of collapsing them to a bare
  exception.
- Some messages reference `docs/whisperx_local_guide.md`; that file is not currently in the tree.
