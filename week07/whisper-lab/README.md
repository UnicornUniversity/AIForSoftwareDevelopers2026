# Whisper Lab

Local speech-to-text for audio and video, built on
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2). Everything — the
model, the audio, the transcripts, and the optional summarisation step — stays on your machine.
No cloud API and no API keys.

Three entry points share one engine, so a lesson on model quality, cost, and latency can be
taught from a browser or a terminal:

| entry point | what it is |
| --- | --- |
| `server.py` | FastAPI web UI: drop a file, watch progress, read the transcript, download subtitles, turn it into notes |
| `transcribe.py` | CLI that writes `txt`, `srt`, `vtt`, `json`, or Markdown next to the input, plus a comparison page when a reference text exists |
| `benchmark.py` | Runs several model sizes on the same recording and reports load time, speed, and WER |

The second stage — transcript → notes — goes through a local
[Ollama](https://ollama.com) server, configured by environment variable. It is optional: without
it, transcription works exactly the same.

## How it works

```text
                    ┌── server.py (FastAPI, http://127.0.0.1:8000) ── public/ (static UI)
audio / video ──────┤
                    ├── transcribe.py (CLI)
                    └── benchmark.py

                              │
                              ▼
                whisper_lab/engine.py — faster-whisper
          tiny · base · small · medium · large-v3 · large-v3-turbo · distil-large-v3
                auto device: CUDA float16, else CPU int8
                              │
                    Transcription (segments, optional word timings,
                     detected language, duration, elapsed, RTF)
                    │                               │
      whisper_lab/formats.py               whisper_lab/llm.py
   txt · srt · vtt · json · markdown    Ollama (optional)
```

`engine.py` is the only module that imports faster-whisper. The web server turns a request into a
`Job`, runs it on a background thread, and lets the browser poll for segments as they are decoded.
Only one job transcribes at a time and only one model is kept loaded, because a typical laptop has
one GPU and a few gigabytes of VRAM; queued uploads wait instead of competing for memory.

## Quick start

Python 3.10 or newer (the bundled `.venv` uses 3.13). From this directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# optional: GPU on Windows with an NVIDIA card (~1.5 GB of wheels)
pip install -r requirements-cuda.txt

python server.py            # http://127.0.0.1:8000
```

On macOS or Linux activate with `source .venv/bin/activate`; the GPU wheel file is Windows-only
because macOS and Linux find the CUDA libraries without help.

Open <http://127.0.0.1:8000>, pick a bundled sample or drop your own file, choose a model, and press
**Transcribe**. The first run downloads the model into `models/` (gitignored): about 72 MB for
`tiny`, 461 MB for the default `small`.

Things worth knowing while the page is open:

- **Audio and video** are both accepted; faster-whisper decodes the audio track of `mp4`, `mkv`,
  and friends with PyAV. Uploads are capped at 200 MB.
- **Progress is live** — segments appear as Whisper produces them, and the progress bar follows
  the last segment's end time.
- **Downloads** are `TXT`, `SRT`, `VTT`, and `JSON`. Subtitles keep the segment timings; JSON
  carries the whole result — segments, word timings when that option was on, language, model,
  device, and speed. Markdown is available from the API and the CLI, not from the page.
- **Notes** (second tab) summarises the finished transcript with a local LLM. If Ollama is not
  running, the badge says *Ollama offline* and the button is disabled; transcription is
  unaffected. The Markdown that comes back is escaped before it is rendered, so a confused model
  cannot inject HTML into the page.
- **Jobs live in memory** for six hours and are pruned when the next job is created. Pruning and
  deleting remove uploaded files but never the bundled samples. Restarting the server clears the
  history.

## Command line

```powershell
python transcribe.py samples/demo1.wav
python transcribe.py talk.mp4 --model large-v3-turbo --format srt
python transcribe.py lecture.m4a --format all --output-dir out
python transcribe.py meeting.mp3 --summarize
python transcribe.py podcast.mp3 --language cs --task translate --words
python transcribe.py --list-models
```

`--format` repeats and accepts `all` (txt, srt, vtt, json, md). `--summarize` writes
`<name>.notes.md` next to the transcript and degrades to a "summary skipped" message when no
local LLM answers. `--initial-prompt` is the place for names, acronyms, and product terms that
Whisper keeps misspelling.

## Comparing with the original text

When a reference transcript exists, `transcribe.py` also writes `<name>.diff.html` — a static
page that shows the original and the transcript side by side, letter by letter. The reference is
looked up as `<name>.reference.txt` next to the audio or in `samples/`, so `samples/demo2.wav`
uses `samples/demo2.reference.txt`.

```powershell
python transcribe.py samples/demo2.wav --model small
# ...
# Wrote: samples\demo2.txt
# Comparison: samples\demo2.diff.html (WER 19.4%)
```

The page is self-contained — inline CSS, no scripts, no external assets — so it can be opened,
printed, or committed. Words are aligned with a minimum edit distance and the letters of each
aligned pair are compared case-insensitively: **green letters appear in both texts**, **red
letters differ**, and punctuation is shown but not compared. The header reports WER plus the
number of matched, substituted, missing, and extra words; the WER is the same number
`benchmark.py` reports, because both count a minimum edit distance over the same normalization.
The page also adapts to a dark browser theme.

The bundled `demo1.wav` pairs with the older `demo.reference1.txt` name, which the lookup accepts
as a fallback; rename it to `demo1.reference.txt` and nothing changes.

## Benchmarking model sizes

```powershell
python benchmark.py samples/demo1.wav --models tiny base small --reference samples/demo.reference1.txt
python benchmark.py samples/demo2.wav --models small --reference samples/demo.reference2.txt
python benchmark.py talk.mp3 --models small large-v3-turbo --device cuda
```

Each model is loaded, run over the whole file, and released. Without `--reference` you get load
time, processing time, speed, and RTF; with one you also get word error rate (punctuation and
case are stripped first, so WER measures what was heard). Raw rows go to `benchmark-results.json`
(gitignored) and a Markdown table is printed. Example from an NVIDIA GPU on the 28 s `demo1.wav`:

| Model | Device | Load (s) | Transcribe (s) | Speed | WER |
|---|---|---|---|---|---|
| tiny | cuda/float16 | 0.5 | 1.4 | 20x | 3.6% |
| base | cuda/float16 | 0.6 | 0.5 | 59x | 0.0% |
| small | cuda/float16 | 1.3 | 0.7 | 38x | 0.0% |

Treat the first row's transcription time as warm-up: it includes the one-off CUDA kernel and cuDNN
initialisation, which is why `tiny` looks slower than `base` here. Compare throughput from the
second model onwards, and expect the ordering to look more intuitive on CPU.

## Samples

| file | contents |
| --- | --- |
| `samples/demo1.wav` | 28 s English introduction to the lab (one synthetic voice, 22.05 kHz mono) |
| `samples/demo.reference1.txt` | correct transcript of `demo1.wav` |
| `samples/demo2.wav` | 90 s encyclopedic text about Prague, with Czech names and citations |
| `samples/demo2.reference.txt` | transcript of `demo2.wav` for WER scoring, mojibake — see the note below |
| `samples/demo2-cs.wav` | the same Prague passage in Czech, 70 s, a Czech neural voice |
| `samples/demo2-cs.reference.txt` | correct Czech transcript of `demo2-cs.wav` for WER scoring |
| `samples/make_sample.ps1` | regenerates a clip with the Windows built-in SAPI voice |
| `samples/make_sample_cs.py` | regenerates the Czech clip with edge-tts |

The two English clips were made by synthesising text with `System.Speech`, which is why they need
no copyright clearance. The script writes `demo.wav` and `demo.reference.txt` from whatever text it
currently contains (the Prague passage); the bundled files were generated the same way and
renamed. On macOS or Linux, record any short clip instead.

The Czech clip cannot use `System.Speech` unless a Czech SAPI voice is installed — the built-in
list here is English-only — so `make_sample_cs.py` asks Microsoft's edge-tts for
`cs-CZ-AntoninNeural` (or `--voice cs-CZ-VlastaNeural`) and converts the MP3 to a 24 kHz mono WAV
with the PyAV the lab already depends on. It needs a network connection and `edge-tts`, installed
for generating samples only and deliberately left out of `requirements.txt`. With the default
`small` model Whisper labels the clip `cs (98%)` and scores 17% WER against its reference.

## API

`server.py` serves the UI at `/` and JSON under `/api`. Interactive docs are at
<http://127.0.0.1:8000/api/docs>.

| method and path | purpose |
| --- | --- |
| `GET /api/status` | device, compute type, CUDA device count, model catalog, languages, samples, upload limit |
| `GET /api/llm` | whether Ollama answers and has a model; checked separately so an offline Ollama cannot delay page load |
| `POST /api/jobs` | multipart upload (`file`, `model`, `language`, `task`, `vad`, `words`) → job snapshot |
| `POST /api/jobs/sample` | same, for a bundled sample (`{"name": "demo1.wav", ...}`) |
| `GET /api/jobs/{id}` | job snapshot: status, progress, segments, text, summary, error |
| `DELETE /api/jobs/{id}` | forget a finished job and delete its upload |
| `POST /api/jobs/{id}/summarize` | `{"focus": "optional extra instruction"}` → Markdown notes; `503` when no LLM answers |
| `GET /api/jobs/{id}/download/{fmt}` | `txt`, `srt`, `vtt`, `json`, `md` as an attachment |

A job moves through `queued → loading → running → done | error`. Bad model names, languages, or
file extensions fail with `400`; a file over the limit with `413`; deleting or downloading from a
job that is still running with `409`.

## Layout

| path | purpose |
| --- | --- |
| `server.py` | FastAPI app, job endpoints, static UI mount |
| `transcribe.py` | CLI |
| `benchmark.py` | model-size comparison and WER |
| `config.py` | every tunable: model catalog, languages, paths, limits, LLM endpoint |
| `whisper_lab/engine.py` | `Transcriber`, `Transcription`, device/compute-type resolution |
| `whisper_lab/formats.py` | SRT/VTT/JSON/Markdown renderers |
| `whisper_lab/diff.py` | word alignment, letter-level comparison, and the `.diff.html` page |
| `whisper_lab/jobs.py` | in-memory job store and worker |
| `whisper_lab/llm.py` | transcript → notes through Ollama's native HTTP API |
| `whisper_lab/gpu.py` | makes pip-installed NVIDIA DLLs visible to CTranslate2 on Windows |
| `public/` | the single-page front end (no build step) |
| `samples/` | bundled clips and reference transcripts |
| `tests/` | 32 unit tests for formats, the job store, and the comparison |
| `models/`, `jobs/` | downloaded weights and uploaded audio (both gitignored) |

## Configuration

All settings are in `config.py`; the same values are used by the UI, the CLI, and the benchmark.
Command-line flags override them for a single run.

| setting | default | effect |
| --- | --- | --- |
| `DEFAULT_MODEL` | `small` | model loaded when none is named |
| `DEFAULT_DEVICE` | `auto` | CUDA when visible, else CPU |
| `DEFAULT_COMPUTE_TYPE` | `auto` | `float16` on GPU, `int8` on CPU |
| `BEAM_SIZE` | `5` | decoding beams |
| `VAD_FILTER`, `VAD_MIN_SILENCE_MS` | on, `500` | skip silence before decoding |
| `INITIAL_PROMPT` | empty | vocabulary hint for names and acronyms |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | where the UI listens (`--host`, `--port` override) |
| `MAX_UPLOAD_MB` | `200` | upload cap |
| `JOB_TTL_S` | `21600` | how long finished jobs are kept |
| `AUDIO_EXTENSIONS` | audio + video | accepted upload extensions |

The local LLM is Ollama, configured by environment variable:

| variable | default |
| --- | --- |
| `WHISPER_LAB_LLM_BASE_URL` | `http://localhost:11434` (Ollama's native API, no `/v1`) |
| `WHISPER_LAB_LLM_MODEL` | empty — the first installed completion model is used |

Start the server with `ollama serve` and install a model with `ollama pull qwen2.5:3b` (any
completion-capable model works; small ones answer faster). The notes request asks Ollama for a
16,384-token context so a long transcript is not silently cut, and disables "thinking" so the
whole output budget goes to the answer. Long transcripts are still truncated to 24,000 characters
for the summary, and the notes say when that happened. No key is involved, and nothing leaves the
machine.

## Tests

```powershell
python -m unittest discover -v        # 32 tests, milliseconds
```

The suite covers the output formats (SRT/VTT timestamps, JSON round trip, Markdown), the job
store (lifecycle, progress clamping, expiry, and that pruning deletes uploads but not samples),
and the comparison (word alignment, per-letter colouring, HTML escaping, reference lookup). It
needs no model, no network, and no Ollama. The engine itself is exercised by actually
transcribing a bundled sample — `python transcribe.py samples/demo1.wav` — because a fake
WhisperModel would only test the fake.

## Notes and limitations

- **Windows GPU.** CTranslate2 loads `cublas64_12.dll` lazily at the first encode, not when the
  model is constructed, so without `requirements-cuda.txt` a model can load and then fail
  mid-transcription with *Library cublas64_12.dll is not found*. `whisper_lab/gpu.py` registers the
  pip-installed NVIDIA directories with the DLL loader before the first import. If CUDA cannot be
  initialised while the model is loading, the engine retries on CPU/int8 with a warning; a failure
  that only shows up during decoding is reported as a job error like any other.
- **PyAV is pinned.** `av==16.0.1` because faster-whisper 1.2.x passes a `metadata_errors`
  argument that PyAV 19 removed, which breaks every decode.
- **CPU is usable, not fast.** `small` is the sensible default; `large-v3` runs on CPU but is
  many times slower than realtime. The speed column in `--list-models` is relative to `large-v3`
  on the same machine.
- **One at a time.** A single worker and a single cached model keep memory bounded; a second
  upload waits. Switching models evicts the previous one before loading the next.
- **No diarisation.** Whisper does not say who spoke; overlapping speakers are transcribed as
  one stream.
- **WER expectations.** `samples/demo2.reference.txt` was written with a UTF-8/Windows-1252
  mix-up, so its Czech names (for example *Vyšehrad*) are stored as mojibake and count as errors
  even when the model spells them correctly — repairing the file moves `small` from 19.4% to 18.0%
  on `demo2.wav`. Citations like `[20]` and `10m` count as words too. On `demo1.wav`, where the
  reference is clean, `small` scores 0% and `tiny` 3.6%.
- **The benchmark measures this machine.** Load time varies with the page cache (the weights are
  already on disk after the first run) and with the GPU driver, so compare models within one run,
  not across sessions.
