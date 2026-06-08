#!/usr/bin/env python3
"""Inspect a portrait crop plan against face tracks without scoring it."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def inside_ratio(box: dict, crop: dict) -> float:
    bx1, by1 = float(box["x"]), float(box["y"])
    bx2, by2 = bx1 + float(box["width"]), by1 + float(box["height"])
    cx1, cy1 = float(crop["x"]), float(crop["y"])
    cx2, cy2 = cx1 + float(crop["width"]), cy1 + float(crop["height"])
    ix1, iy1 = max(bx1, cx1), max(by1, cy1)
    ix2, iy2 = min(bx2, cx2), min(by2, cy2)
    area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    return inter / area if area > 0 else 0.0


def main() -> int:
    payload = read_input()
    plan_path = Path(payload.get("portraitPlanPath") or payload.get("planPath") or "").expanduser().resolve()
    tracks_path = Path(payload.get("tracksPath") or "").expanduser().resolve()
    if not plan_path.exists():
        print(json.dumps({"ok": False, "error": "portraitPlanPath does not exist"}, indent=2))
        return 1
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    tracks_doc = json.loads(tracks_path.read_text(encoding="utf-8")) if tracks_path.exists() else {"tracks": []}
    tracks_by_label = {track.get("label"): track for track in tracks_doc.get("tracks") or []}
    warnings = []
    inspected_ranges = []

    for range_item in plan.get("ranges") or []:
        label = range_item.get("selectedPersonLabel")
        crop = range_item.get("cropRect") or {}
        track = tracks_by_label.get(label)
        face_samples = []
        if track:
            for detection in track.get("detections") or []:
                time_ms = int(detection.get("timeMs", 0))
                if int(range_item["startMs"]) <= time_ms <= int(range_item["endMs"]):
                    face_samples.append({
                        "timeMs": time_ms,
                        "box": detection.get("box") or {},
                        "insideRatio": inside_ratio(detection.get("box") or {}, crop),
                    })
        if float(crop.get("width", 0)) <= 0 or float(crop.get("height", 0)) <= 0:
            warnings.append("invalid_crop_size")
        if float(crop.get("x", 0)) < -0.0001 or float(crop.get("y", 0)) < -0.0001:
            warnings.append("crop_negative_origin")
        if float(crop.get("x", 0)) + float(crop.get("width", 0)) > 1.0001:
            warnings.append("crop_x_out_of_bounds")
        if float(crop.get("y", 0)) + float(crop.get("height", 0)) > 1.0001:
            warnings.append("crop_y_out_of_bounds")
        if label and not track:
            warnings.append(f"missing_track:{label}:{range_item['startMs']}-{range_item['endMs']}")
        inspected_ranges.append({
            "startMs": range_item["startMs"],
            "endMs": range_item["endMs"],
            "personLabel": label or "",
            "cropRect": crop,
            "faceSampleCount": len(face_samples),
            "faceSamples": face_samples,
        })

    print(json.dumps({
        "ok": True,
        "schema": "wowclip.crop-inspection.v1",
        "ranges": inspected_ranges,
        "warnings": sorted(set(warnings)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
