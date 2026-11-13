import numpy as np
import librosa
import librosa.feature
import sounddevice as sd
import onnxruntime as ort

# CONFIG
SAMPLE_RATE = 22050
DURATION = 3
THRESHOLD = 0.68          # cosine similarity threshold for a positive detection
MARGIN = 0.05             # winner must beat runner-up by at least this much
SILENCE_RMS = 0.005       # below this RMS the input is treated as silence
N_MFCC = 20

# Human speech detection (Silero VAD, ONNX)
VAD_MODEL = "models/silero_vad.onnx"
VAD_SAMPLE_RATE = 16000
VAD_CHUNK = 512           # samples per VAD frame (32 ms at 16 kHz)
VAD_CONTEXT = 64          # context samples the model expects before each chunk
VAD_PROB_THRESHOLD = 0.5  # per-frame probability above which a frame counts as speech
VAD_MIN_SPEECH_RATIO = 0.20  # fraction of frames that must be speech to report a voice

SAMPLES = {
    "Cat (meow)": "samples/cat-meow.wav",
    "Dog (barking)": "samples/dog-tripple-bark.wav",
}


# ---------- feature extraction ----------
def audioToFeature(y):
    """Convert a 1-D audio signal into a fixed-length, time-invariant descriptor.

    We summarize each MFCC coefficient by its mean and standard deviation across
    time, drop coefficient 0 (overall loudness), and L2-normalize. This makes the
    vector independent of clip length, recording volume, and start offset."""
    mfcc = librosa.feature.mfcc(y=y, sr=SAMPLE_RATE, n_mfcc=N_MFCC)
    mfcc = mfcc[1:]  # drop energy coefficient
    feat = np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1)])
    norm = np.linalg.norm(feat)
    if norm < 1e-8:
        return feat
    return feat / norm


def loadFeature(file_path):
    y, _ = librosa.load(file_path, sr=SAMPLE_RATE, dtype=np.float32)
    return audioToFeature(y)


# ---------- human voice detection ----------
def loadVadSession():
    """Load the Silero VAD ONNX model used to detect human speech."""
    return ort.InferenceSession(VAD_MODEL, providers=["CPUExecutionProvider"])


def voiceRatio(audio, session):
    """Return the fraction of 32 ms frames the VAD labels as human speech.

    Silero operates on 16 kHz mono audio and processes 512-sample chunks. Each
    chunk must be preceded by the previous 64 samples (the model's context), and
    a recurrent state must be carried across chunks."""
    y = librosa.resample(audio.astype(np.float32), orig_sr=SAMPLE_RATE, target_sr=VAD_SAMPLE_RATE)
    state = np.zeros((2, 1, 128), dtype=np.float32)
    context = np.zeros((1, VAD_CONTEXT), dtype=np.float32)
    sr = np.array(VAD_SAMPLE_RATE, dtype=np.int64)
    speech_frames = 0
    total_frames = 0
    for start in range(0, len(y) - VAD_CHUNK + 1, VAD_CHUNK):
        chunk = y[None, start:start + VAD_CHUNK].astype(np.float32)
        probs, state = session.run(
            None,
            {"input": np.concatenate([context, chunk], axis=1), "state": state, "sr": sr},
        )
        context = chunk[:, -VAD_CONTEXT:]
        speech_frames += int(float(probs[0, 0]) >= VAD_PROB_THRESHOLD)
        total_frames += 1
    return speech_frames / total_frames if total_frames else 0.0


def recordAudio(duration):
    print("Recording sound...")
    audio = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype=np.float32)
    sd.wait()
    return np.squeeze(audio)


def cosineSimilarity(a, b):
    return float(np.dot(a, b))  # already L2-normalized


def classify(recorded_audio, sample_features):
    feat = audioToFeature(recorded_audio)
    scores = {label: cosineSimilarity(feat, ref) for label, ref in sample_features.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_label, best_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else -1.0
    return best_label, best_score, runner_up_score, scores


# ---------- main ----------
print("Starting audio monitoring (cat / dog / human / none)")
sample_features = {label: loadFeature(path) for label, path in SAMPLES.items()}
vad_session = loadVadSession()

while True:
    recorded_audio = recordAudio(DURATION)

    rms = float(np.sqrt(np.mean(recorded_audio ** 2)))
    if rms < SILENCE_RMS:
        print(f"Detected: none (silence, rms={rms:.4f})")
        continue

    speech_ratio = voiceRatio(recorded_audio, vad_session)
    if speech_ratio >= VAD_MIN_SPEECH_RATIO:
        print(f"Detected: Human (voice) (speech={speech_ratio:.2f}, rms={rms:.4f})")
        continue

    best_label, best_score, runner_up, scores = classify(recorded_audio, sample_features)
    score_str = ", ".join(f"{label}: {score:.3f}" for label, score in scores.items())
    print(f"Similarity -> {score_str} | rms={rms:.4f}")

    if best_score >= THRESHOLD and (best_score - runner_up) >= MARGIN:
        print(f"Detected: {best_label} (score={best_score:.3f}, margin={best_score - runner_up:.3f})")
    else:
        print(
            f"Detected: none (best {best_label} at {best_score:.3f}, "
            f"runner-up {runner_up:.3f}, threshold {THRESHOLD}, margin {MARGIN})"
        )
