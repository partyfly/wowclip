# YouTube Auto Pipeline

The YouTube path turns one URL into local portrait exports. It is local/offline after download: no cloud ASR and no hosted editing APIs.

## Product Steps

1. Generate full-source engineered subtitles.
2. Run candidate precheck to verify that selected ranges have usable visual samples.
3. Write highlight/clip plans with hook-first segment roles.
4. Compile the selected plan into `edl.json` with portrait placement and subtitle clips.
5. Export the EDL to vertical video.

## Engineering Steps

1. `wowclip-ingest-youtube.py`
   - Downloads the source with `yt-dlp`.
   - Saves `source-links.json` and YouTube metadata.
   - Only supports YouTube URLs.

2. `wowclip-transcribe-local.py`
   - Generates `transcripts/source.json`, engineered SRT files, word SRT files, and dense word TSV files.
   - Word timestamps are required for speech clips.

3. `wowclip-select-clips.py`
   - Builds subtitle-driven candidates.
   - Preserves `startMs`, `endMs`, `text`, `segmentIds`, and `wordCount`.
   - Writes `plans/clips/highlight-plan.json`.

4. `wowclip-validate-highlight-plan.py`
   - Validates clip plan roles, hook position, actions, segment ranges, and duration gates.

5. `wowclip-extract-frames.py`, `wowclip-detect-shots.py`, and `wowclip-preview-montage.py`
   - Produce visual samples and a Look-style montage.
   - Detect shot boundaries so portrait crops do not span unrelated camera cuts.

6. `wowclip-detect-faces.py` and `wowclip-precheck-candidates.py`
   - Check whether candidate ranges have enough visual evidence.
   - Precheck happens before crop planning, so it validates range usability rather than `cropRect`.

7. `wowclip-track-faces.py`, `wowclip-portrait-materials.py`, and `wowclip-plan-portrait.py`
   - Track subjects and generate shot-scoped ranges in `plans/portrait/plan.json`.
   - Prepare Agent-selectable `face_crop` materials with subtitle bindings.
   - The automated default portrait mode is `auto`, which is an alias for shot-scoped `speaker_crop`.
   - If no face-centered portrait ranges or materials exist, the pipeline stops instead of exporting a center crop.

8. `wowclip-clip-check.py`
   - Evidence-only inspection after crop planning.
   - Returns planned clip ranges, crop metadata, warnings, subtitle text, and word timestamps without visual scores.

9. `wowclip-build-timeline.py` and `wowclip-export.py`
   - Build `edl.json` from the selected clip plan, engineered subtitles, and portrait placement.
   - Export one or more portrait ranges from `edl.json`.
   - Burn subtitles from EDL subtitle clips when enabled.

## One Command

```bash
python scripts/wowclip-auto-youtube.py '{"url":"https://www.youtube.com/watch?v=...","projectRootDir":"/abs/project","language":"en","maxClips":3,"portraitMode":"auto","export":true}'
```

The command writes `wowclip-auto-result.json` with all intermediate artifact paths.

Set `portraitMode` to `auto` or `speaker_crop`. Both modes generate face-centered crops only.

## Gate Rule

Do not export a speech clip unless engineered subtitles exist for the source and final validation passes. If candidate precheck passes but EDL validation fails, fix the subtitle, clip-plan, or portrait-plan artifact and rebuild `edl.json`.
