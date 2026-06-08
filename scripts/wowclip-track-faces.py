#!/usr/bin/env python3
"""Track same-person face detections with deterministic local heuristics."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def center(box: dict) -> tuple[float, float]:
    return float(box["x"]) + float(box["width"]) / 2, float(box["y"]) + float(box["height"]) / 2


def iou(a: dict, b: dict) -> float:
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2, ay2 = ax1 + float(a["width"]), ay1 + float(a["height"])
    bx1, by1 = float(b["x"]), float(b["y"])
    bx2, by2 = bx1 + float(b["width"]), by1 + float(b["height"])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = float(a["width"]) * float(a["height"]) + float(b["width"]) * float(b["height"]) - inter
    return inter / union if union > 0 else 0.0


def distance(a: dict, b: dict) -> float:
    ax, ay = center(a)
    bx, by = center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return None
    return dot / (na * nb)


def centroid(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    length = len(vectors[0])
    if length == 0:
        return None
    sums = [0.0] * length
    count = 0
    for vector in vectors:
        if len(vector) != length:
            continue
        count += 1
        for index, value in enumerate(vector):
            sums[index] += float(value)
    if count == 0:
        return None
    avg = [value / count for value in sums]
    norm = math.sqrt(sum(value * value for value in avg))
    if norm <= 0:
        return avg
    return [value / norm for value in avg]


def load_sface(payload: dict):
    model_path_raw = payload.get("sfacePath") or payload.get("sfaceModelPath") or "assets/models/opencv/face_recognition_sface.onnx"
    model_path = Path(model_path_raw).expanduser().resolve()
    if not model_path.exists():
        return None, f"sface_model_missing:{model_path}"
    try:
        import cv2  # type: ignore
    except Exception:
        return None, "opencv_python_missing"
    try:
        return cv2.FaceRecognizerSF.create(str(model_path), ""), None
    except Exception as error:
        return None, f"sface_init_failed:{error}"


def raw_yunet_matrix(face: dict):
    values = face.get("rawYuNet")
    if isinstance(values, list) and len(values) >= 15:
        return values
    pixel = face.get("pixelBox") or {}
    x = float(pixel.get("x", 0))
    y = float(pixel.get("y", 0))
    w = float(pixel.get("width", 0))
    h = float(pixel.get("height", 0))
    landmarks = face.get("landmarks") or []
    # SFace alignment needs 5 landmarks in pixel coordinates. If they are not
    # available, signal no embedding rather than fabricating biometric input.
    image_size = face.get("_imageSize") or {}
    width = float(image_size.get("width", 0))
    height = float(image_size.get("height", 0))
    if len(landmarks) < 5 or width <= 0 or height <= 0:
        return None
    raw = [x, y, w, h]
    for landmark in landmarks[:5]:
        raw.extend([float(landmark.get("x", 0)) * width, float(landmark.get("y", 0)) * height])
    raw.append(float(face.get("score", 0)))
    return raw


def embedding_for_face(recognizer, frame_cache: dict, face: dict, frame_path: str):
    if recognizer is None or not frame_path:
        return None
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None
    image = frame_cache.get(frame_path)
    if image is None:
        image = cv2.imread(frame_path)
        if image is None:
            return None
        frame_cache[frame_path] = image
    raw = raw_yunet_matrix(face)
    if raw is None:
        return None
    try:
        face_matrix = np.array(raw, dtype=np.float32).reshape(1, -1)
        aligned = recognizer.alignCrop(image, face_matrix)
        feature = recognizer.feature(aligned)
        vector = feature.flatten().astype(float).tolist()
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector
    except Exception:
        return None


def main() -> int:
    payload = read_input()
    detections_path = Path(payload.get("detectionsPath") or "").expanduser().resolve()
    if not detections_path.exists():
        print(json.dumps({"ok": False, "error": "detectionsPath does not exist"}, indent=2))
        return 1
    doc = json.loads(detections_path.read_text(encoding="utf-8"))
    detections = sorted(doc.get("detections") or [], key=lambda item: int(item.get("timeMs", 0)))
    max_distance = float(payload.get("maxDistance", 0.22))
    min_iou = float(payload.get("minIou", 0.03))
    min_embedding_similarity = float(payload.get("minEmbeddingSimilarity", 0.36))
    max_gap_ms = int(payload.get("maxGapMs", 2000))
    use_sface = payload.get("useSFace", True) is not False
    recognizer, sface_warning = load_sface(payload) if use_sface else (None, "sface_disabled")
    frame_cache = {}
    warnings = []
    if sface_warning:
        warnings.append(sface_warning)
    tracks: list[dict] = []

    for frame in detections:
        time_ms = int(frame.get("timeMs", 0))
        frame_path = frame.get("framePath") or frame.get("path") or ""
        image_size = frame.get("imageSize") or {}
        for face in frame.get("faces") or []:
            face["_imageSize"] = image_size
            box = face.get("box") or {}
            embedding = embedding_for_face(recognizer, frame_cache, face, frame_path)
            best = None
            best_score = -999.0
            for track in tracks:
                if time_ms - int(track["lastTimeMs"]) > max_gap_ms:
                    continue
                last_box = track["lastBox"]
                overlap = iou(box, last_box)
                dist = distance(box, last_box)
                similarity = cosine_similarity(embedding, track.get("embeddingCentroid"))
                embedding_match = similarity is not None and similarity >= min_embedding_similarity
                geometric_match = overlap >= min_iou or dist <= max_distance
                score = overlap * 1.5 - dist + (similarity if similarity is not None else 0.0)
                if (embedding_match or geometric_match) and score > best_score:
                    best = track
                    best_score = score
            detection = {
                "timeMs": time_ms,
                "box": box,
                "score": float(face.get("score", 0)),
                "framePath": frame_path,
                "hasEmbedding": embedding is not None,
            }
            if best is None:
                label = f"P{len(tracks) + 1}"
                tracks.append({
                    "label": label,
                    "detections": [detection],
                    "firstTimeMs": time_ms,
                    "lastTimeMs": time_ms,
                    "lastBox": box,
                    "_embeddings": [embedding] if embedding is not None else [],
                    "embeddingCentroid": embedding,
                })
            else:
                best["detections"].append(detection)
                best["lastTimeMs"] = time_ms
                best["lastBox"] = box
                if embedding is not None:
                    best.setdefault("_embeddings", []).append(embedding)
                    best["embeddingCentroid"] = centroid(best["_embeddings"])

    output_tracks = []
    for track in tracks:
        detections_for_track = track["detections"]
        areas = [float(d["box"].get("width", 0)) * float(d["box"].get("height", 0)) for d in detections_for_track]
        avg_area = sum(areas) / len(areas) if areas else 0
        output_tracks.append({
            "label": track["label"],
            "firstTimeMs": track["firstTimeMs"],
            "lastTimeMs": track["lastTimeMs"],
            "seenFrameCount": len(detections_for_track),
            "averageArea": avg_area,
            "embeddingSampleCount": len(track.get("_embeddings") or []),
            "matching": {
                "sfaceEnabled": recognizer is not None,
                "minEmbeddingSimilarity": min_embedding_similarity,
            },
            "detections": detections_for_track,
        })
    output_tracks.sort(key=lambda item: (-item["seenFrameCount"], -item["averageArea"], item["firstTimeMs"]))

    output_path = Path(payload.get("outputPath") or detections_path.parent / "tracks.json").expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "wowclip.face-tracks.v1",
        "sourceDetectionsPath": str(detections_path),
        "tracks": output_tracks,
        "warnings": warnings + ([] if output_tracks else ["no_faces_tracked"]),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "outputPath": str(output_path), "trackCount": len(output_tracks), "tracks": output_tracks}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
