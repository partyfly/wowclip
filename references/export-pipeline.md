# Export Pipeline

The local export pipeline consumes only `edl.json`. FFmpeg execution is an implementation detail, not the editable source of truth.

1. Validate `edl.json`.
2. Resolve assets and canvas from the EDL.
3. Render video/audio clips in timeline order.
4. Apply EDL placement/crop metadata.
5. Compile subtitle track clips into ASS/SRT render assets.
6. Write MP4 to `exports/`.

Portrait export may render each EDL media clip with its own placement and concatenate rendered segments, but the segment list must come from the EDL. Do not pass portrait plans, clip-check files, or source paths directly to the exporter.

## Preview Before Export

For portrait reframing, generate:

- a source montage before planning,
- a cropped preview frame near the beginning,
- a cropped preview frame near the midpoint,
- a cropped preview frame near the end.

If preview scoring reports poor face visibility or unreadable subtitles, revise the portrait plan or subtitle style and rebuild `edl.json` before export.
