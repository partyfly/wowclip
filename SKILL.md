---
name: wowclip
description: Use when Codex needs to locally analyze video/audio, generate engineered subtitles with offline ASR, create or modify standardized edl.json timelines, convert landscape video to vertical 9:16 clips, track faces locally, preview edits, or export short-form videos. This skill is fully local/offline-first and does not depend on any hosted video editing service.
metadata:
  short-description: Local AI video clipping and portrait reframing
---

# WowClip

WowClip is an offline-first video clipping workflow. It uses local open-source models for speech transcription, voice activity detection, face detection, same-person tracking, portrait crop planning, standardized EDL assembly, and local export.

## Core Rules

- Do not call cloud APIs.
- Do not overwrite source media.
- `edl.json` is the canonical editable timeline. Use `wowclip.timeline.v1`.
- Agent editing must target `edl.json`, highlight plans, subtitle assets, or portrait plans. Do not create one-off FFmpeg scripts as the source of truth.
- Do not edit `edl.json` directly. Use `wowclip-update-edl.mjs` for EDL mutations so version checks and validation run.
- Keep all generated files inside the project directory.
- Use `wowclip.portrait-plan.v1` for horizontal-to-vertical crop plans.
- Ask or honor the user's portrait mode when converting landscape to vertical: `speaker_crop` or `auto`. `auto` is an alias for `speaker_crop`.
- For traffic clips, ask which editing mode the user wants when the choice is ambiguous: faithful excerpt, hook-first remix, aggressive short-form, or analysis-only planning.
- Build full-file subtitle assets before clip selection. Do not rely on subtitle coverage checks as a substitute for engineered subtitle generation.
- Every speech clip must be bound to engineered subtitles and traceable back to source words or source segments.
- Build and validate `plans/clips/highlight-plan.json` before EDL compilation. EDL clips must come from a selected `clipPlan`, not directly from raw candidate ranges.
- Validate `edl.json`, highlight plans, and crop plan JSON before preview/export.
- Generate preview frames or montage images before claiming a visual crop is ready.

## Default Local Stack

- Media metadata and export: FFmpeg / FFprobe.
- URL ingest: yt-dlp for YouTube downloads.
- Voice activity detection: Silero VAD ONNX.
- Speech recognition: faster-whisper with local Whisper models.
- Portable fallback ASR: whisper.cpp.
- Face detection: OpenCV YuNet.
- Same-person tracking: OpenCV SFace embeddings plus IoU/temporal smoothing.
- Portrait crop planning: face-centered 9:16 crops only; no center crop fallback.
- Hard subtitle/watermark removal: official ProPainter with a deterministic mask before portrait cropping.

## Portrait Modes

WowClip crop planning is deterministic and face-centered. It does not use content scores, embedded portrait preservation, blurred-background fallback, dialogue stacks, or center-crop fallback for portrait material generation.

- `speaker_crop`: generate the largest possible 9:16 crop that centers the tracked face horizontally and places the face anchor in the upper portion of the vertical frame when source bounds allow it.
- `auto`: alias for `speaker_crop`; it must not preserve central embedded 9:16 content.

When the user does not choose a mode, default the automated pipeline to `auto`. If no face-backed crop material exists for a selected range, stop and report the artifact instead of exporting a center crop.

## Project Layout

```text
project/
├── wowclip.project.json
├── edl.json
├── source-links.json
├── transcripts/                         # Raw ASR JSON and compatibility SRTs.
├── LiveClipper/
│   ├── workflow-state.json
│   └── subtitles/
│       ├── merged.srt
│       ├── merged_words.srt
│       └── merged_words_dense.tsv
├── plans/
│   ├── clips/
│   └── portrait/
├── cache/
│   ├── frames/
│   ├── faces/
│   ├── overlays/
│   ├── waveforms/
│   └── previews/
└── exports/
```

## Workflow

This workflow is intentionally engineered instead of prompt-only. Do not ask the model to guess crop rectangles or clip meaning from the source filename. Build intermediate artifacts first, then let the Agent reason over those artifacts.

