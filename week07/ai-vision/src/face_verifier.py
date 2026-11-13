"""1:1 face verification with OpenCV YuNet (detection) and SFace (recognition).

This module answers one question: "is the face in this frame the same person as
the face in the reference photo?" It does not build a gallery and does not try to
name anyone. YuNet finds face boxes; SFace turns an aligned face into a 128-number
embedding; cosine similarity between two embeddings is the comparison score.

Requires ``opencv-contrib-python``; the base ``opencv-python`` wheel does not ship
``FaceDetectorYN`` or ``FaceRecognizerSF``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

DEFAULT_DETECTOR_MODEL = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
DEFAULT_RECOGNIZER_MODEL = MODELS_DIR / "face_recognition_sface_2021dec.onnx"

# SFace's published cosine threshold (LFW). Higher = stricter. Calibrate it for
# your own camera and reference photo before trusting it.
DEFAULT_MATCH_THRESHOLD = 0.363

# YuNet's confidence that a box is a face. 0.7 is a sane default once the frame
# is a normal size; see DEFAULT_DETECT_MAX_DIM for why size matters.
DEFAULT_DETECTION_THRESHOLD = 0.7

# Frames are downscaled to this before detection. YuNet's priors are tuned for
# faces of ordinary size; on a full-resolution phone photo (3000+ px) the face
# can be a thousand pixels wide and the detector misses it or scores it low.
# Downscaling first took one such photo from "no face" to a 0.93 detection.
DEFAULT_DETECT_MAX_DIM = 1280


@dataclass(frozen=True)
class FaceDetection:
    """One face box returned by YuNet."""

    box: tuple[int, int, int, int]  # x, y, width, height
    score: float
    raw: np.ndarray  # the 15 values YuNet returns; SFace needs them for alignment

    @property
    def area(self) -> int:
        return self.box[2] * self.box[3]


@dataclass(frozen=True)
class MatchResult:
    similarity: float
    threshold: float

    @property
    def matched(self) -> bool:
        return self.similarity >= self.threshold


class FaceVerifier:
    """YuNet detector plus SFace recognizer, wrapped in a small API."""

    def __init__(
        self,
        detector_model: str | Path = DEFAULT_DETECTOR_MODEL,
        recognizer_model: str | Path = DEFAULT_RECOGNIZER_MODEL,
        detection_threshold: float = DEFAULT_DETECTION_THRESHOLD,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
        detect_max_dim: int = DEFAULT_DETECT_MAX_DIM,
    ) -> None:
        detector_path = Path(detector_model)
        recognizer_path = Path(recognizer_model)
        for path in (detector_path, recognizer_path):
            if not path.is_file():
                raise FileNotFoundError(
                    f"Face model not found: {path}\n"
                    "Run `python download_face_models.py` in week07/ai-vision."
                )

        if not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
            raise RuntimeError(
                "This OpenCV build has no face module. Install opencv-contrib-python "
                "(see requirements-face.txt); opencv-python alone is not enough."
            )

        self._detector = cv2.FaceDetectorYN.create(
            str(detector_path),
            "",
            (320, 320),
            detection_threshold,
            nms_threshold,
            top_k,
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        self.detection_threshold = detection_threshold
        self.detect_max_dim = detect_max_dim

    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        """Return every face YuNet finds in a BGR frame.

        Large frames are downscaled to ``detect_max_dim`` before detection and
        the results are mapped back, so boxes and landmarks are always in the
        coordinates of the frame you passed in. This is what makes ordinary
        phone photos work: YuNet is trained on faces of roughly normal size and
        under-scores a face that fills a 3000-pixel-wide image.
        """
        height, width = frame.shape[:2]
        if height == 0 or width == 0:
            return []

        scale = min(1.0, self.detect_max_dim / max(height, width))
        if scale < 1.0:
            work = cv2.resize(
                frame,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            work = frame

        self._detector.setInputSize((work.shape[1], work.shape[0]))
        _, faces = self._detector.detect(work)
        if faces is None:
            return []

        detections: list[FaceDetection] = []
        for face in faces:
            # YuNet returns x, y, w, h, ten landmark coordinates, then the score.
            raw = face.copy()
            if scale < 1.0:
                raw[:14] = raw[:14] / scale
            x, y, w, h = (max(0, int(value)) for value in raw[:4])
            detections.append(
                FaceDetection(
                    box=(x, y, w, h),
                    score=float(raw[14]),
                    raw=raw,
                )
            )
        return detections

    def largest(self, frame: np.ndarray) -> FaceDetection | None:
        """Return the largest detected face, or None."""
        faces = self.detect(frame)
        return max(faces, key=lambda face: face.area, default=None)

    def embed(self, frame: np.ndarray, detection: FaceDetection) -> np.ndarray:
        """Align the face and return a 128-number SFace embedding."""
        aligned = self._recognizer.alignCrop(frame, detection.raw.reshape(1, -1))
        return self._recognizer.feature(aligned).flatten()

    def embed_largest(self, frame: np.ndarray) -> tuple[FaceDetection, np.ndarray] | None:
        """Detect the largest face and embed it in one call."""
        detection = self.largest(frame)
        if detection is None:
            return None
        return detection, self.embed(frame, detection)

    def compare(
        self,
        reference: np.ndarray,
        candidate: np.ndarray,
        threshold: float = DEFAULT_MATCH_THRESHOLD,
    ) -> MatchResult:
        """Cosine similarity between two SFace embeddings."""
        similarity = float(
            self._recognizer.match(
                reference.reshape(1, -1),
                candidate.reshape(1, -1),
                cv2.FaceRecognizerSF_FR_COSINE,
            )
        )
        return MatchResult(similarity=similarity, threshold=threshold)
