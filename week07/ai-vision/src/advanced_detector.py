import sys
import time
import cv2
import torch
from ultralytics import YOLO
from datetime import datetime
import os


class AdvancedDetector:
    def __init__(
            self,
            model_path='yolo11n.pt',
            confidence_threshold=0.3,
            save_detections=False,
            alert_threshold=1
    ):
        """
        Advanced detector with additional features

        Args:
            model_path: path to the model
            confidence_threshold: confidence threshold
            save_detections: whether to save detections to file
            alert_threshold: object count threshold for alerts
        """
        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold
        self.save_detections = save_detections
        self.alert_threshold = alert_threshold
        self._fps = 0.0
        self._fps_counter = 0
        self._fps_start = time.perf_counter()

        if torch.cuda.is_available():
            self.model.to('cuda')
            print("Model moved to GPU.")
        else:
            print("GPU not available, model will run on CPU.")

        # Print supported classes
        print("\nSupported YOLO classes:")
        print("=" * 60)
        class_names = self.model.names
        for class_id, class_name in class_names.items():
            print(f"  {class_id:2d}: {class_name}")
        print("=" * 60)
        print(f"Total classes: {len(class_names)}\n")

        # Create directory for saving results
        if save_detections:
            os.makedirs("detections", exist_ok=True)
            os.makedirs("saved_frames", exist_ok=True)

    def detect(self, frame, frame_count=0):
        """
        Advanced detection with result saving

        Args:
            frame: input frame
            frame_count: frame number (for logging)

        Returns:
            processed_frame, count, info
        """
        # YOLO accepts BGR directly; no need to convert
        results = self.model(frame, conf=self.confidence_threshold, verbose=False)[0]

        count = 0
        info = []
        processed_frame = frame.copy()

        if results.boxes is not None:
            for box in results.boxes:
                class_id = int(box.cls[0])
                name = results.names[class_id]
                confidence = float(box.conf[0])

                x1, y1, x2, y2 = map(int, box.xyxy[0])

                count += 1
                info.append({
                    'bbox': (x1, y1, x2, y2),
                    'confidence': confidence,
                    'timestamp': datetime.now()
                })

                # Draw bounding box with different colors depending on confidence
                color = self.get_color_by_confidence(confidence)
                cv2.rectangle(processed_frame, (x1, y1), (x2, y2), color, 3)

                # Compute label size dynamically so long class names aren't clipped
                label = f"{name} {confidence:.2f}"
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.6
                text_thickness = 2
                (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, text_thickness)
                pad = 5
                box_x2 = x1 + text_w + 2 * pad
                box_y1 = y1 - text_h - 2 * pad
                cv2.rectangle(processed_frame, (x1, box_y1), (box_x2, y1), color, -1)

                # Add text
                cv2.putText(processed_frame, label, (x1 + pad, y1 - pad),
                            font, font_scale, (255, 255, 255), text_thickness)

        # Update FPS
        self._fps_counter += 1
        now = time.perf_counter()
        elapsed = now - self._fps_start
        if elapsed >= 1.0:
            self._fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_start = now

        # Draw information overlay directly onto the frame
        self.draw_info_panel(processed_frame, count, frame_count)

        # Save frame on detection
        if self.save_detections and count > 0:
            self.save_detection_frame(processed_frame, count, frame_count)

        # Optional: send notification
        if count >= self.alert_threshold:
            self.send_alert(count)

        return processed_frame, count, info

    def get_color_by_confidence(self, confidence):
        """Returns color based on confidence"""
        if confidence > 0.8:
            return (0, 255, 0)  # Green for high confidence
        elif confidence > 0.5:
            return (0, 255, 255)  # Yellow for medium confidence
        else:
            return (0, 0, 255)  # Red for low confidence

    def draw_info_panel(self, frame, count, frame_count):
        """Draws an information overlay directly onto the frame (in-place)."""
        h, w = frame.shape[:2]

        # Semi-transparent black bar at the top
        panel_h = 60
        overlay = frame[:panel_h].copy()
        cv2.rectangle(overlay, (0, 0), (w, panel_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame[:panel_h], 0.4, 0, frame[:panel_h])

        cv2.putText(frame, f"Count: {count}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"FPS: {self._fps:.1f}", (260, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        time_text = f"Time: {datetime.now().strftime('%H:%M:%S')}"
        (text_w, _), _ = cv2.getTextSize(time_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.putText(frame, time_text, (w - text_w - 20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    def save_detection_frame(self, frame, count, frame_count):
        """Saves frame with detected birds"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"saved_frames/detect_{timestamp}_{count}.jpg"
        cv2.imwrite(filename, frame)
        print(f"Saved: {filename}")

    def send_alert(self, count):
        """Sends notification about large number of birds"""
        print(f"ALERT: Detected {count} objects at {datetime.now()}")
        # Here you can add email/telegram notification sending

    def run_webcam_detection(self, camera_index=0):
        """Start detection from webcam"""
        cap = cv2.VideoCapture(camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        if not cap.isOpened():
            print("Error: Cannot open camera")
            return

        print("Detection started. Press 'q' to quit, 's' to save frame.")

        cv2.namedWindow("AIDetector", cv2.WINDOW_AUTOSIZE)
        win_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        win_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        if sys.platform == 'win32':
            try:
                import ctypes
                user32 = ctypes.windll.user32
                screen_w = user32.GetSystemMetrics(0)
                screen_h = user32.GetSystemMetrics(1)
                x = max((screen_w - win_w) // 2, 0)
                y = max((screen_h - win_h) // 2, 0)
                cv2.moveWindow("AIDetector", x, y)
            except Exception:
                pass

        frame_count = 0

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    print("No camera")
                    break

                frame_count += 1

                processed_frame, count, info = self.detect(frame, frame_count)

                cv2.imshow("AIDetector", processed_frame)

                # Check if window was closed
                if cv2.getWindowProperty("AIDetector", cv2.WND_PROP_VISIBLE) < 1:
                    break

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('s'):
                    # Save current frame
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    cv2.imwrite(f"saved_frames/screenshot_{timestamp}.jpg", processed_frame)
                    print(f"Screenshot saved")

        finally:
            cap.release()
            cv2.destroyAllWindows()
            for _ in range(5):
                cv2.waitKey(1)
            print("Detection stopped")


# Additional function for using custom model
def train_custom_model():
    """
    Function for training custom model on bird dataset
    """
    from ultralytics import YOLO

    # Load pretrained model
    model = YOLO('yolov8n.pt')

    # Train on custom dataset
    model.train(
        data='birds_dataset.yaml',  # YAML file with dataset configuration
        epochs=100,
        imgsz=640,
        batch=16,
        name='detector'
    )
