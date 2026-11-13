"""Download the two OpenCV Zoo models used by face_match.py.

    YuNet  - face detection       (~230 KB)
    SFace  - face recognition     (~37 MB)

Files land in models/ and are ignored by git. Run this once:

    python download_face_models.py

Sources (OpenCV Zoo, official repository):
    https://github.com/opencv/opencv_zoo
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_ROOT / "models"

MODELS = [
    (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        100_000,
    ),
    (
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        20_000_000,
    ),
]


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "ai-vision-face-models/1.0"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if total:
                    percent = 100 * downloaded / total
                    sys.stdout.write(f"\r  {percent:5.1f}%  {downloaded / 1e6:6.1f} MB")
                    sys.stdout.flush()
    if total:
        sys.stdout.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download YuNet and SFace ONNX models.")
    parser.add_argument("--force", action="store_true", help="Re-download existing files.")
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for filename, url, minimum_size in MODELS:
        destination = MODELS_DIR / filename
        if destination.exists() and not args.force:
            print(f"Already present: {destination} ({destination.stat().st_size / 1e6:.1f} MB)")
            continue

        print(f"Downloading {filename} ...")
        try:
            download(url, destination)
        except Exception as error:  # noqa: BLE001 - report the URL and stop clearly
            destination.unlink(missing_ok=True)
            print(f"\nDownload failed for {url}\n{error}", file=sys.stderr)
            return 1

        size = destination.stat().st_size
        if size < minimum_size:
            destination.unlink(missing_ok=True)
            print(
                f"\n{filename} is only {size} bytes - that looks like an error page, "
                "not model weights. Check the URL or your network.",
                file=sys.stderr,
            )
            return 1
        print(f"Saved {destination} ({size / 1e6:.1f} MB)")

    print("\nFace models ready. Run: python face_match.py --reference <photo>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
