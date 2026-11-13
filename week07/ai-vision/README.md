# AI Vision

Four small computer-vision demos that run entirely on your own machine — no cloud
calls, no API keys, no uploads. Three of them drive a webcam; one compares a live face
with a reference photo.

| entry point | what it does |
| --- | --- |
| `main.py` | Real-time object detection with YOLO11 (ultralytics), with count/FPS overlay |
| `src/move_detector.py` | Frame-difference motion detector on the GPU (PyTorch CUDA), saves triggering frames |
| `face_match.py` | 1:1 face verification with OpenCV's YuNet detector and SFace recognizer |
| `download_face_models.py` | Fetches the two ONNX face models into `models/` |

`src/simple_detector.py` is a fourth, older Haar-cascade demo. It is currently commented
out of `main.py` and needs a `models/face.xml` cascade that is not in the repository, so
it is documented but not runnable as-is.

## How it works

```text
webcam ─► cv2.VideoCapture ─► AdvancedDetector.detect ─► YOLO11 (ultralytics)
                                                          CUDA when available, else CPU
                                        │
                                        ▼
                            boxes + confidence ─► overlay: count, FPS, clock
                                        │
                                        ├─► save frame (optional)
                                        └─► alert when count ≥ threshold (optional)

webcam/video ─► BGR→gray ─► Gaussian blur on GPU ─► |Δ vs previous frame|
                                                          │
                                              >1% pixels change ─► save frame + print time

photo/webcam ─► YuNet (face boxes) ─► SFace align + 128-d embedding
                                        │
                                        ▼
                              cosine vs reference embedding ─► MATCH / NO MATCH
```

- **YOLO detector.** `AdvancedDetector` wraps `ultralytics.YOLO`, moves the model to CUDA
  when `torch.cuda.is_available()`, and runs on every frame. Each box is coloured by
  confidence (green > 0.8, yellow > 0.5, red otherwise) and labelled with
  `class confidence`. A semi-transparent bar shows the object count, a smoothed FPS
  (recomputed once per second), and the local time. The pretrained models recognise the
  80 COCO classes; the full list is captured in [`YOLO classes.md`](YOLO%20classes.md).
- **Motion detector.** Frames are converted to grayscale, then blurred with a separable
  Gaussian kernel implemented in `torch.nn.functional.conv2d` — the same kernel OpenCV
  would use for `ksize=21, sigma=0`. The absolute difference against the previous frame
  is thresholded (`thr=25`); if more than `min_motion_percent` of pixels (default 1 %)
  change, the frame is written to `motion_frames/` and its timestamp is printed.
- **Face verification.** YuNet finds faces; frames larger than 1280 px are downscaled
  first because YuNet under-scores faces that fill a full-resolution photo. SFace aligns
  the face using YuNet's five landmarks and produces a 128-number embedding; the cosine
  similarity between two embeddings is compared with a threshold (default `0.363`, the
  value published for SFace on LFW). This is **verification**, not identification — it
  only answers "is this the same person as the reference?", and it names nobody.

## Repository layout

| path | purpose |
| --- | --- |
| `main.py` | Entry point for the YOLO detector; also holds the model/threshold choices |
| `src/advanced_detector.py` | `AdvancedDetector`: detection loop, overlay, optional saving/alerting |
| `src/move_detector.py` | GPU motion detector (`python -m src.move_detector`) |
| `src/face_verifier.py` | `FaceVerifier`: YuNet detection, SFace embeddings, cosine comparison |
| `src/simple_detector.py` | Haar-cascade face demo (needs a missing `models/face.xml`) |
| `face_match.py` | Interactive 1:1 face-verification demo |
| `download_face_models.py` | Downloads YuNet and SFace from OpenCV Zoo into `models/` |
| `models/yolo11n.pt` | YOLO11 nano weights (~5.6 MB), the fast option |
| `models/yolo11m.pt` | YOLO11 medium weights (~40.7 MB), the default in `main.py` |
| `models/face_detection_yunet_2023mar.onnx` | YuNet face detector (~0.2 MB, gitignored, downloaded) |
| `models/face_recognition_sface_2021dec.onnx` | SFace recognizer (~38.7 MB, gitignored, downloaded) |
| `photos/i-am.JPG`, `photos/another-person.png` | Reference photos for the face demo |
| `requirements.txt` | Full stack: OpenCV contrib, NumPy, PyTorch, torchvision, ultralytics |
| `requirements-face.txt` | Torch-free subset for `face_match.py` only |
| `train.ipynb` | One-cell scratch notebook (`!nvidia-smi`) used while checking the GPU |
| `YOLO classes.md` | Captured console output listing the 80 COCO class ids and names |

## Requirements

- Python 3.10 or newer (developed on 3.13)
- A webcam (all three camera demos), and for `face_match.py` a clear, frontal reference
  photo
- An NVIDIA GPU with a CUDA-enabled PyTorch for `src/move_detector.py` — it refuses to
  run on CPU by design

The YOLO and face demos run on CPU, just more slowly. `requirements.txt` pins
`torch~=2.9.1` and `torchvision~=0.24.1`; a plain `pip install` from PyPI gives you the
CPU build.

## Setup

From this directory (`week07/ai-vision`):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Linux/macOS activate with `source .venv/bin/activate`.

For a GPU build of PyTorch, install from the official index matching your driver rather
than PyPI (example for CUDA 12.8 / RTX 50xx):

```powershell
python -m pip install -r requirements.txt `
    --index-url https://download.pytorch.org/whl/cu128 `
    --extra-index-url https://pypi.org/simple
