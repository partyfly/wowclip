# Subtitle Pipeline

Subtitles are full-source assets. Generate and normalize them before clip selection, portrait reframing, or export.

## Pipeline

1. Extract audio with FFmpeg to mono 16 kHz WAV.
2. Run VAD/chunk planning for long files.
3. Run faster-whisper or whisper.cpp locally with word timestamps.
4. Merge chunk results into one source timeline.
5. Run engineered sentence splitting.
6. Write canonical subtitle artifacts.
7. Build EDL subtitle clips by intersecting source subtitle entries with selected clip-plan segments.

## Canonical Outputs

```text
transcripts/source.json
LiveClipper/workflow-state.json
LiveClipper/subtitles/merged.srt
LiveClipper/subtitles/merged_words.srt
LiveClipper/subtitles/merged_words_dense.tsv
```

Do not treat missing subtitles in an exported clip as a local rendering problem. Fix the ASR/subtitle asset pipeline so the whole source has engineered subtitles.

## Engineered Split Rules

Use source words when available. If a source segment has weak word coverage, split from segment text and keep source timing stable.

Recommended defaults:

- vertical subtitles: max 26 display characters per subtitle chunk;
- engineered sentence duration: max 6 seconds;
- line break gap: split when word gap exceeds 1000 ms;
- punctuation split: prefer natural punctuation boundaries;
- vertical display text: strip trailing punctuation when it improves readability;
- subtitle track layout: use EDL `styleOverride` or track style, not ad hoc drawtext.

## EDL Remapping

For each selected clip-plan segment:

1. Find source subtitle entries overlapping `startMs/endMs`.
2. Intersect the subtitle source range with the segment source range.
3. Convert intersected source times into timeline `dstStart/dstEnd`.
4. Emit one subtitle clip per engineered subtitle entry.

This keeps subtitles complete across jump cuts and hook-frontloaded edits.
