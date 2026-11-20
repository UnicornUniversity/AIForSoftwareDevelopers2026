from src.advanced_detector import AdvancedDetector
from src.simple_detector import simple_detector

if __name__ == "__main__":
    #simple_detector()
    # Create detector with result saving
    detector = AdvancedDetector(
        #model_path='models/yolo11s.pt',
        # model_path='models/yolo11n.pt',
        #model_path='models/yolo11m.pt',
        #model_path='yolov8n.pt',
        model_path='models/hammer_v3_warm_best.pt',
        confidence_threshold=0.3,
        save_detections=False,
        alert_threshold=2
    )

    # Start detection
    detector.run_webcam_detection()
