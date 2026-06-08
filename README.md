# WowClip

Free, local-first video clipping for turning long videos into short vertical clips.

WowClip is an offline-first clipping pipeline. It analyzes local video/audio, builds word-level subtitles, selects candidate highlights, tracks faces, creates shot-scoped 9:16 crop plans, compiles a standard `edl.json`, previews frames, and exports MP4 locally.

The goal is simple: a completely free local clipping tool that does not require hosted editing services or cloud ASR.

[中文说明](README.zh-CN.md)

## Status

WowClip is currently a developer-oriented local pipeline. The core workflow lives in this repository as Python and Node.js scripts plus JSON schemas and reference docs. It is suitable for local experimentation, automation, and integration into an editor, but it is not yet packaged as a one-click desktop app.

## What It Does

- Downloads YouTube sources with `yt-dlp`, or works with an existing local video.
- Transcribes speech locally with `faster-whisper` when a local model is available.
- Generates engineered subtitle assets for the full source before clip selection.
- Selects candidate highlight ranges from transcript timing and text.
- Extracts representative frames and detects shot boundaries.
- Detects and tracks faces with local OpenCV models.
- Builds deterministic face-centered 9:16 portrait crop plans.
- Compiles selected ranges, crop placement, audio, video, and subtitle clips into `edl.json`.
- Exports MP4 locally with FFmpeg.

## Design Principles

- **Local first:** media, audio, transcripts, and timeline data stay on your machine.
- **Free stack:** the pipeline is built around open-source tools and local models.
- **Non-destructive editing:** source media is never overwritten; generated work is stored in project folders.
- **EDL as source of truth:** `edl.json` is the canonical editable timeline, not one-off FFmpeg commands.
- **Subtitles before selection:** speech clips must be traceable back to source words or source segments.
- **No silent downloads:** model directories can be prepared, but models must be downloaded explicitly.

## Repository Layout

```text
.
├── SKILL.md                         # Workflow contract used by local agents
├── assets/editor/EDITOR_CONTRACT.md # Optional editor integration contract
├── references/                      # Pipeline design notes
├── schemas/                         # Timeline, highlight, and portrait JSON schemas
├── scripts/                         # Local pipeline scripts
└── tests/                           # Unit tests for planning and overlay utilities
```

## Requirements

Install system tools:

- Python 3.10+
- Node.js 18+
- FFmpeg and FFprobe
- `yt-dlp` for YouTube ingest

Install Python packages for the full local workflow:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`faster-whisper`, OpenCV, NumPy, Pillow, and yt-dlp are the default Python dependencies. Some features are optional:

- `faster-whisper` is needed for local ASR unless you provide transcript segments yourself.
- OpenCV YuNet is needed for face detection.
- OpenCV SFace is recommended for same-person tracking.
- ProPainter is optional for hard subtitle or watermark removal.

## Model Setup

Prepare the expected model directory structure:

```bash
python3 scripts/wowclip-bootstrap-models.py '{"modelsDir":"./assets/models"}'
```

This command creates directories and reports missing files. It does not download models automatically.

Expected local model locations include:

```text
assets/models/
├── opencv/
│   ├── face_detection_yunet.onnx
│   └── face_recognition_sface.onnx
├── silero/
│   └── silero_vad.onnx
├── whisper/
└── propainter/
```

See `references/local-models.md` for details.

## Quick Start: Local Video

Probe a source file:

```bash
node scripts/wowclip-probe.mjs '{"path":"/abs/source.mp4"}'
```

Generate local subtitles:

```bash
python3 scripts/wowclip-transcribe-local.py '{"sourcePath":"/abs/source.mp4","projectRootDir":"/abs/wowclip-project","language":"en"}'
```

Select candidate clips:

```bash
python3 scripts/wowclip-select-clips.py '{"transcriptPath":"/abs/wowclip-project/transcripts/source.json","projectRootDir":"/abs/wowclip-project","maxClips":5}'
```

From there, run frame extraction, shot detection, face detection/tracking, portrait planning, timeline build, validation, preview, and export. The full command list is in `SKILL.md`.

## Quick Start: YouTube to Vertical MP4

After FFmpeg, yt-dlp, Python dependencies, and local models are ready:

```bash
python3 scripts/wowclip-auto-youtube.py '{"url":"https://www.youtube.com/watch?v=...","projectRootDir":"/abs/wowclip-project","language":"en","maxClips":3,"portraitMode":"auto","export":true}'
```

The command writes all intermediate artifacts under `projectRootDir`, including:

- `transcripts/`
- `LiveClipper/subtitles/`
- `plans/clips/highlight-plan.json`
- `plans/portrait/plan.json`
- `cache/previews/`
- `edl.json`
- `exports/youtube_portrait.mp4`
- `wowclip-auto-result.json`

## Testing

Run the current WowClip tests:

```bash
python3 -m unittest discover -s tests
```

## Privacy

WowClip is designed so runtime media processing can happen locally. The project scripts should not upload source media, audio, transcripts, face detections, or timelines. You are still responsible for reviewing any third-party tools or models you install separately.

## Third-Party Tools and Models

This repository is licensed under MIT for the WowClip code in this project. Third-party tools, models, and datasets are governed by their own licenses and terms, including FFmpeg, yt-dlp, faster-whisper, Whisper model weights, OpenCV models, Silero VAD, and ProPainter.

Do not redistribute model weights or third-party binaries unless their licenses allow it.

## License

MIT. See [LICENSE](LICENSE).
