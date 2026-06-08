#!/usr/bin/env python3
"""Generate portrait material candidates from tracked faces and subtitles."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def join_words(words: list[dict]) -> str:
    tokens = [str(word.get("word") or "").strip() for word in words if str(word.get("word") or "").strip()]
    if not tokens:
        return ""
    if any(has_cjk(token) for token in tokens):
        return "".join(tokens)
    return " ".join(tokens)


def overlap_ms(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def transcript_segments(transcript_doc: dict) -> list[dict]:
    normalized = []
    for index, segment in enumerate(transcript_doc.get("segments") or [], start=1):
        start_ms = int(segment.get("startMs", round(float(segment.get("start", 0)) * 1000)))
        end_ms = int(segment.get("endMs", round(float(segment.get("end", 0)) * 1000)))
        text = str(segment.get("text") or "").strip()
        if end_ms <= start_ms:
            continue
        words = []
        for word_index, word in enumerate(segment.get("words") or [], start=1):
            word_start = int(word.get("startMs", round(float(word.get("start", start_ms / 1000)) * 1000)))
            word_end = int(word.get("endMs", round(float(word.get("end", end_ms / 1000)) * 1000)))
            token = str(word.get("word") or word.get("text") or "").strip()
            if token and word_end > word_start:
                words.append({
                    "id": word.get("id") or f"{segment.get('id') or index}-w{word_index:03d}",
                    "startMs": word_start,
                    "endMs": word_end,
                    "word": token,
                })
        normalized.append({
            "id": segment.get("id") or f"seg-{index:04d}",
            "startMs": start_ms,
            "endMs": end_ms,
            "text": text,
            "words": words,
        })
    return normalized


def bind_subtitles(start_ms: int, end_ms: int, segments: list[dict], max_words: int) -> dict:
    overlapping_segments = []
    overlapping_words = []
    for segment in segments:
        segment_overlap = overlap_ms(start_ms, end_ms, int(segment["startMs"]), int(segment["endMs"]))
        if segment_overlap <= 0:
            continue
        segment_words = [
            word
            for word in segment.get("words") or []
            if overlap_ms(start_ms, end_ms, int(word["startMs"]), int(word["endMs"])) > 0
        ]
        overlapping_segments.append({
            "id": segment["id"],
            "startMs": segment["startMs"],
            "endMs": segment["endMs"],
            "text": segment["text"],
            "overlapMs": segment_overlap,
            "wordCount": len(segment_words),
        })
        overlapping_words.extend(segment_words)
    text = join_words(overlapping_words) if overlapping_words else " ".join(item["text"] for item in overlapping_segments).strip()
    return {
        "text": text,
        "segments": overlapping_segments,
        "words": overlapping_words[:max_words],
        "wordCount": len(overlapping_words),
        "hasWordTimestamps": bool(overlapping_words),
        "truncatedWords": max(0, len(overlapping_words) - max_words),
    }


def average_box(detections: list[dict]) -> dict | None:
    if not detections:
        return None
    sums = {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    for detection in detections:
        box = detection.get("box") or {}
        for key in sums:
            sums[key] += float(box.get(key, 0))
    return {key: sums[key] / len(detections) for key in sums}


def crop_for_face(box: dict, source_aspect: float, target_aspect: float = 9 / 16) -> dict:
    if source_aspect >= target_aspect:
        crop_height = 1.0
        crop_width = target_aspect / source_aspect
    else:
        crop_width = 1.0
        crop_height = source_aspect / target_aspect
    face_cx = float(box["x"]) + float(box["width"]) / 2
    face_cy = float(box["y"]) + float(box["height"]) * 0.38
    x = clamp(face_cx - crop_width / 2, 0.0, 1.0 - crop_width)
    y = clamp(face_cy - crop_height * 0.33, 0.0, 1.0 - crop_height)
    return {"x": x, "y": y, "width": crop_width, "height": crop_height}


def normalize_ranges(payload: dict) -> list[dict]:
    ranges = []
    for index, item in enumerate(payload.get("ranges") or [], start=1):
        start_ms = int(item.get("startMs", item.get("start", 0)))
        end_ms = int(item.get("endMs", item.get("end", start_ms)))
        if end_ms > start_ms:
            ranges.append({
                "id": str(item.get("id") or f"R{index:03d}"),
                "startMs": start_ms,
                "endMs": end_ms,
            })
    return ranges


def detections_in_range(track: dict, start_ms: int, end_ms: int) -> list[dict]:
    return [
        detection
        for detection in track.get("detections") or []
        if start_ms <= int(detection.get("timeMs", 0)) <= end_ms
    ]


def main() -> int:
    payload = read_input()
    tracks_path = Path(payload.get("tracksPath") or "").expanduser().resolve()
    transcript_path = Path(payload.get("transcriptPath") or "").expanduser().resolve()
    if not tracks_path.exists():
        print(json.dumps({"ok": False, "error": "tracksPath does not exist"}, indent=2))
        return 1
    if not transcript_path.exists():
        print(json.dumps({"ok": False, "error": "transcriptPath does not exist"}, indent=2))
        return 1

    tracks = load_json(tracks_path).get("tracks") or []
    segments = transcript_segments(load_json(transcript_path))
    ranges = normalize_ranges(payload)
    source_width = float(payload.get("sourceWidth") or 1920)
    source_height = float(payload.get("sourceHeight") or 1080)
    source_aspect = source_width / max(1.0, source_height)
    max_words = int(payload.get("maxWordsOutput", 120))
    materials = []

    for range_index, range_item in enumerate(ranges, start=1):
        start_ms = int(range_item["startMs"])
        end_ms = int(range_item["endMs"])
        subtitle = bind_subtitles(start_ms, end_ms, segments, max_words)
        for track in tracks:
            label = str(track.get("label") or "")
            detections = detections_in_range(track, start_ms, end_ms)
            box = average_box(detections)
            if not label or box is None:
                continue
            material_id = f"M{len(materials) + 1:04d}"
            materials.append({
                "id": material_id,
                "kind": "face_crop",
                "rangeId": range_item["id"],
                "startMs": start_ms,
                "endMs": end_ms,
                "durationMs": end_ms - start_ms,
                "trackLabel": label,
                "cropRect": crop_for_face(box, source_aspect),
                "targetFaceBox": box,
                "subtitle": subtitle,
                "source": {
                    "type": "tracked_face",
                    "detectionTimesMs": [int(item.get("timeMs", 0)) for item in detections],
                },
            })

    result = {
        "ok": True,
        "schema": "wowclip.portrait-materials.v1",
        "rangeCount": len(ranges),
        "materialCount": len(materials),
        "materials": materials,
        "content": [
            {
                "type": "text",
                "text": f"[portrait_materials] {len(ranges)} ranges, {len(materials)} materials",
            }
        ],
    }
    output_path_raw = payload.get("outputPath") or ""
    if output_path_raw:
        output_path = Path(output_path_raw).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["outputPath"] = str(output_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
