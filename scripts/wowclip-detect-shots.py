#!/usr/bin/env python3
"""Detect shot boundaries and embedded portrait content from sampled frames."""

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


def frame_time(frame: dict) -> int:
    return int(frame.get("timeMs", round(float(frame.get("timeSec", 0)) * 1000)))


def cut_confidence_for_frame(frame: dict) -> float:
    visual = float(frame.get("visualDiff", 0))
    histogram = float(frame.get("histogramDiff", 0))
    perceptual_hash = float(frame.get("hashDiff", 0))
    edge = float(frame.get("edgeDiff", 0))
    metrics = [visual, histogram, perceptual_hash, edge]
    supporting = sum([
        visual >= 0.30,
        histogram >= 0.35,
        perceptual_hash >= 0.30,
        edge >= 0.30,
    ])
    if supporting < 2:
        return round(min(0.54, 0.25 * supporting + 0.60 * max(metrics) + 0.30 * (sum(metrics) / len(metrics))), 4)
    return round(min(1.0, 0.25 * supporting + 0.60 * max(metrics) + 0.30 * (sum(metrics) / len(metrics))), 4)


def score_cut_confidence(frames: list[dict]) -> list[dict]:
    scored = []
    for frame in frames:
        item = dict(frame)
        item["cutConfidence"] = cut_confidence_for_frame(item)
        item["cutEvidence"] = {
            "visualDiff": float(item.get("visualDiff", 0)),
            "histogramDiff": float(item.get("histogramDiff", 0)),
            "hashDiff": float(item.get("hashDiff", 0)),
            "edgeDiff": float(item.get("edgeDiff", 0)),
        }
        scored.append(item)
    return scored


def is_hard_cut(frame: dict, threshold: float, confidence_threshold: float) -> bool:
    visual_diff = float(frame.get("visualDiff", 0))
    confidence = frame.get("cutConfidence")
    return visual_diff >= threshold or (confidence is not None and float(confidence) >= confidence_threshold)


def add_cut_metadata(shot: dict, frame: dict) -> dict:
    if "cutConfidence" in frame:
        shot["confidence"] = float(frame["cutConfidence"])
        shot["kind"] = "hard_cut"
        if frame.get("cutEvidence"):
            shot["evidence"] = frame["cutEvidence"]
        if frame.get("previousPath") and frame.get("path"):
            shot["evidenceFrames"] = {"before": frame["previousPath"], "after": frame["path"]}
    return shot


def shots_from_scored_frames(
    frames: list[dict],
    end_ms: int,
    threshold: float = 0.42,
    min_duration_ms: int = 700,
    confidence_threshold: float = 0.80,
) -> list[dict]:
    ordered = sorted(frames, key=frame_time)
    if not ordered:
        return []
    shots = []
    shot_start = frame_time(ordered[0])
    shot_frame_count = 0
    for frame in ordered:
        time_ms = frame_time(frame)
        if shot_frame_count > 0 and is_hard_cut(frame, threshold, confidence_threshold) and time_ms - shot_start >= min_duration_ms:
            shot = add_cut_metadata({
                "id": f"shot-{len(shots) + 1:04d}",
                "startMs": shot_start,
                "endMs": time_ms,
                "frameCount": shot_frame_count,
            }, frame)
            shots.append(shot)
            shot_start = time_ms
            shot_frame_count = 0
        shot_frame_count += 1
    final_end = max(frame_time(ordered[-1]) + 1, int(end_ms))
    shots.append({
        "id": f"shot-{len(shots) + 1:04d}",
        "startMs": shot_start,
        "endMs": final_end,
        "frameCount": shot_frame_count,
    })
    return shots


def average_hash(gray_image) -> list[int]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return []
    small = cv2.resize(gray_image, (16, 16))
    threshold = float(np.mean(small))
    return [1 if float(value) >= threshold else 0 for value in small.flatten()]


