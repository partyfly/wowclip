#!/usr/bin/env python3
"""Build a standard WowClip EDL from a clip plan, subtitles, and portrait plan."""

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


def load_engineered_subtitles(payload: dict, project_root: Path, source_path: Path) -> list[dict]:
    transcript_path_raw = payload.get("transcriptPath") or project_root / "transcripts" / f"{source_path.stem}.json"
    transcript_path = Path(transcript_path_raw).expanduser().resolve()
    if not transcript_path.exists():
        return []
    transcript = load_json(transcript_path)
    entries = transcript.get("engineeredSubtitles") or transcript.get("subtitles") or []
    normalized = []
    for index, entry in enumerate(entries, start=1):
        start_ms = int(entry.get("startMs", round(float(entry.get("start", 0)) * 1000)))
        end_ms = int(entry.get("endMs", round(float(entry.get("end", 0)) * 1000)))
        text = str(entry.get("text") or "").strip()
        if text and end_ms > start_ms:
            normalized.append({"id": entry.get("id") or f"sub-src-{index:04d}", "startMs": start_ms, "endMs": end_ms, "text": text})
    return normalized


def load_highlight_plan(payload: dict) -> dict | None:
    if isinstance(payload.get("highlightPlan"), dict):
        return payload["highlightPlan"]
    path_raw = payload.get("highlightPlanPath") or ""
    if not path_raw:
        return None
    path = Path(path_raw).expanduser().resolve()
    return load_json(path) if path.exists() else None


def selected_clip_plan(highlight_plan: dict | None, selected_id: str | None) -> dict | None:
    if not highlight_plan:
        return None
    clip_plans = highlight_plan.get("clipPlans") or []
    if not clip_plans:
        return None
    if selected_id:
        for clip_plan in clip_plans:
            if str(clip_plan.get("id")) == selected_id:
                return clip_plan
    return clip_plans[0]


def segments_from_plan(clip_plan: dict | None, portrait_plan: dict) -> list[dict]:
    if clip_plan:
        segments = []
        for index, segment in enumerate(clip_plan.get("segments") or [], start=1):
            start_ms = int(segment.get("startMs", 0))
            end_ms = int(segment.get("endMs", start_ms))
            if end_ms <= start_ms:
                continue
            segments.append({
                "index": index,
                "startMs": start_ms,
                "endMs": end_ms,
                "role": segment.get("role") or "body",
                "actions": segment.get("actions") or [],
                "highlightId": segment.get("highlightId") or "",
                "reason": segment.get("reason") or "",
            })
        return segments
    return [
        {
            "index": index,
            "startMs": int(item["startMs"]),
            "endMs": int(item["endMs"]),
            "role": "body",
            "actions": ["keep_context"],
            "highlightId": "",
            "reason": item.get("reason") or "",
        }
        for index, item in enumerate(portrait_plan.get("ranges") or [], start=1)
    ]


def portrait_range_for_segment(segment: dict, ranges: list[dict]) -> dict:
    start_ms = int(segment["startMs"])
    end_ms = int(segment["endMs"])
    for item in ranges:
        if int(item.get("startMs", -1)) == start_ms and int(item.get("endMs", -1)) == end_ms:
            return item
    for item in ranges:
        if int(item.get("startMs", -1)) <= start_ms and int(item.get("endMs", -1)) >= end_ms:
            return item
    return {"startMs": start_ms, "endMs": end_ms, "portraitMode": "speaker_crop", "cropRect": None, "reason": "missing_portrait_range"}


def portrait_overlaps_for_segment(segment: dict, ranges: list[dict]) -> list[dict]:
    start_ms = int(segment["startMs"])
    end_ms = int(segment["endMs"])
    overlaps = []
    for item in sorted(ranges, key=lambda range_item: (int(range_item.get("startMs", 0)), int(range_item.get("endMs", 0)))):
        overlap_start = max(start_ms, int(item.get("startMs", 0)))
        overlap_end = min(end_ms, int(item.get("endMs", 0)))
        if overlap_end <= overlap_start:
            continue
        overlapped = dict(item)
        overlapped["startMs"] = overlap_start
        overlapped["endMs"] = overlap_end
        overlaps.append(overlapped)
    if overlaps:
        return overlaps
    return []


