import time
from pathlib import Path
import cv2

# Resolve model paths relative to the project root, not the current working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"


def add_rps_text(source_img, text):
    x1, y1 = 10, 10
    x2, y2 = 100, 34
    rectangle_color = (33, 22, 14)
    rectangle_thickness = -1

    font = cv2.FONT_HERSHEY_PLAIN
    font_scale = 1
    text_color = (255, 255, 255)
    text_thickness = 1

    cv2.rectangle(source_img, (x1, y1), (x2, y2), rectangle_color, rectangle_thickness)
    cv2.putText(source_img, "RPS: " + text, (x1 + 7, y1 + 17), font, font_scale, text_color, text_thickness)


def find_faces(model, find_img, source_img, k=1):
    rectangle_color = (0, 255, 0)
    rectangle_thickness = 2

    results = model.detectMultiScale(find_img, scaleFactor=1.1, minNeighbors=5)

    for (x, y, w, h) in results:
        x *= k
        y *= k
        w *= k
        h *= k
        cv2.rectangle(source_img, (x, y), (x + w, y + h), rectangle_color, rectangle_thickness)


def simple_detector():
    face_model = cv2.CascadeClassifier(str(MODELS_DIR / "face.xml"))
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Failed to open camera")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    rps_result = 0
    rps_counter = 0
    start_time = time.perf_counter()

    try:
        while True:
            success, frame = cap.read()

            if not success:
                print("Failed to get frame")
                break

            gray_img = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            scale = 0.5
            gray_img = cv2.resize(gray_img, (-1, -1), fx=scale, fy=scale)

            rps_counter += 1
            end_time = time.perf_counter()

            if end_time - start_time >= 1.0:
                start_time = end_time
                rps_result = rps_counter
                rps_counter = 0

            find_faces(face_model, gray_img, frame, int(1 / scale))
            add_rps_text(frame, str(rps_result))

            cv2.imshow("VideoCam", frame)

            if cv2.getWindowProperty("VideoCam", cv2.WND_PROP_VISIBLE) < 1:
                break

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
