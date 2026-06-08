# Local Models

WowClip must work without cloud services after models are available locally.

## Recommended Defaults

- Face detection: OpenCV YuNet ONNX.
- Face embedding: OpenCV SFace ONNX.
- VAD: Silero VAD ONNX.
- ASR: faster-whisper using local CTranslate2 Whisper models.
- Portable ASR fallback: whisper.cpp quantized models.
- Hard subtitle/watermark removal: official ProPainter repository and local weights.

## Model Directory

```text
assets/models/
├── opencv/
│   ├── face_detection_yunet.onnx
│   └── face_recognition_sface.onnx
├── silero/
│   └── silero_vad.onnx
├── whisper/
    ├── faster-whisper-large-v3-turbo/
    └── ggml-large-v3-turbo-q5_0.bin
└── propainter/
    ├── ProPainter/
    └── weights/
        ├── ProPainter.pth
        ├── recurrent_flow_completion.pth
        └── raft-things.pth
```

`scripts/wowclip-bootstrap-models.py` should download only explicitly requested models. Runtime scripts must not silently call the network.

## Runtime Policy

- If a model is missing, return a structured error with installation instructions.
- Never upload media or audio.
- Store model checksums in `models.lock.json` when a downloader is implemented.

## Face Model Files

Expected OpenCV model paths:

```text
assets/models/opencv/face_detection_yunet.onnx
assets/models/opencv/face_recognition_sface.onnx
```

`face_detection_yunet.onnx` is required for face detection. `face_recognition_sface.onnx` is optional but recommended; when absent, WowClip still tracks faces by geometry.

Do not write SFace embeddings into final timelines. Embeddings are biometric-like derived data and should remain ephemeral or project-cache-only.

## ProPainter Overlay Removal

Use `scripts/wowclip-remove-overlays.py` when sampled frames show hard-burned subtitles or watermarks. Run it before portrait crop planning so the repair area stays in the original landscape frame; after 9:16 crop, subtitle pixels are often enlarged or partially cut off, which makes inpainting less reliable.

Expected ProPainter files:

```text
assets/models/propainter/ProPainter/inference_propainter.py
assets/models/propainter/ProPainter/weights/ProPainter.pth
assets/models/propainter/ProPainter/weights/recurrent_flow_completion.pth
assets/models/propainter/ProPainter/weights/raft-things.pth
```

Alternatively, pass `propainterDir` and `weightsDir` explicitly. The script checks all three weights before running the official ProPainter inference command; missing files are reported as a structured error instead of triggering an implicit download.
