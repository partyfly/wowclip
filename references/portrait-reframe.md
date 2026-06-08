# Portrait Reframe

Portrait reframe converts landscape clips to vertical clips by generating a crop plan. The plan is inspectable and is compiled into `edl.json` as placement metadata.

## Crop Plan

```json
{
  "schema": "wowclip.portrait-plan.v1",
  "assetId": "A001",
  "target": { "width": 1080, "height": 1920, "aspectRatio": "9:16" },
  "ranges": [
    {
      "startMs": 10000,
      "endMs": 25000,
      "shotId": "shot-0003",
      "selectedPersonLabel": "P1",
      "reason": "dominant_face_with_speech_overlap",
      "cropRect": { "x": 0.28, "y": 0, "width": 0.44, "height": 1 }
    }
  ]
}
```

Coordinates use normalized top-left source coordinates.

## User-Selectable Modes

`portraitMode` controls how a landscape clip becomes 9:16. Crop planning is face-centered and deterministic; it does not preserve embedded portrait regions, use blurred backgrounds, use dialogue stacks, or fall back to center crop.

1. `speaker_crop`
   - Crops around a detected face.
   - Uses the largest possible 9:16 crop inside source bounds.
   - Centers the face horizontally.
   - Places the face anchor in the upper portion of the vertical frame when source bounds allow it.

2. `auto`
   - Alias for `speaker_crop`.
   - Must not preserve detected central 9:16 content.

## Selection Rules

1. Split selected clip ranges by shot boundaries before crop planning.
2. Do not apply one crop rectangle across unrelated camera cuts.
3. Ignore detected embedded 9:16 content for crop planning.
4. Prefer persistent tracked faces over untracked face detections.
5. Keep crop inside source bounds.
6. Omit ranges with no detected face material; do not emit center crop fallback.
7. Generate Agent-selectable portrait materials before assembly: every tracked face crop for each selected range.
8. Bind each planned range to engineered subtitles before compiling `edl.json`.
9. Inspect the plan with evidence-only `wowclip-clip-check.py` before preview/export.

## Engineering QA Outputs

The analysis tools should return deterministic structures, not prose-only results:

- `frames[]`: timestamped sampled frames.
- `shots[]`: shot-scoped ranges generated from sampled frame visual differences.
- `montage`: a JPEG overview for human/AI visual QA.
- `detections[]`: per-frame face boxes.
- `tracks[]`: stable temporary labels such as `P1`, `P2`.
- `materials[]`: candidate `face_crop` ranges bound to subtitles for Agent selection.
- `subtitle`: overlapping engineered subtitles and words for each planned clip or material.
- `warnings[]`: low sample count, no face, out-of-bounds, partial face crop.

Do not rely on the model to invent crop values without these intermediate artifacts.

## Portrait Materials and Clip Check

`wowclip-portrait-materials.py` prepares the reusable material pool before timeline assembly. For each selected range it emits every tracked face crop it can find, each bound to the overlapping subtitle text and words:

```bash
python scripts/wowclip-portrait-materials.py '{"tracksPath":"/abs/project/cache/faces/tracks.json","transcriptPath":"/abs/project/transcripts/source.json","ranges":[{"startMs":0,"endMs":30000}],"outputPath":"/abs/project/cache/previews/portrait_materials.json"}'
```

`wowclip-clip-check.py` is evidence-only. It inspects the planned crop ranges and returns clip content plus searchable subtitle binding; it should not add visual scores, `ok` decisions per clip, or person-specific acceptance logic:

```bash
python scripts/wowclip-clip-check.py '{"portraitPlanPath":"/abs/project/plans/portrait/plan.json","tracksPath":"/abs/project/cache/faces/tracks.json","transcriptPath":"/abs/project/transcripts/source.json","outputPath":"/abs/project/cache/previews/clip_check.json"}'
```

A speech clip inspection should include:

- A valid crop rectangle inside source bounds.
- Overlapping subtitle text.
- Word-level timestamp binding for the clip range.

The Agent should use `materials[].subtitle.text`, `materials[].subtitle.words[]`, `clips[].subtitle.text`, and `clips[].subtitle.words[]` as content hooks when choosing and assembling usable clips.

## EDL Placement

Compile the crop as clip placement in `edl.json`:

```json
{
  "placement": {
    "fit": "cover",
    "mode": "portrait_reframe",
    "targetWidth": 1080,
    "targetHeight": 1920,
    "cropRect": { "x": 0.28, "y": 0, "width": 0.44, "height": 1 },
    "personLabel": "P1"
  }
}
```