1. Probe source media and create a local project folder.
2. Run local ASR for the whole source whenever speech exists. Keep raw `segments[]` and `words[]` in `transcripts/*.json`.
3. Compile engineered subtitle assets for the whole source before clip selection: `merged.srt`, `merged_words.srt`, and `merged_words_dense.tsv`.
4. If source frames show hard-burned subtitles or watermarks, run `wowclip-remove-overlays.py` on the source material before portrait crop planning. Removing subtitles before crop keeps the repair region small and avoids enlarged, cut-off subtitle artifacts after 9:16 reframing.
5. Create and validate a highlight plan with complete clip plans, not only one-minute ranges. Each clip plan must contain segment roles such as `hook`, `proof`, `demo`, `benefit`, `body`, or `cta`, plus edit actions such as `hook_frontload`, `trim_breath`, `remove_filler`, `tighten_pause`, and `keep_context`.
6. Extract representative frames for candidate ranges and build a montage so the Agent can inspect visual content quickly.
7. Detect shot boundaries from sampled frames. Crop ranges must be shot-scoped; do not apply one crop rectangle across a long multi-shot subtitle range.
8. If converting to portrait, ask or honor the portrait mode, then detect faces and track same persons across sampled frames.
9. Generate high-quality portrait material candidates before assembly: every tracked face crop for each selected range, all bound to the overlapping subtitles.
10. Generate a 9:16 portrait crop plan from face detections/tracks only: shot-scoped tracked face -> untracked face material. Do not use embedded 9:16 content or center crop fallback.
11. Run `clip_check` as evidence-only inspection: return clip ranges, crop metadata, warnings, and the corresponding subtitle text/words. Do not use it as a visual score or person-specific gate.
12. Compile the selected clip plan, engineered subtitles, and portrait placements into standard `edl.json`.
13. Validate `edl.json` and the portrait plan. A valid speech EDL has video/audio clips and subtitle clips whose timeline times are remapped from source subtitle entries.
14. Preview key frames or montage from the final EDL.
15. Export locally from `edl.json`.

## YouTube Auto Workflow

For a YouTube URL, keep the user-facing flow simple but preserve the engineering gates:

1. Ingest the YouTube URL with `yt-dlp`.
2. Generate full-file word-level subtitles locally.
3. Compile engineered subtitle assets.
4. Inspect sampled frames for hard-burned subtitles or watermarks. If present, run `wowclip-remove-overlays.py` before any portrait crop planning.
5. Select candidate highlights and create explicit clip plans with hook/body/proof/CTA roles.
6. Extract frames, detect shots, and run candidate precheck for visual usability.
7. Detect/track faces and prepare face-crop portrait materials for Agent selection.
8. Write the shot-scoped portrait crop plan and run evidence-only `clip_check` for clip/subtitle binding.
9. Build standard `edl.json` with video, audio, and subtitle tracks.
10. Validate and preview the EDL.
11. Export vertical MP4 with optional burned subtitles.

Use `wowclip-auto-youtube.py` for the full chain. If any gate fails, stop and report the failing artifact instead of exporting an unverified clip.

## Subtitle and EDL Contract

Subtitles are source assets, not post-export overlays:

- `transcripts/*.json` stores raw ASR segments and words.
- `LiveClipper/subtitles/merged.srt` stores engineered sentence subtitles for normal timeline use.
- `LiveClipper/subtitles/merged_words.srt` stores word-level subtitle timing for search and debugging.
- `LiveClipper/subtitles/merged_words_dense.tsv` stores dense source-word rows for deterministic remapping.
- `edl.json` stores selected subtitle clips on the `S1` track, remapped to timeline time.

When the source is speech-heavy, do not select or export clips before full-source subtitles exist. Missing subtitles are a pipeline failure to fix at ASR/subtitle compilation time, not a reason to patch only the affected export range.

## Portrait Reframe Contract

Horizontal-to-vertical conversion is a pipeline contract, not a single crop command:

- `transcripts/*.json` is mandatory for speech clips. It should contain `segments[]` and `words[]` with `startMs`/`endMs`.
- `LiveClipper/subtitles/**` stores the engineered subtitle assets used by all clip plans and EDL builds.
- `cache/frames/**/frames.json` is the visual sampling manifest.
- `cache/frames/**/shots.json` or `cache/frames/shots.json` stores shot boundaries.
- `cache/overlays/**` stores generated masks, ProPainter work inputs, contact sheets, and cleaned overlay-removal previews.
- `cache/faces/detections.json` stores per-frame YuNet detections.
- `cache/faces/tracks.json` stores stable labels such as `P1`, `P2`; do not expose raw face embeddings in final outputs.
- `cache/previews/portrait_materials.json` stores Agent-selectable face crop candidates with subtitle bindings.
- `cache/previews/clip_check.json` stores evidence-only clip range and subtitle bindings for the planned crop ranges.
- `plans/portrait/plan.json` stores deterministic crop ranges.
- `plans/clips/highlight-plan.json` stores highlight and clip-plan decisions.
- `edl.json` stores final non-destructive placement and subtitle clips.

When searching or selecting clips, inspect both the montage/preview and the engineered subtitles. The subtitle assets are what let an Agent understand why a visually similar clip matters.

## Common Commands

Scripts accept one JSON argument or JSON from stdin.

