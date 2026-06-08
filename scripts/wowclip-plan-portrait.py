#!/usr/bin/env python3
"""Create an engineered local portrait crop plan from face detections/tracks."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


def load_optional_json(path_raw: str) -> dict:
    if not path_raw:
        return {}
    path = Path(path_raw).expanduser().resolve()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def average_box(detections: list[dict]) -> dict | None:
    if not detections:
        return None
    sums = {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    for detection in detections:
        box = detection.get("box") or {}
        for key in sums:
            sums[key] += float(box.get(key, 0))
    return {key: sums[key] / len(detections) for key in sums}


def box_area(box: dict) -> float:
    return max(0.0, float(box.get("width", 0))) * max(0.0, float(box.get("height", 0)))


def face_visible_ratio(box: dict, crop_rect: dict) -> float:
    face_area = box_area(box)
    if face_area <= 0:
        return 0.0
    ax1 = float(box.get("x", 0))
    ay1 = float(box.get("y", 0))
    ax2 = ax1 + float(box.get("width", 0))
    ay2 = ay1 + float(box.get("height", 0))
    bx1 = float(crop_rect.get("x", 0))
    by1 = float(crop_rect.get("y", 0))
    bx2 = bx1 + float(crop_rect.get("width", 0))
    by2 = by1 + float(crop_rect.get("height", 0))
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    return (iw * ih) / face_area


def detections_in_range(track: dict, start_ms: int, end_ms: int) -> list[dict]:
    return [
        detection
        for detection in track.get("detections") or []
        if start_ms <= int(detection.get("timeMs", 0)) <= end_ms
    ]


def ranked_tracks_for_range(tracks: list[dict], start_ms: int, end_ms: int) -> list[tuple[dict, list[dict]]]:
    ranked = []
    for track in tracks:
        ds = detections_in_range(track, start_ms, end_ms)
        if not ds:
            continue
        ranked.append((track, ds))
    return sorted(ranked, key=lambda item: (-len(item[1]), str(item[0].get("label") or "")))


def select_track_for_range(tracks: list[dict], start_ms: int, end_ms: int) -> tuple[dict | None, list[dict]]:
    ranked = ranked_tracks_for_range(tracks, start_ms, end_ms)
    if ranked:
        return ranked[0]
    return None, []


def detection_centered_subranges(range_item: dict, detections: list[dict]) -> list[dict]:
    ordered = sorted(detections, key=lambda item: int(item.get("timeMs", 0)))
    if not ordered:
        return []
    range_start = int(range_item["startMs"])
    range_end = int(range_item["endMs"])
    subranges = []
    for index, detection in enumerate(ordered):
        detection_time = int(detection.get("timeMs", range_start))
        if index == 0:
            start_ms = range_start
        else:
            previous_time = int(ordered[index - 1].get("timeMs", detection_time))
            start_ms = (previous_time + detection_time) // 2
        if index == len(ordered) - 1:
            end_ms = range_end
        else:
            next_time = int(ordered[index + 1].get("timeMs", detection_time))
            end_ms = (detection_time + next_time) // 2
        start_ms = max(range_start, start_ms)
        end_ms = min(range_end, end_ms)
        if valid_range(start_ms, end_ms):
            subrange = dict(range_item)
            subrange["startMs"] = start_ms
            subrange["endMs"] = end_ms
            subrange["detection"] = detection
            subranges.append(subrange)
    return subranges


def hold_crop_range(
    range_item: dict,
    detections: list[dict],
    crop_rect: dict,
    visibility_threshold: float,
    check_interval_ms: int,
) -> tuple[int, int, list[str]]:
    ordered = sorted(detections, key=lambda item: int(item.get("timeMs", 0)))
    range_start = int(range_item["startMs"])
    range_end = int(range_item["endMs"])
    if not ordered:
        return range_start, range_start, []
    hold_start = max(range_start, int(ordered[0].get("timeMs", range_start)))
    cutoff = range_end
    warnings = []
    check_step_ms = max(1, int(check_interval_ms))
    last_check_time = int(ordered[0].get("timeMs", hold_start))
    next_check = last_check_time + check_step_ms
    for detection in ordered[1:]:
        detection_time = int(detection.get("timeMs", 0))
        if detection_time < next_check:
            continue
        ratio = face_visible_ratio(detection.get("box") or {}, crop_rect)
        if ratio < visibility_threshold:
            cutoff = max(hold_start, min(range_end, detection_time))
            warnings.append(f"face_left_crop:{detection_time}")
            break
        last_check_time = detection_time
        while next_check <= detection_time:
            next_check += check_step_ms
    if cutoff == range_end:
        last_detection = ordered[-1]
        last_time = int(last_detection.get("timeMs", range_end))
        if last_time > hold_start and last_time < range_end:
            ratio = face_visible_ratio(last_detection.get("box") or {}, crop_rect)
            if ratio < visibility_threshold:
                for detection in ordered:
                    detection_time = int(detection.get("timeMs", 0))
                    if detection_time <= last_check_time:
                        continue
                    ratio = face_visible_ratio(detection.get("box") or {}, crop_rect)
                    if ratio < visibility_threshold:
                        cutoff = max(hold_start, min(range_end, detection_time))
                        warnings.append(f"face_left_crop:{detection_time}")
                        break
    return hold_start, cutoff, warnings


def valid_range(start_ms: int, end_ms: int) -> bool:
    return end_ms > start_ms


def normalize_payload_ranges(payload: dict, detections: list[dict]) -> list[dict]:
    if isinstance(payload.get("ranges"), list) and payload["ranges"]:
        ranges = []
        for item in payload["ranges"]:
            start_ms = int(item.get("startMs", item.get("start", 0)))
            end_ms = int(item.get("endMs", item.get("end", start_ms + 1)))
            if valid_range(start_ms, end_ms):
                normalized = {"startMs": start_ms, "endMs": end_ms}
                if item.get("id"):
                    normalized["sourceRangeId"] = str(item["id"])
                ranges.append(normalized)
        if ranges:
            return ranges
    start_ms = int(payload.get("startMs") if payload.get("startMs") is not None else min([d.get("timeMs", 0) for d in detections] or [0]))
    end_ms = int(payload.get("endMs") if payload.get("endMs") is not None else max([d.get("timeMs", 0) for d in detections] or [0]) + 1000)
    return [{"startMs": start_ms, "endMs": max(start_ms + 1, end_ms)}]


def normalize_shots(shots_doc: dict) -> list[dict]:
    shots = []
    for index, shot in enumerate(shots_doc.get("shots") or [], start=1):
        start_ms = int(shot.get("startMs", shot.get("start", 0)))
        end_ms = int(shot.get("endMs", shot.get("end", start_ms)))
        if valid_range(start_ms, end_ms):
            shots.append({
                "id": str(shot.get("id") or f"shot-{index:04d}"),
                "startMs": start_ms,
                "endMs": end_ms,
            })
    return sorted(shots, key=lambda item: (item["startMs"], item["endMs"]))


def split_ranges_by_shots(ranges: list[dict], shots: list[dict]) -> list[dict]:
    if not shots:
        return ranges
    split = []
    for range_item in ranges:
        start_ms = int(range_item["startMs"])
        end_ms = int(range_item["endMs"])
        overlaps = []
        for shot in shots:
            overlap_start = max(start_ms, int(shot["startMs"]))
            overlap_end = min(end_ms, int(shot["endMs"]))
            if valid_range(overlap_start, overlap_end):
                item = dict(range_item)
                item["startMs"] = overlap_start
                item["endMs"] = overlap_end
                item["shotId"] = shot["id"]
                overlaps.append(item)
        split.extend(overlaps or [range_item])
    return split


def merge_adjacent_ranges_in_same_shot(ranges: list[dict], merge_gap_ms: int = 250) -> list[dict]:
    ordered = sorted(ranges, key=lambda item: (str(item.get("shotId") or ""), int(item["startMs"]), int(item["endMs"])))
    merged = []
    for range_item in ordered:
        if not merged:
            merged.append(dict(range_item))
            continue
        previous = merged[-1]
        same_shot = str(previous.get("shotId") or "") == str(range_item.get("shotId") or "")
        adjacent = int(range_item["startMs"]) <= int(previous["endMs"]) + int(merge_gap_ms)
        if same_shot and adjacent:
            previous["endMs"] = max(int(previous["endMs"]), int(range_item["endMs"]))
            if previous.get("sourceRangeId") and range_item.get("sourceRangeId"):
                previous["sourceRangeId"] = f"{previous['sourceRangeId']}+{range_item['sourceRangeId']}"
            continue
        merged.append(dict(range_item))
    return sorted(merged, key=lambda item: (int(item["startMs"]), int(item["endMs"])))


def plan_ranges(payload: dict, detections: list[dict], shots_doc: dict) -> list[dict]:
    ranges = normalize_payload_ranges(payload, detections)
    split = split_ranges_by_shots(ranges, normalize_shots(shots_doc))
    return merge_adjacent_ranges_in_same_shot(split, merge_gap_ms=int(payload.get("sameShotMergeGapMs", 250)))


def main() -> int:
    payload = read_input()
    detections_path_raw = payload.get("detectionsPath") or ""
    tracks_path_raw = payload.get("tracksPath") or ""
    detections_path = Path(detections_path_raw).expanduser().resolve() if detections_path_raw else None
    tracks_path = Path(tracks_path_raw).expanduser().resolve() if tracks_path_raw else None
    if detections_path is None and tracks_path is None:
        print(json.dumps({"ok": False, "error": "detectionsPath or tracksPath is required"}, indent=2))
        return 1
    if detections_path is not None and not detections_path.exists():
        print(json.dumps({"ok": False, "error": "detectionsPath does not exist"}, indent=2))
        return 1
    if tracks_path is not None and not tracks_path.exists():
        print(json.dumps({"ok": False, "error": "tracksPath does not exist"}, indent=2))
        return 1
    detections_doc = json.loads(detections_path.read_text(encoding="utf-8")) if detections_path else {}
    tracks_doc = json.loads(tracks_path.read_text(encoding="utf-8")) if tracks_path else {}
    shots_doc = load_optional_json(str(payload.get("shotsPath") or ""))
    embedded_doc = load_optional_json(str(payload.get("embeddedPortraitPath") or "")) or shots_doc
    embedded_portrait_detected = bool((embedded_doc.get("embeddedPortrait") or embedded_doc).get("detected"))
    detections = detections_doc.get("detections") or []
    tracks = tracks_doc.get("tracks") or []
    asset_id = payload.get("assetId") or detections_doc.get("assetId") or tracks_doc.get("assetId") or "A001"
    source_width = float(payload.get("sourceWidth") or detections_doc.get("sourceWidth") or 1920)
    source_height = float(payload.get("sourceHeight") or detections_doc.get("sourceHeight") or 1080)
    source_aspect = source_width / max(1.0, source_height)
    requested_portrait_mode = str(payload.get("portraitMode") or payload.get("mode") or "speaker_crop")
    auto_portrait_mode = requested_portrait_mode == "auto"
    portrait_mode = "speaker_crop"
    allowed_modes = {"speaker_crop", "auto"}
    if requested_portrait_mode not in allowed_modes:
        print(json.dumps({"ok": False, "error": f"portraitMode must be one of {sorted(allowed_modes)}"}, indent=2))
        return 1
    warnings = []
    planned_ranges = []
    visibility_threshold = float(payload.get("faceVisibilityThreshold", 0.80))
    check_interval_ms = int(payload.get("cropCheckIntervalMs", 3000))
    for range_item in plan_ranges(payload, detections, shots_doc):
        start_ms = range_item["startMs"]
        end_ms = range_item["endMs"]
        shot_id = str(range_item.get("shotId") or "")
        selected_track, selected_detections = select_track_for_range(tracks, start_ms, end_ms)
        if selected_track:
            if not selected_detections:
                warnings.append(f"no_face_material:{start_ms}-{end_ms}")
                continue
            person_label = selected_track.get("label", "")
            if len(selected_detections) < 2:
                warnings.append(f"low_face_sample_count:{person_label}:{start_ms}-{end_ms}")
            first_detection = sorted(selected_detections, key=lambda item: int(item.get("timeMs", 0)))[0]
            crop_rect = crop_for_face(first_detection.get("box") or {}, source_aspect)
            hold_start, cutoff, hold_warnings = hold_crop_range(
                range_item,
                selected_detections,
                crop_rect,
                visibility_threshold,
                check_interval_ms,
            )
            for warning in hold_warnings:
                if warning.startswith("face_left_crop:"):
                    warnings.append(f"face_left_crop:{person_label}:{warning.split(':', 1)[1]}")
                else:
                    warnings.append(warning)
            if not valid_range(hold_start, cutoff):
                warnings.append(f"no_stable_face_crop:{person_label}:{start_ms}-{end_ms}")
                continue
            planned_range = {
                "startMs": hold_start,
                "endMs": max(hold_start + 1, cutoff),
                "portraitMode": portrait_mode,
                "selectedPersonLabel": person_label,
                "reason": "tracked_face_hold_crop",
                "cropRect": crop_rect,
            }
            if shot_id:
                planned_range["shotId"] = shot_id
            planned_ranges.append(planned_range)
            continue
        else:
            faces = []
            for item in detections:
                time_ms = int(item.get("timeMs", 0))
                if not (start_ms <= time_ms <= end_ms):
                    continue
                for face in item.get("faces") or []:
                    faces.append(face)
            if not faces:
                warnings.append(f"no_face_material:{start_ms}-{end_ms}")
                continue
            best_face = sorted(
                faces,
                key=lambda face: -float((face.get("box") or {}).get("width", 0)) * float((face.get("box") or {}).get("height", 0)),
            )[0]
            crop_rect = crop_for_face(best_face["box"], source_aspect)
            reason = "untracked_face_center_crop"
            person_label = "untracked"
            warnings.append(f"untracked_face_material:{start_ms}-{end_ms}")
        planned_range = {
            "startMs": start_ms,
            "endMs": max(start_ms + 1, end_ms),
            "portraitMode": portrait_mode,
            "selectedPersonLabel": person_label,
            "reason": reason,
            "cropRect": crop_rect,
        }
        if shot_id:
            planned_range["shotId"] = shot_id
        planned_ranges.append(planned_range)

    plan = {
        "schema": "wowclip.portrait-plan.v1",
        "assetId": asset_id,
        "target": {"width": int(payload.get("targetWidth") or 1080), "height": int(payload.get("targetHeight") or 1920), "aspectRatio": "9:16"},
        "ranges": planned_ranges,
        "warnings": warnings,
        "analysis": {
            "sourceWidth": source_width,
            "sourceHeight": source_height,
            "trackCount": len(tracks),
            "detectionFrameCount": len(detections),
            "planner": "tracked_face_hold_v1",
            "portraitMode": portrait_mode,
            "requestedPortraitMode": requested_portrait_mode,
            "faceVisibilityThreshold": visibility_threshold,
            "cropCheckIntervalMs": check_interval_ms,
            "shotCount": len(normalize_shots(shots_doc)),
            "embeddedPortraitDetected": embedded_portrait_detected,
            "embeddedPortraitUsed": False,
        }
    }
    base_dir = tracks_path.parent.parent if tracks_path else detections_path.parent.parent
    output_path = Path(payload.get("outputPath") or (base_dir / "plans" / "portrait" / "plan.json")).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "outputPath": str(output_path), "plan": plan}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
