from pathlib import Path
import time
import cv2
import numpy as np
import torch
import torch.nn.functional as F


def ensure_dir(path: str | Path) -> Path:
    """Create directory if it doesn't exist. Returns Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def bgr_to_gray_blur_gpu(frame_bgr: np.ndarray, device: torch.device, ksize: int = 21) -> torch.Tensor:
    """BGR -> GRAY -> Gaussian blur on GPU. Returns [1, 1, H, W] float32."""
    g_ndarr = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = torch.from_numpy(g_ndarr).to(device=device, dtype=torch.float32).unsqueeze(0).unsqueeze(0)

    # sigma as in OpenCV when sigma = 0
    sigma = 0.3 * ((ksize - 1) * 0.5 - 1) + 0.8
    x = torch.arange(ksize, device=device, dtype=torch.float32) - (ksize - 1) / 2
    k = torch.exp(-(x ** 2) / (2 * sigma * sigma))
    k /= k.sum()
    k_col, k_row = k.view(1, 1, ksize, 1), k.view(1, 1, 1, ksize)

    pad = ksize // 2
    gray = F.conv2d(F.pad(gray, (0, 0, pad, pad), mode="reflect"), k_col)
    gray = F.conv2d(F.pad(gray, (pad, pad, 0, 0), mode="reflect"), k_row)

    return gray


def detect_motion(
        video_source: str | int,
        save_dir: str | Path = "motion_frames",
        min_motion_percent: float = 1.0,
        thr: float = 25.0,
        blur_ksize: int = 21,
        sleep_between: float = 0.0,
        show_window: bool = True,
) -> None:
    """Motion detection on GPU (PyTorch CUDA). Saves frame on trigger and outputs time in seconds when motion is detected."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available in PyTorch - check driver/Nvidia installation")

    device = torch.device("cuda")
    out_dir = ensure_dir(save_dir)

    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open source: {video_source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_id = 0
    prev_gray = None

    if show_window:
        cv2.namedWindow("MotionDetector", cv2.WINDOW_AUTOSIZE)

    print("Analysis (GPU/CUDA). Press 'q' to quit.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            gray = bgr_to_gray_blur_gpu(frame, device, ksize=blur_ksize)

            if prev_gray is None:
                prev_gray = gray
                frame_id += 1
                if sleep_between:
                    time.sleep(sleep_between)
                continue

            diff = torch.abs(prev_gray - gray)
            mask = (diff > thr)
            motion_percent = (mask.sum(dtype=torch.float32) / mask.numel()) * 100.0

            display_frame = frame
            if float(motion_percent) > min_motion_percent:
                ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                ts_sec = (ts_ms / 1000.0) if ts_ms else (frame_id / fps if fps > 0 else 0.0)

                shot_path = out_dir / f"motion_{frame_id}.jpg"
                cv2.imwrite(str(shot_path), frame)
                print(f"[!] Motion! {float(motion_percent):.2f}% @{ts_sec:.2f}s -> screenshot: {shot_path}")

                display_frame = frame.copy()
                cv2.putText(display_frame, f"MOTION {float(motion_percent):.2f}%",
                            (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

            if show_window:
                cv2.imshow("MotionDetector", display_frame)
                if cv2.getWindowProperty("MotionDetector", cv2.WND_PROP_VISIBLE) < 1:
                    break
                if (cv2.waitKey(1) & 0xFF) == ord('q'):
                    break

            prev_gray = gray
            frame_id += 1

            if sleep_between:
                time.sleep(sleep_between)

    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        cap.release()
        if show_window:
            cv2.destroyAllWindows()


def main():
    detect_motion(
        video_source=0,
        save_dir="motion_frames",
        min_motion_percent=1.0,
        thr=25.0,
        blur_ksize=21,
        sleep_between=0.2,
    )


if __name__ == "__main__":
    main()
