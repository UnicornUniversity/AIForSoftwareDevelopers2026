# AI Sound Detector

A real-time microphone monitor that labels each 3-second audio window as one of
**cat (meow)**, **dog (barking)**, **human (voice)**, or **none**. It runs entirely
locally — classical MFCC similarity for the animal sounds plus a Silero voice-activity
model for speech — with no cloud calls and no API keys.

## How it works

```text
microphone ──► 3 s window ──► silence gate (RMS)
                                   │
                                   ▼
                          Silero VAD (ONNX) ──► speech ratio ≥ 0.20 ──► Human
                                   │ no
                                   ▼
                  MFCC mean+std descriptor ──► cosine similarity vs. cat/dog references
                                   │
                                   ▼
                  best ≥ 0.68 and margin ≥ 0.05 ──► Cat / Dog
                                   │ otherwise
                                   ▼
                                  none
```

1. **Capture.** `sounddevice` records 3 s of mono float32 audio at 22,050 Hz, in a
   continuous loop.
2. **Silence gate.** A window with RMS below `0.005` is reported as `none` without
   touching the models.
3. **Human voice.** [Silero VAD](https://github.com/snakers4/silero-vad) (`models/silero_vad.onnx`)
   is run on the window resampled to 16 kHz, in 512-sample frames (32 ms) each preceded
   by the 64 samples of context the model expects, carrying its recurrent state across
   frames. If at least 20 % of frames are speech, the result is `Human (voice)`.
4. **Animal sounds.** The window is described by 20 MFCCs, dropping coefficient 0
   (overall loudness), summarized by mean and standard deviation over time and
   L2-normalized — a 38-dimensional descriptor that is insensitive to clip length,
   recording volume, and start offset. It is compared by cosine similarity against the
   reference clips; a label is emitted only if the best score clears `0.68` **and**
   beats the runner-up by `0.05`, so a sound that is merely "close" is reported as
   `none` rather than guessed.

Checking voice first matters: human speech is spectrally close enough to these animal
references that it would otherwise cross the similarity threshold.

## Repository layout

| Path | Purpose |
| --- | --- |
| `sound_detector.py` | The whole application: capture, VAD, features, classification loop |
| `models/silero_vad.onnx` | Silero VAD model (~2.3 MB, CPU inference via ONNX Runtime) |
| `samples/cat-meow.wav` | Reference clip for **Cat (meow)** (1.54 s, 44.1 kHz) |
| `samples/dog-tripple-bark.wav` | Reference clip for **Dog (barking)** (1.80 s, 44.1 kHz) |
| `samples/test.wav` | Scratch clip (3.00 s), **not** used as a reference |
| `requirements.txt` | Python dependencies |

`sound_detector.py` loads its model and samples by relative path, so it must be run
from this directory. It has no `__main__` guard — the monitoring loop starts at import
time.

## Requirements

- Python 3.10 or newer (the bundled `.venv` uses 3.13)
- A working microphone and PortAudio
- Packages: `numpy`, `librosa`, `sounddevice`, `onnxruntime` (pydub, scipy, matplotlib
  and pygame are listed in `requirements.txt` but are not imported by the current script)

## Setup and run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python sound_detector.py
```

On Linux/macOS activate with `source .venv/bin/activate`; on Debian/Ubuntu install
PortAudio first with `sudo apt install libportaudio2`.

The monitor prints one line per window and runs until interrupted with `Ctrl+C`.
Example output (values vary with microphone and room):

```text
Starting audio monitoring (cat / dog / human / none)
Recording sound...
Detected: Human (voice) (speech=0.83, rms=0.0412)
Recording sound...
Similarity -> Cat (meow): 0.912, Dog (barking): 0.684 | rms=0.1930
Detected: Cat (meow) (score=0.912, margin=0.228)
Recording sound...
Detected: none (silence, rms=0.0011)
```

## Configuration

All constants sit at the top of `sound_detector.py`:

| Constant | Default | Meaning |
| --- | --- | --- |
| `SAMPLE_RATE` | `22050` | Capture rate for features |
| `DURATION` | `3` | Window length in seconds |
| `THRESHOLD` | `0.68` | Minimum cosine similarity for a detection |
| `MARGIN` | `0.05` | Required lead of the best label over the runner-up |
| `SILENCE_RMS` | `0.005` | Below this RMS the window is silence |
| `N_MFCC` | `20` | MFCC coefficients (coefficient 0 is dropped) |
| `VAD_PROB_THRESHOLD` | `0.5` | Per-frame speech probability |
| `VAD_MIN_SPEECH_RATIO` | `0.20` | Fraction of speech frames that reports a voice |
| `SAMPLES` | cat, dog | Label → reference clip map |

## Notes and limitations

- **Closed set.** Only cat and dog are modeled; every other sound is either speech
  (VAD) or `none` (threshold/margin). Add a class by dropping a clean clip into
  `samples/` and adding an entry to `SAMPLES`.
- **One reference clip per class.** The descriptor averages MFCC statistics over the
  window, which works well for short, clean bursts but is not a trained classifier;
  overlapping sounds or a noisy room will usually fall to `none`.
- **Fixed window.** A sound shorter than the 3 s window is diluted by the surrounding
  silence; a continuous sound straddling two windows is judged twice.
- **No automated tests.** The bundled clips are useful for a quick sanity check: the
  cat clip scores `1.000` against itself and `0.718` against the dog reference (and
  vice versa), comfortably above the threshold but with the expected margin.