```bash
python scripts/wowclip-bootstrap-models.py '{"modelsDir":"./assets/models"}'
python scripts/wowclip-ingest-youtube.py '{"url":"https://www.youtube.com/watch?v=...","projectRootDir":"/abs/project"}'
python scripts/wowclip-auto-youtube.py '{"url":"https://www.youtube.com/watch?v=...","projectRootDir":"/abs/project","language":"en","maxClips":3,"portraitMode":"speaker_crop","export":true}'
node scripts/wowclip-probe.mjs '{"path":"/abs/source.mp4"}'
python scripts/wowclip-transcribe-local.py '{"sourcePath":"/abs/source.mp4","projectRootDir":"/abs/project"}'
python scripts/wowclip-remove-overlays.py '{"sourcePath":"/abs/source.mp4","projectRootDir":"/abs/project","propainterDir":"/abs/ProPainter","weightsDir":"/abs/propainter-weights","maskRect":{"x":0,"y":0.80,"width":1,"height":0.19},"outputPath":"/abs/project/exports/source_clean.mp4"}'
python scripts/wowclip-select-clips.py '{"transcriptPath":"/abs/project/transcripts/source.json","projectRootDir":"/abs/project","maxClips":5}'
python scripts/wowclip-validate-highlight-plan.py '{"highlightPlanPath":"/abs/project/plans/clips/highlight-plan.json","strict":true}'
python scripts/wowclip-extract-frames.py '{"sourcePath":"/abs/source.mp4","projectRootDir":"/abs/project","startMs":0,"endMs":30000}'
python scripts/wowclip-detect-shots.py '{"manifestPath":"/abs/project/cache/frames/source/frames.json","outputPath":"/abs/project/cache/frames/shots.json"}'
python scripts/wowclip-preview-montage.py '{"manifestPath":"/abs/project/cache/frames/source/frames.json"}'
python scripts/wowclip-detect-faces.py '{"framesDir":"/abs/project/cache/frames/source"}'
python scripts/wowclip-precheck-candidates.py '{"candidatesPath":"/abs/project/plans/clips/candidates.json","detectionsPath":"/abs/project/cache/faces/detections.json"}'
python scripts/wowclip-track-faces.py '{"detectionsPath":"/abs/project/cache/faces/detections.json"}'
python scripts/wowclip-plan-portrait.py '{"detectionsPath":"/abs/project/cache/faces/detections.json","tracksPath":"/abs/project/cache/faces/tracks.json","shotsPath":"/abs/project/cache/frames/shots.json","portraitMode":"auto"}'
python scripts/wowclip-portrait-materials.py '{"tracksPath":"/abs/project/cache/faces/tracks.json","transcriptPath":"/abs/project/transcripts/source.json","ranges":[{"startMs":0,"endMs":30000}],"outputPath":"/abs/project/cache/previews/portrait_materials.json"}'
python scripts/wowclip-score-crop.py '{"portraitPlanPath":"/abs/project/plans/portrait/plan.json","tracksPath":"/abs/project/cache/faces/tracks.json"}'
python scripts/wowclip-clip-check.py '{"portraitPlanPath":"/abs/project/plans/portrait/plan.json","tracksPath":"/abs/project/cache/faces/tracks.json","transcriptPath":"/abs/project/transcripts/source.json","outputPath":"/abs/project/cache/previews/clip_check.json"}'
python scripts/wowclip-build-timeline.py '{"sourcePath":"/abs/source.mp4","highlightPlanPath":"/abs/project/plans/clips/highlight-plan.json","selectedClipPlanId":"CP001","portraitPlanPath":"/abs/project/plans/portrait/plan.json","clipCheckPath":"/abs/project/cache/previews/clip_check.json","projectRootDir":"/abs/project","outputPath":"/abs/project/edl.json"}'
node scripts/wowclip-validate.mjs '{"edlPath":"/abs/project/edl.json","portraitPlanPath":"/abs/project/plans/portrait/plan.json"}'
node scripts/wowclip-update-edl.mjs '{"edlPath":"/abs/project/edl.json","baseVersion":0,"script":"edl.ui.canvas.width = 1080; return edl;","summary":"Set canvas width"}'
python scripts/wowclip-preview-frame.py '{"timelinePath":"/abs/project/edl.json","timeMs":5000}'
python scripts/wowclip-export.py '{"edlPath":"/abs/project/edl.json","outputPath":"/abs/project/exports/final.mp4","burnSubtitles":true}'
```

## References

- Local model stack: `references/local-models.md`
- Timeline schema: `references/timeline-schema.md`
- Portrait crop planning: `references/portrait-reframe.md`
- Subtitle pipeline: `references/subtitle-pipeline.md`
- Face tracking: `references/face-tracking.md`
- Export pipeline: `references/export-pipeline.md`
- YouTube auto pipeline: `references/youtube-auto-pipeline.md`