def hamming_distance(a: list[int], b: list[int]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(1 for left, right in zip(a, b) if left != right) / len(a)


def compute_frame_metrics(previous_path: str, current_path: str) -> dict:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return {"visualDiff": 0.0, "histogramDiff": 0.0, "hashDiff": 0.0, "edgeDiff": 0.0}
    previous = cv2.imread(previous_path)
    current = cv2.imread(current_path)
    if previous is None or current is None:
        return {"visualDiff": 0.0, "histogramDiff": 0.0, "hashDiff": 0.0, "edgeDiff": 0.0}
    size = (96, 54)
    previous_small = cv2.resize(previous, size)
    current_small = cv2.resize(current, size)
    visual_delta = np.mean(np.abs(previous_small.astype("float32") - current_small.astype("float32"))) / 255.0

    previous_hsv = cv2.cvtColor(previous_small, cv2.COLOR_BGR2HSV)
    current_hsv = cv2.cvtColor(current_small, cv2.COLOR_BGR2HSV)
    previous_hist = cv2.calcHist([previous_hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    current_hist = cv2.calcHist([current_hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(previous_hist, previous_hist)
    cv2.normalize(current_hist, current_hist)
    histogram_delta = 1.0 - float(cv2.compareHist(previous_hist, current_hist, cv2.HISTCMP_CORREL))

    previous_gray = cv2.cvtColor(previous_small, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.cvtColor(current_small, cv2.COLOR_BGR2GRAY)
    hash_delta = hamming_distance(average_hash(previous_gray), average_hash(current_gray))

    previous_edges = cv2.Canny(previous_gray, 80, 160)
    current_edges = cv2.Canny(current_gray, 80, 160)
    edge_delta = np.mean(np.abs(previous_edges.astype("float32") - current_edges.astype("float32"))) / 255.0

    return {
        "visualDiff": float(max(0.0, min(1.0, visual_delta))),
        "histogramDiff": float(max(0.0, min(1.0, histogram_delta))),
        "hashDiff": float(max(0.0, min(1.0, hash_delta))),
        "edgeDiff": float(max(0.0, min(1.0, edge_delta))),
    }


def compute_frame_diff(previous_path: str, current_path: str) -> float:
    return compute_frame_metrics(previous_path, current_path)["visualDiff"]


def score_frames(frames: list[dict]) -> list[dict]:
    ordered = sorted(frames, key=frame_time)
    scored = []
    previous_path = ""
    for frame in ordered:
        item = dict(frame)
        path = str(item.get("path") or "")
        if previous_path and path:
            metrics = compute_frame_metrics(previous_path, path)
        else:
            metrics = {"visualDiff": 0.0, "histogramDiff": 0.0, "hashDiff": 0.0, "edgeDiff": 0.0}
        for key, value in metrics.items():
            item[key] = float(item.get(key, value))
        item["previousPath"] = previous_path
        scored.append(item)
        if path:
            previous_path = path
    return score_cut_confidence(scored)


def dense_source_frames(manifest: dict, payload: dict, output_dir: Path) -> list[dict]:
    source_path = Path(manifest.get("sourcePath") or payload.get("sourcePath") or "").expanduser().resolve()
    if not source_path.exists() or payload.get("denseSourceScan") is False:
        return []
    try:
        import cv2  # type: ignore
    except Exception:
        return []
    scan_fps = float(payload.get("denseScanFps", 4.0))
    if scan_fps <= 0:
        return []
    source_range = manifest.get("range") or {}
    start_ms = int(payload.get("startMs", source_range.get("startMs", 0)))
    end_ms = int(payload.get("endMs", source_range.get("endMs", start_ms)))
    if end_ms <= start_ms:
        return []
    max_frames = int(payload.get("maxDenseFrames", 1200))
    interval_ms = max(1, int(round(1000 / scan_fps)))
    times = list(range(start_ms, end_ms + 1, interval_ms))
    if len(times) > max_frames:
        step = max(1, len(times) // max_frames)
        times = times[::step][:max_frames]
    frames_dir = output_dir / "dense"
    frames_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source_path))
    frames = []
    max_width = int(payload.get("denseMaxWidth", 480))
    for time_ms in times:
        capture.set(cv2.CAP_PROP_POS_MSEC, float(time_ms))
        ok, image = capture.read()
        if not ok or image is None:
            continue
        height, width = image.shape[:2]
        if width > max_width:
            scale = max_width / width
            image = cv2.resize(image, (max_width, max(1, int(round(height * scale)))))
        path = frames_dir / f"frame-{time_ms:010d}.jpg"
        cv2.imwrite(str(path), image)
        frames.append({"timeMs": time_ms, "timeSec": round(time_ms / 1000, 3), "path": str(path), "sample": "dense_source"})
    capture.release()
    return frames


def detect_embedded_portrait(frames: list[dict]) -> dict:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return {"detected": False, "confidence": 0.0, "reason": "opencv_unavailable"}
    candidates = []
    for frame in frames:
        path = str(frame.get("path") or "")
        image = cv2.imread(path)
        if image is None:
            continue
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            continue
        target_width = int(round(height * 9 / 16))
        if target_width <= 0 or target_width >= width:
            continue
        x = int(round((width - target_width) / 2))
        left = image[:, :max(1, x)]
        right = image[:, min(width, x + target_width):]
        if left.size == 0 or right.size == 0:
            continue
        side_std = float((np.std(left) + np.std(right)) / 2.0)
        center_std = float(np.std(image[:, x:x + target_width]))
        side_similarity = 1.0 - min(1.0, abs(float(np.mean(left)) - float(np.mean(right))) / 255.0)
        confidence = 0.0
        if center_std > 8:
            confidence = min(1.0, max(0.0, side_similarity * 0.45 + min(1.0, side_std / max(1.0, center_std)) * 0.25 + 0.25))
        candidates.append({
            "x": x / width,
            "y": 0.0,
            "width": target_width / width,
            "height": 1.0,
            "confidence": confidence,
        })
    if not candidates:
        return {"detected": False, "confidence": 0.0, "reason": "no_usable_frames"}
    avg_confidence = sum(item["confidence"] for item in candidates) / len(candidates)
    avg_x = sum(item["x"] for item in candidates) / len(candidates)
    avg_width = sum(item["width"] for item in candidates) / len(candidates)
    detected = avg_confidence >= 0.55 and 0.25 <= avg_x <= 0.45 and 0.22 <= avg_width <= 0.42
    return {
        "detected": bool(detected),
        "confidence": round(avg_confidence, 4),
        "cropRect": {"x": avg_x, "y": 0.0, "width": avg_width, "height": 1.0},
        "reason": "central_9x16_content_candidate",
        "sampleCount": len(candidates),
    }


def main() -> int:
    payload = read_input()
    manifest_path = Path(payload.get("manifestPath") or payload.get("framesManifestPath") or "").expanduser().resolve()
    if not manifest_path.exists():
        print(json.dumps({"ok": False, "error": "manifestPath does not exist"}, indent=2))
        return 1
    manifest = load_json(manifest_path)
    output_path = Path(payload.get("outputPath") or manifest_path.parent / "shots.json").expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dense_frames = dense_source_frames(manifest, payload, output_path.parent)
    raw_frames = dense_frames or manifest.get("frames") or []
    scored_frames = score_frames(raw_frames)
    if payload.get("endMs") is not None:
        end_ms = int(payload["endMs"])
    elif scored_frames:
        end_ms = frame_time(scored_frames[-1]) + int(payload.get("tailMs", 1000))
    else:
        end_ms = 0
    shots = shots_from_scored_frames(
        scored_frames,
        end_ms=end_ms,
        threshold=float(payload.get("threshold", 0.42)),
        min_duration_ms=int(payload.get("minDurationMs", 700)),
    )
    embedded = detect_embedded_portrait(scored_frames)
    result = {
        "schema": "wowclip.shots.v1",
        "manifestPath": str(manifest_path),
        "shots": shots,
        "frames": scored_frames,
        "analysis": {
            "detector": "dense_multi_feature_v1" if dense_frames else "manifest_multi_feature_v1",
            "denseFrameCount": len(dense_frames),
            "denseFramesDir": str(output_path.parent / "dense") if dense_frames else "",
            "sourceFrameCount": len(manifest.get("frames") or []),
        },
        "embeddedPortrait": embedded,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "outputPath": str(output_path),
        "shotCount": len(shots),
        "denseFramesDir": str(output_path.parent / "dense") if dense_frames else "",
        "denseFrameCount": len(dense_frames),
        "embeddedPortrait": embedded,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
