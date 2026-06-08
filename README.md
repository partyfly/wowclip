# WowClip Agent Skill

WowClip is a free, local-first **agent skill** for turning long videos into short vertical clips.

It is designed to be installed into Codex, OpenClaw, Claude Code, or another `SKILL.md`-compatible coding agent. WowClip is not packaged as a standalone desktop app or consumer video editor. The skill gives your agent a repeatable local workflow for analyzing media, creating subtitles, selecting highlights, planning portrait crops, building an editable `edl.json`, and exporting MP4 files with local tools.

[中文说明](README.zh-CN.md)

## What This Is

- A reusable Agent Skill anchored by `SKILL.md`.
- A local video clipping workflow your coding agent can follow.
- A set of Python and Node.js helper scripts the agent can run on your machine.
- A fully local pipeline for subtitles, highlight selection, face-centered portrait reframing, EDL assembly, previews, and FFmpeg export.

## What This Is Not

- Not a SaaS product.
- Not a hosted editing API.
- Not a one-click desktop video editor.
- Not a GUI timeline editor.
- Not a model-weight bundle.

## Install as a Skill

Clone this repository into your agent's skills directory.

For Codex:

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/partyfly/wowclip.git ~/.codex/skills/wowclip
```

For OpenClaw or Claude Code, install the repository into the skills/plugins directory that your agent runtime scans for `SKILL.md` files.

Then start a new agent session and ask for WowClip explicitly:

```text
Use the wowclip skill to analyze this local video and create 3 vertical short clips with burned subtitles.
```

or:

```text
Use the wowclip skill on this YouTube URL. Keep everything local after download, generate subtitles, build edl.json, preview frames, and export MP4.
```

## Agent Workflow

When the skill is active, the agent should:

1. Probe the source media.
2. Generate full-source local subtitles before selecting clips.
3. Select candidate highlight ranges from transcript timing and text.
4. Extract representative frames and detect shot boundaries.
5. Detect and track faces with local OpenCV models.
6. Build deterministic 9:16 face-centered portrait crop plans.
7. Compile selected ranges, crop placement, audio, video, and subtitle clips into `edl.json`.
8. Validate the timeline and portrait plan.
9. Generate preview frames or montages.
10. Export MP4 locally with FFmpeg.

The editable source of truth is `edl.json`, not an ad hoc FFmpeg command.

## Repository Layout

```text
.
├── SKILL.md                         # Agent workflow contract
├── agents/openai.yaml               # Optional agent metadata
├── assets/editor/EDITOR_CONTRACT.md # Optional editor integration contract
├── references/                      # Pipeline design notes
├── schemas/                         # Timeline, highlight, and portrait JSON schemas
├── scripts/                         # Local helper scripts used by the skill
└── tests/                           # Unit tests for planning and overlay utilities
```

## Local Runtime Requirements

Install system tools:

- Python 3.10+
- Node.js 18+
- FFmpeg and FFprobe
- `yt-dlp` for YouTube ingest

Install Python packages for the local helper scripts:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`faster-whisper`, OpenCV, NumPy, Pillow, and yt-dlp are the default Python dependencies. Some features are optional:

- `faster-whisper` is needed for local ASR unless transcript segments are provided.
- OpenCV YuNet is needed for face detection.
- OpenCV SFace is recommended for same-person tracking.
- ProPainter is optional for hard subtitle or watermark removal.

## Model Setup

Prepare the expected local model directory structure:

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

## Direct Script Usage

The recommended entry point is through an agent using `SKILL.md`. Advanced users can also run the helper scripts directly.

Probe a source file:

```bash
node scripts/wowclip-probe.mjs '{"path":"/abs/source.mp4"}'
```

Generate local subtitles:

```bash
python3 scripts/wowclip-transcribe-local.py '{"sourcePath":"/abs/source.mp4","projectRootDir":"/abs/wowclip-project","language":"en"}'
```

Run the YouTube-to-vertical workflow:

```bash
python3 scripts/wowclip-auto-youtube.py '{"url":"https://www.youtube.com/watch?v=...","projectRootDir":"/abs/wowclip-project","language":"en","maxClips":3,"portraitMode":"auto","export":true}'
```

The command writes intermediate artifacts under `projectRootDir`, including transcripts, engineered subtitles, highlight plans, portrait crop plans, preview caches, `edl.json`, and exported MP4 files.

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