```

With `uv`, put the PyTorch index first:

```powershell
uv pip install -r requirements.txt --index https://download.pytorch.org/whl/cu128 --index https://pypi.org/simple
```

Only the face demo needs `requirements-face.txt`; it installs `opencv-contrib-python` and
NumPy without pulling in PyTorch or ultralytics. Never keep `opencv-python` and
`opencv-contrib-python` installed side by side — they provide the same `cv2` module and
the last one installed wins. Both requirement files use the contrib wheel, so installing
them in either order is safe.

The YOLO weights are already in `models/`. The face models are not checked in; fetch them
once:

```powershell
python download_face_models.py
```

The script verifies the downloaded size, so an error page saved as an `.onnx` is reported
instead of being silently used. Re-run with `--force` to refresh the files.

## Running

### YOLO object detection

```powershell
python main.py
```

`main.py` selects `models/yolo11m.pt`, confidence `0.3`, no frame saving, and an alert
threshold of 2. Edit the `AdvancedDetector(...)` call to switch to `yolo11n.pt` (faster,
less accurate) or turn on saving. The window is titled **AIDetector**; press `q` to quit
and `s` to save the current annotated frame.

### GPU motion detector

```powershell
python -m src.move_detector
```

Press `q` to quit. Triggering frames are written to `motion_frames/` as
`motion_<frame>.jpg`, and each trigger prints the video time in seconds. The defaults are
`min_motion_percent=1.0`, `thr=25.0`, `blur_ksize=21`, `sleep_between=0.2`.

To tune it, edit `main()` at the bottom of `src/move_detector.py`; the function
`detect_motion(video_source, ...)` also accepts a video file path instead of a camera
index.

### Face verification

```powershell
python face_match.py --reference photos/i-am.JPG
python face_match.py                      # press SPACE to capture a reference
python face_match.py --reference photos/i-am.JPG --threshold 0.40
```

While the preview is open:

| key | action |
| --- | --- |
| `SPACE` | capture the largest face as the reference (when capturing) |
| `R` | capture a new reference from the camera |
| `Q` / `Esc` | quit |

The overlay shows the YuNet detection score on the box and, on the top bar, the SFace
cosine similarity plus `MATCH` / `NO MATCH`. Nothing is written to disk.

| flag | default | meaning |
| --- | --- | --- |
| `--reference PATH` | none | reference photo; without it a reference is captured from the webcam |
| `--camera N` | `0` | webcam index |
| `--threshold T` | `0.363` | cosine similarity needed for `MATCH`; higher is stricter |
| `--detection-threshold T` | `0.7` | YuNet confidence needed to accept a box as a face |
| `--mirror` | off | mirror the live view (selfie style); off so it matches the unmirrored photo |
| `--detector-model PATH` | YuNet in `models/` | alternative YuNet ONNX file |
| `--recognizer-model PATH` | SFace in `models/` | alternative SFace ONNX file |

## Configuration

`AdvancedDetector` constructor arguments (set in `main.py`):

| argument | default | meaning |
| --- | --- | --- |
| `model_path` | `yolo11n.pt` | ultralytics weights; `main.py` passes `models/yolo11m.pt` |
| `confidence_threshold` | `0.3` | minimum YOLO confidence for a box |
| `save_detections` | `False` | write annotated frames and create `detections/`, `saved_frames/` |
| `alert_threshold` | `1` | object count that triggers `send_alert`; `main.py` passes `2` |

`run_webcam_detection(camera_index=0)` opens the camera at 1280×720 and centres the
window on Windows.

## Notes and limitations

- **No automated tests.** All four entry points are interactive demos; the console
  output in `YOLO classes.md` was captured from a real run, but nothing asserts on it.
- **The motion detector is CUDA-only.** It raises `RuntimeError` when
  `torch.cuda.is_available()` is false rather than silently falling back to CPU. A PyPI
  `torch` wheel is CPU-only; use the CUDA index above. Check the build with
  `python -c "import torch; print(torch.__version__, torch.cuda.is_available())"`.
- **Saving frames from the YOLO demo.** `save_detections=False` means `saved_frames/` is
  never created, so the `s` screenshot key prints "Screenshot saved" while
  `cv2.imwrite` fails silently. Start the detector with `save_detections=True` if you
  want the key (or automatic saving) to work.
- **Alerts repeat every frame.** `alert_threshold` is checked on every processed frame,
  so once the object count stays at or above it, `ALERT: ...` prints continuously.
  `save_detection_frame` likewise writes a new file for every qualifying frame.
- **`src/simple_detector.py` needs a file that is not shipped.** It loads
  `models/face.xml` (an OpenCV Haar cascade) and is commented out in `main.py`. The
  80-class YOLO models are the working detectors.
- **`train_custom_model()` is a leftover.** The helper at the bottom of
  `src/advanced_detector.py` trains on a `birds_dataset.yaml` that does not exist; the
  docstrings still talk about birds. It is not called anywhere.
- **Face threshold needs calibration.** `0.363` is SFace's published LFW value, and the
  script is sensitive to lighting, camera, and reference quality. One reference clip per
  person keeps it honest; a face that is merely similar can still score near the
  threshold. The references in `photos/` are ordinary photos used for a manual demo.
- **Nothing leaves the machine.** Face verification keeps the reference in memory; only
  the motion detector and optional YOLO saving write images, and both write under this
  directory (gitignored).
- **OpenCV builds are not interchangeable.** The face module (`FaceDetectorYN`,
  `FaceRecognizerSF`) exists only in `opencv-contrib-python`. If `face_match.py` reports
  that this OpenCV build has no face module, the wrong wheel is installed.
