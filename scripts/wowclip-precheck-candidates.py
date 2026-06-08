#!/usr/bin/env python3
"""Precheck subtitle-selected clip candidates before portrait crop planning."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def in_range(time_ms: int, start_ms: int, end_ms: int) -> bool:
    return start_ms <= time_ms <= end_ms


def face_stats(candidate: dict, detections: list[dict]) -> dict:
    start_ms = int(candidate["startMs"])
    end_ms = int(candidate["endMs"])
    samples = [
        item for item in detections
        if in_range(int(item.get("timeMs", 0)), start_ms, end_ms)
    ]
    face_count = sum(len(item.get("faces") or []) for item in samples)
    largest = 0.0
    for item in samples:
        for face in item.get("faces") or []:
            box = face.get("box") or {}
            largest = max(largest, float(box.get("width", 0)) * float(box.get("height", 0)))
    sample_ratio = len(samples) / max(1, min(12, max(1, (end_ms - start_ms) // 3000)))
    face_score = min(1.0, largest * 12.0 + min(1.0, face_count / max(1, len(samples))) * 0.5) if samples else 0.0
    return {"sampleCount": len(samples), "faceCount": face_count, "largestFaceArea": largest, "sampleRatio": sample_ratio, "faceScore": round(face_score, 4)}


def main() -> int:
    payload = read_input()
    candidates_path = Path(payload.get("candidatesPath") or "").expanduser().resolve()
    if not candidates_path.exists():
        print(json.dumps({"ok": False, "error": "candidatesPath does not exist"}, indent=2))
        return 1
    candidates_doc = json.loads(candidates_path.read_text(encoding="utf-8"))
    detections_path_raw = payload.get("detectionsPath") or ""
    detections = []
    if detections_path_raw:
        detections_path = Path(detections_path_raw).expanduser().resolve()
        if detections_path.exists():
            detections = json.loads(detections_path.read_text(encoding="utf-8")).get("detections") or []
    min_score = float(payload.get("minScore", 0.45))
    checks = []
    warnings = []
    for candidate in candidates_doc.get("candidates") or []:
        stats = face_stats(candidate, detections)
        subtitle_score = 1.0 if candidate.get("hasWordTimestamps") else 0.45
        visual_score = stats["faceScore"] if detections else 0.55
        score = round(visual_score * 0.55 + subtitle_score * 0.35 + float(candidate.get("score", 0)) * 0.1, 4)
        candidate_warnings = []
        if not candidate.get("hasWordTimestamps"):
            candidate_warnings.append("missing_word_timestamps")
        if detections and stats["faceCount"] == 0:
            candidate_warnings.append("no_face_samples")
        if candidate.get("durationMs", 0) < int(payload.get("minDurationMs", 8000)):
            candidate_warnings.append("candidate_too_short")
        warnings.extend([f"{candidate['id']}:{warning}" for warning in candidate_warnings])
        checks.append({
            "id": candidate["id"],
            "startMs": candidate["startMs"],
            "endMs": candidate["endMs"],
            "text": candidate.get("text", ""),
            "score": score,
            "visual": stats,
            "warnings": candidate_warnings,
            "ok": score >= min_score and "missing_word_timestamps" not in candidate_warnings,
        })
    accepted = [item for item in checks if item["ok"]]
    result = {
        "schema": "wowclip.candidate-precheck.v1",
        "ok": bool(accepted),
        "acceptedCount": len(accepted),
        "checks": checks,
        "warnings": sorted(set(warnings)),
    }
    output_path_raw = payload.get("outputPath") or ""
    if output_path_raw:
        output_path = Path(output_path_raw).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["outputPath"] = str(output_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
