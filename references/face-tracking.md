# Face Tracking

WowClip tracks people inside a single video. It does not identify real-world identity.

## Detection

Use OpenCV YuNet to produce:

```json
{
  "timeMs": 5000,
  "faces": [
    {
      "box": { "x": 0.33, "y": 0.18, "width": 0.12, "height": 0.22 },
      "landmarks": [],
      "score": 0.94
    }
  ]
}
```

## Tracking

Assign temporary labels such as `P1`, `P2` using:

- SFace cosine similarity for same-person matching.
- IoU continuity for adjacent frames.
- Maximum movement threshold between frames.
- Track persistence score.

Never store biometric identity outside project-local cache unless the user explicitly asks.

## SFace Embedding Matching

SFace is optional but recommended. It improves tracking when people cross paths or leave and re-enter the frame.

Pipeline:

1. YuNet detects face box and five landmarks.
2. SFace aligns the face crop from the original frame.
3. SFace extracts an embedding vector.
4. The tracker compares embeddings using cosine similarity.
5. The vector is used only during matching and is not written to timeline output.

Runtime behavior:

- If `face_recognition_sface.onnx` exists, `wowclip-track-faces.py` uses it.
- If the model is missing, tracking falls back to IoU/distance heuristics.
- Track output records `embeddingSampleCount`, not raw embedding vectors.
- Temporary labels like `P1` are not identity claims.

## Crop Material Ladder

Use this deterministic crop material ladder:

1. Track-level selection: choose a persistent person track in the requested range.
2. Frame-level selection: choose the best single untracked face only when tracking fails.
3. No face material: omit the range and warn; do not emit center crop fallback.

Every fallback below track-level selection must add a warning to the crop plan.

## Minimum Quality Gates

- A tracked subject should have at least two samples in the range.
- Prefer tracks with `embeddingSampleCount > 0` in multi-person scenes.
- The final crop should contain at least 85% of the selected face box in scored frames.
- Crop coordinates must stay in `[0, 1]`.
- Avoid abrupt crop jumps unless there is a shot boundary or selected person changes.
- Face crops should center the face horizontally and place the face anchor in the upper portion of the vertical frame when source bounds allow it.
