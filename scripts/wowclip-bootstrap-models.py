#!/usr/bin/env python3
"""Prepare WowClip model directories without silently downloading anything."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


MODEL_MANIFEST = {
    "opencv-yunet": {
        "path": "opencv/face_detection_yunet.onnx",
        "purpose": "face detection",
        "source": "OpenCV Zoo YuNet ONNX",
    },
    "opencv-sface": {
        "path": "opencv/face_recognition_sface.onnx",
        "purpose": "same-person face embeddings",
        "source": "OpenCV Zoo SFace ONNX",
        "optional": True,
    },
    "silero-vad": {
        "path": "silero/silero_vad.onnx",
        "purpose": "voice activity detection",
        "source": "Silero VAD ONNX",
    },
    "whisper": {
        "path": "whisper/",
        "purpose": "local ASR model directory",
        "source": "faster-whisper or whisper.cpp local models",
    },
    "propainter-repo": {
        "path": "propainter/ProPainter/",
        "purpose": "official ProPainter repository checkout for hard subtitle and watermark removal",
        "source": "https://github.com/sczhou/ProPainter",
        "optional": True,
    },
    "propainter-weights": {
        "path": "propainter/weights/",
        "purpose": "ProPainter.pth, recurrent_flow_completion.pth, and raft-things.pth",
        "source": "ProPainter v0.1.0 pretrained weights",
        "optional": True,
    },
}


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def main() -> int:
    payload = read_input()
    models_dir = Path(payload.get("modelsDir") or "assets/models").expanduser().resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    for item in MODEL_MANIFEST.values():
        target = models_dir / item["path"]
        if item["path"].endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    missing = []
    for name, item in MODEL_MANIFEST.items():
        target = models_dir / item["path"]
        record = {
            "name": name,
            "path": str(target),
            "purpose": item["purpose"],
            "source": item["source"],
            "optional": bool(item.get("optional", False)),
        }
        if target.exists() and (target.is_dir() or target.stat().st_size > 0):
            existing.append(record)
        else:
            missing.append(record)

    print(json.dumps({
        "ok": True,
        "modelsDir": str(models_dir),
        "existing": existing,
        "missing": missing,
        "message": "Directories prepared. Download models explicitly; runtime scripts will not fetch models automatically.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