def main() -> int:
    payload = read_input()
    source_path = Path(payload.get("sourcePath") or "").expanduser().resolve()
    plan_path = Path(payload.get("portraitPlanPath") or payload.get("planPath") or "").expanduser().resolve()
    clip_check_path_raw = payload.get("clipCheckPath") or ""
    if not source_path.exists():
        print(json.dumps({"ok": False, "error": "sourcePath does not exist"}, indent=2))
        return 1
    if not plan_path.exists():
        print(json.dumps({"ok": False, "error": "portraitPlanPath does not exist"}, indent=2))
        return 1
    project_root = Path(payload.get("projectRootDir") or plan_path.parent.parent.parent).expanduser().resolve()
    plan = load_json(plan_path)
    clip_check = load_json(Path(clip_check_path_raw).expanduser().resolve()) if clip_check_path_raw else {"rangeChecks": []}
    engineered_subtitles = load_engineered_subtitles(payload, project_root, source_path)
    highlight_plan = load_highlight_plan(payload)
    clip_plan = selected_clip_plan(highlight_plan, payload.get("selectedClipPlanId") or payload.get("clipPlanId"))
    source_asset_id = (highlight_plan or {}).get("sourceAssetId") or plan.get("assetId") or "A001"
    check_items = clip_check.get("rangeChecks") or clip_check.get("clips") or []
    checks_by_range = {
        (int(item["startMs"]), int(item["endMs"])): item
        for item in check_items
    }
    target = plan.get("target") or {"width": 1080, "height": 1920}
    asset_id = source_asset_id
    duration = 0
    video_clips = []
    audio_clips = []
    subtitle_clips = []
    segments = segments_from_plan(clip_plan, plan)
    portrait_ranges = plan.get("ranges") or []
    media_index = 1
    for segment in segments:
        start_ms = int(segment["startMs"])
        end_ms = int(segment["endMs"])
        check = checks_by_range.get((start_ms, end_ms), {})
        subtitle_binding = check.get("subtitleBinding") or check.get("subtitle") or {}
        for range_item in portrait_overlaps_for_segment(segment, portrait_ranges):
            clip_start_ms = int(range_item["startMs"])
            clip_end_ms = int(range_item["endMs"])
            clip_duration = clip_end_ms - clip_start_ms
            dst_start = duration
            dst_end = duration + clip_duration
            video_clips.append({
                "id": f"clip-{media_index:04d}",
                "kind": "media",
                "assetId": asset_id,
                "dstStart": dst_start,
                "dstEnd": dst_end,
                "srcIn": clip_start_ms,
                "srcOut": clip_end_ms,
                "placement": {
                    "fit": "cover",
                    "mode": "portrait_reframe",
                    "portraitMode": range_item.get("portraitMode") or "speaker_crop",
                    "targetWidth": int(target.get("width", 1080)),
                    "targetHeight": int(target.get("height", 1920)),
                    "cropRect": range_item.get("cropRect"),
                    "layout": range_item.get("layout") or None,
                    "personLabel": range_item.get("selectedPersonLabel") or "",
                    "confidence": float(range_item.get("confidence", 0)),
                    "reason": range_item.get("reason") or "",
                },
                "label": f"{segment.get('role', 'body')} {segment.get('highlightId', '')}".strip(),
                "params": {
                    "role": segment.get("role") or "body",
                    "actions": segment.get("actions") or [],
                    "highlightId": segment.get("highlightId") or "",
                    "clipPlanId": (clip_plan or {}).get("id") or "",
                },
                "subtitleBinding": subtitle_binding,
            })
            audio_clips.append({
                "id": f"audio-{media_index:04d}",
                "kind": "media",
                "assetId": asset_id,
                "dstStart": dst_start,
                "dstEnd": dst_end,
                "srcIn": clip_start_ms,
                "srcOut": clip_end_ms,
                "volume": 1.0,
            })
            subtitle_index_start = len(subtitle_clips) + 1
            for subtitle in engineered_subtitles:
                overlap_start = max(int(subtitle["startMs"]), clip_start_ms)
                overlap_end = min(int(subtitle["endMs"]), clip_end_ms)
                if overlap_end <= overlap_start:
                    continue
                subtitle_clips.append({
                    "id": f"sub-{len(subtitle_clips) + 1:04d}",
                    "kind": "subtitle",
                    "dstStart": dst_start + (overlap_start - clip_start_ms),
                    "dstEnd": dst_start + (overlap_end - clip_start_ms),
                    "text": subtitle["text"],
                    "styleOverride": payload.get("subtitleStyle") or {},
                })
            if len(subtitle_clips) == subtitle_index_start - 1:
                subtitle_text = subtitle_binding.get("subtitleText") or subtitle_binding.get("text") or ""
                if subtitle_text:
                    subtitle_clips.append({
                        "id": f"sub-{len(subtitle_clips) + 1:04d}",
                        "kind": "subtitle",
                        "dstStart": dst_start,
                        "dstEnd": dst_end,
                        "text": subtitle_text,
                        "styleOverride": payload.get("subtitleStyle") or {},
                    })
            duration = dst_end
            media_index += 1
    canvas = {
        "width": int(target.get("width", 1080)),
        "height": int(target.get("height", 1920)),
        "aspect": target.get("aspectRatio") or target.get("aspect") or "9:16",
    }
    project_id = str(payload.get("projectId") or project_root.name or "wowclip-project")
    project_name = str(payload.get("projectName") or project_id)
    edl = {
        "kind": "wowclip.timeline.v1",
        "schemaVersion": 2,
        "version": 0,
        "project": {"id": project_id, "name": project_name},
        "projectId": project_id,
        "assets": {
            asset_id: {
                "id": asset_id,
                "type": "video",
                "name": source_path.name,
                "sourcePath": str(source_path),
                "durationMs": int(payload.get("sourceDurationMs", 0)),
                "width": int(payload.get("sourceWidth", 0)),
                "height": int(payload.get("sourceHeight", 0)),
            }
        },
        "timebase": {"fps": int(payload.get("fps", 30)), "ticksPerSecond": 1000, "tcStartTicks": 0},
        "timeline": {
            "durationTicks": duration,
            "playheadTicks": 0,
            "tracks": [
                {"id": "V1", "type": "video", "role": "primary", "label": "V1 Main Video", "clips": video_clips},
                {"id": "A1", "type": "audio", "role": "voice", "label": "A1 Original Audio", "clips": audio_clips},
                {"id": "S1", "type": "subtitle", "role": "subtitle", "label": "S1 Subtitles", "clips": subtitle_clips},
            ],
        },
        "analysis": {
            "portraitMode": payload.get("portraitMode") or plan.get("portraitMode") or "",
            "sourceTranscriptPath": payload.get("transcriptPath") or "",
            "highlightPlanPath": payload.get("highlightPlanPath") or "",
            "selectedClipPlanId": (clip_plan or {}).get("id") or "",
        },
        "artifacts": {
            "portraitPlanPath": str(plan_path),
            "clipCheckPath": str(Path(clip_check_path_raw).expanduser().resolve()) if clip_check_path_raw else "",
            "highlightPlanPath": str(Path(payload.get("highlightPlanPath")).expanduser().resolve()) if payload.get("highlightPlanPath") else "",
        },
        "ui": {"canvas": canvas},
    }
    output_path = Path(payload.get("outputPath") or project_root / "edl.json").expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "edlPath": str(output_path),
        "clipCount": len(video_clips),
        "subtitleClipCount": len(subtitle_clips),
        "selectedClipPlanId": (clip_plan or {}).get("id") or "",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
