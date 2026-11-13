"""Compare a live webcam face with a reference photo (1:1 verification).

This is verification, not identification: it asks "is this the same person as the
reference?" and prints a cosine score. Nothing leaves the laptop and nothing is
saved unless you keep the reference photo yourself.

Setup:
    python -m pip install -r requirements-face.txt
    python download_face_models.py

Run:
    python face_match.py --reference me.jpg
    python face_match.py                  # press SPACE to capture a reference

Press Q or Esc to quit. Press R to capture a new reference from the camera.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from src.face_verifier import (
    DEFAULT_DETECTION_THRESHOLD,
    DEFAULT_DETECTOR_MODEL,
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_RECOGNIZER_MODEL,
    FaceVerifier,
)

WINDOW = "Face match - YuNet + SFace"

MATCH_COLOR = (0, 200, 0)
NO_MATCH_COLOR = (0, 0, 255)
NEUTRAL_COLOR = (0, 200, 255)


def draw_face(frame: np.ndarray, detection, color: tuple[int, int, int], label: str) -> None:
    x, y, w, h = detection.box
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

    # YuNet also returns five landmarks: eyes, nose, mouth corners.
    points = detection.raw[4:14].astype(int).reshape(5, 2)
    for px, py in points:
        cv2.circle(frame, (int(px), int(py)), 2, color, -1)

    cv2.putText(
        frame,
        label,
        (x, max(y - 10, 18)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        color,
        2,
    )


def draw_panel(frame: np.ndarray, lines: list[str]) -> None:
    height = 34 * len(lines) + 10
    overlay = frame[:height].copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame[:height], 0.4, 0, frame[:height])
    for index, text in enumerate(lines):
        cv2.putText(
            frame,
            text,
            (14, 26 + index * 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
        )


def capture_reference(verifier: FaceVerifier, cap: cv2.VideoCapture, mirror: bool):
    """Show the live camera until SPACE captures the largest face."""
    print("No reference photo. Press SPACE to capture one, Q to quit.")
    while True:
        ok, frame = cap.read()
        if not ok:
            raise SystemExit("Camera stopped delivering frames.")
        if mirror:
            frame = cv2.flip(frame, 1)

        found = verifier.embed_largest(frame)
        if found is None:
            draw_panel(frame, ["No face detected - move closer and face the camera"])
        else:
            detection, _ = found
            draw_face(frame, detection, NEUTRAL_COLOR, f"face {detection.score:.2f}")
            draw_panel(frame, ["Press SPACE to capture this face as the reference", "R: reset   Q: quit"])

        cv2.imshow(WINDOW, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            return None
        if key == ord(" ") and found is not None:
            print("Reference captured from the camera.")
            return found[1]


def load_reference(verifier: FaceVerifier, path: str | Path) -> np.ndarray:
    image = cv2.imread(str(path))
    if image is None:
        raise SystemExit(f"Could not read reference image: {path}")
    found = verifier.embed_largest(image)
    if found is None:
        raise SystemExit(
            f"No face found in {path}.\n"
            "YuNet needs a clear, frontal face. Check that the photo really shows "
            "one face, or lower the detector confidence to accept a weaker "
            "candidate:\n"
            "    python face_match.py --reference <photo> --detection-threshold 0.5"
        )
    detection, embedding = found
    print(
        f"Reference face: detection score {detection.score:.2f}, "
        f"box {detection.box[2]}x{detection.box[3]} px.",
        flush=True,
    )
    return embedding


def run(verifier: FaceVerifier, cap: cv2.VideoCapture, reference: np.ndarray, threshold: float, mirror: bool) -> None:
    print(f"Verifying. Threshold={threshold:.3f}. Press Q to quit, R for a new reference.")
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Camera stopped delivering frames.")
            break
        if mirror:
            frame = cv2.flip(frame, 1)

        found = verifier.embed_largest(frame)
        if found is None:
            draw_panel(frame, ["No face detected", "Q: quit   R: new reference"])
        else:
            detection, embedding = found
            result = verifier.compare(reference, embedding, threshold)
            color = MATCH_COLOR if result.matched else NO_MATCH_COLOR
            verdict = "MATCH" if result.matched else "NO MATCH"
            draw_face(frame, detection, color, f"face {detection.score:.2f}")
            draw_panel(
                frame,
                [
                    f"SFace cosine: {result.similarity:.3f}   {verdict}",
                    f"threshold {threshold:.3f}   Q: quit   R: new reference",
                ],
            )

        cv2.imshow(WINDOW, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        if key == ord("r"):
            captured = capture_reference(verifier, cap, mirror)
            if captured is None:
                break
            reference = captured
            print(f"New reference captured. Threshold={threshold:.3f}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare a live webcam face with a reference photo (1:1)."
    )
    parser.add_argument(
        "--reference",
        help="Path to a reference photo. If omitted, press SPACE to capture one.",
    )
    parser.add_argument("--camera", type=int, default=0, help="Webcam index (default: 0).")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_MATCH_THRESHOLD,
        help=f"Cosine threshold; higher is stricter (default: {DEFAULT_MATCH_THRESHOLD}).",
    )
    parser.add_argument(
        "--detection-threshold",
        type=float,
        default=DEFAULT_DETECTION_THRESHOLD,
        help="YuNet confidence needed to call a box a face; lower accepts weaker "
        f"candidates (default: {DEFAULT_DETECTION_THRESHOLD}).",
    )
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="Mirror the live view (selfie style). Off by default so the comparison "
        "matches the unmirrored reference photo.",
    )
    parser.add_argument("--detector-model", default=str(DEFAULT_DETECTOR_MODEL))
    parser.add_argument("--recognizer-model", default=str(DEFAULT_RECOGNIZER_MODEL))
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        verifier = FaceVerifier(
            detector_model=args.detector_model,
            recognizer_model=args.recognizer_model,
            detection_threshold=args.detection_threshold,
        )
    except (FileNotFoundError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    # Validate the photo before touching the camera, so a bad reference and a
    # missing camera are not confused with each other.
    reference = load_reference(verifier, args.reference) if args.reference else None

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not cap.isOpened():
        print("Error: cannot open the camera.", file=sys.stderr)
        return 1

    try:
        if reference is None:
            reference = capture_reference(verifier, cap, args.mirror)
        if reference is None:
            return 0
        run(verifier, cap, reference, args.threshold, args.mirror)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
