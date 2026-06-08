#!/usr/bin/env python3
"""Detect faces in sampled frames with local OpenCV YuNet when available."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def main() -> int:
    payload = read_input()
    frames_dir = Path(payload.get("framesDir") or "").expanduser().resolve()
    output_path = Path(payload.get("outputPath") or (frames_dir.parent / "faces" / "detections.json")).expanduser().resolve()
    model_path = Path(payload.get("modelPath") or payload.get("yunetPath") or "assets/models/opencv/face_detection_yunet.onnx").expanduser().resolve()
    if not frames_dir.exists():
        print(json.dumps({"ok": False, "error": "framesDir does not exist"}, indent=2))
        return 1
    if not model_path.exists():
        print(json.dumps({
            "ok": False,
            "error": "YuNet model is missing",
            "modelPath": str(model_path),
            "hint": "Run wowclip-bootstrap-models.py and place face_detection_yunet.onnx at the reported path.",
        }, indent=2))
        return 1
    try:
        import cv2  # type: ignore
    except Exception:
        print(json.dumps({"ok": False, "error": "opencv-python is required", "install": "pip install opencv-python"}, indent=2))
        return 1

    image_paths = sorted([*frames_dir.glob("*.jpg"), *frames_dir.glob("*.jpeg"), *frames_dir.glob("*.png")])
    detections = []
    for image_path in image_paths:
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        height, width = image.shape[:2]
        detector = cv2.FaceDetectorYN.create(str(model_path), "", (width, height), score_threshold=float(payload.get("scoreThreshold", 0.75)))
        _, faces = detector.detect(image)
        normalized_faces = []
        if faces is not None:
            for face_index, face in enumerate(faces):
                values = [float(v) for v in face.tolist()]
                x, y, w, h = values[:4]
                landmark_values = values[4:14] if len(values) >= 15 else []
                score = float(values[14]) if len(values) >= 15 else (float(values[-1]) if len(values) > 4 else 0.0)
                landmarks = []
                for i in range(0, len(landmark_values), 2):
                    landmarks.append({
                        "x": max(0.0, min(1.0, landmark_values[i] / width)),
                        "y": max(0.0, min(1.0, landmark_values[i + 1] / height)),
                    })
                normalized_faces.append({
                    "id": f"{time_ms if 'time_ms' in locals() else 0}-{face_index}",
                    "box": {
                        "x": max(0.0, min(1.0, x / width)),
                        "y": max(0.0, min(1.0, y / height)),
                        "width": max(0.0, min(1.0, w / width)),
                        "height": max(0.0, min(1.0, h / height)),
                    },
                    "pixelBox": {"x": x, "y": y, "width": w, "height": h},
                    "landmarks": landmarks,
                    "rawYuNet": values,
                    "score": score,
                })
        time_ms = int(image_path.stem.split("-")[-1]) if image_path.stem.split("-")[-1].isdigit() else 0
        for face_index, face in enumerate(normalized_faces):
            face["id"] = f"{time_ms}-{face_index}"
        detections.append({
            "framePath": str(image_path),
            "timeMs": time_ms,
            "imageSize": {"width": width, "height": height},
            "faces": normalized_faces,
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"schema": "wowclip.face-detections.v1", "detections": detections}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "outputPath": str(output_path), "frameCount": len(image_paths), "detectionCount": sum(len(item["faces"]) for item in detections)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
