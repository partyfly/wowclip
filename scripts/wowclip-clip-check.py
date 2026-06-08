#!/usr/bin/env python3
"""Inspect planned clip ranges and bind them to source subtitles."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def join_words(words: list[dict]) -> str:
    tokens = [str(word["word"]).strip() for word in words if str(word.get("word", "")).strip()]
    if not tokens:
        return ""
    if any(has_cjk(token) for token in tokens):
        return "".join(tokens)
    return " ".join(tokens)


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def overlap_ms(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def transcript_segments(transcript_doc: dict) -> list[dict]:
    segments = transcript_doc.get("segments") or transcript_doc.get("items") or []
    normalized = []
    for index, segment in enumerate(segments, start=1):
        start_ms = int(segment.get("startMs", round(float(segment.get("start", 0)) * 1000)))
        end_ms = int(segment.get("endMs", round(float(segment.get("end", 0)) * 1000)))
        text = str(segment.get("text", "")).strip()
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


def bind_subtitles(range_item: dict, segments: list[dict], max_words: int) -> dict:
    start_ms = int(range_item["startMs"])
    end_ms = int(range_item["endMs"])
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

    subtitle_text = join_words(overlapping_words) if overlapping_words else " ".join(segment["text"] for segment in overlapping_segments).strip()

    return {
        "text": subtitle_text,
        "segments": overlapping_segments,
        "words": overlapping_words[:max_words],
        "wordCount": len(overlapping_words),
        "hasWordTimestamps": bool(overlapping_words),
        "truncatedWords": max(0, len(overlapping_words) - max_words),
    }


def crop_warnings(range_item: dict) -> list[str]:
    warnings = []
    crop = range_item.get("cropRect") or {}
    if float(crop.get("width", 0)) <= 0 or float(crop.get("height", 0)) <= 0:
        warnings.append("invalid_crop_size")
    if float(crop.get("x", 0)) < -0.0001 or float(crop.get("y", 0)) < -0.0001:
        warnings.append("crop_negative_origin")
    if float(crop.get("x", 0)) + float(crop.get("width", 0)) > 1.0001:
        warnings.append("crop_x_out_of_bounds")
    if float(crop.get("y", 0)) + float(crop.get("height", 0)) > 1.0001:
        warnings.append("crop_y_out_of_bounds")
    return warnings


def main() -> int:
    payload = read_input()
    plan_path = Path(payload.get("portraitPlanPath") or payload.get("planPath") or "").expanduser().resolve()
    transcript_path_raw = payload.get("transcriptPath") or payload.get("subtitlesPath") or ""
    if not plan_path.exists():
        print(json.dumps({"ok": False, "error": "portraitPlanPath does not exist"}, indent=2))
        return 1

    max_words = int(payload.get("maxWordsOutput", 120))

    plan = load_json(plan_path)
    transcript_doc = {"segments": []}
    transcript_missing = False
    if transcript_path_raw:
        transcript_path = Path(transcript_path_raw).expanduser().resolve()
        if transcript_path.exists():
            transcript_doc = load_json(transcript_path)
        else:
            transcript_missing = True
    else:
        transcript_missing = True

    segments = transcript_segments(transcript_doc)
    warnings = []
    if transcript_missing:
        warnings.append("missing_transcript_path")

    clips = []
    for index, range_item in enumerate(plan.get("ranges") or [], start=1):
        binding = bind_subtitles(range_item, segments, max_words)
        range_warnings = crop_warnings(range_item)
        if not binding["text"]:
            range_warnings.append(f"missing_subtitle_binding:{range_item['startMs']}-{range_item['endMs']}")
        warnings.extend(range_warnings)
        clips.append({
            "id": range_item.get("id") or f"clip-{index:04d}",
            "sourceRange": {
                "startMs": int(range_item["startMs"]),
                "endMs": int(range_item["endMs"]),
                "durationMs": int(range_item["endMs"]) - int(range_item["startMs"]),
            },
            "startMs": range_item["startMs"],
            "endMs": range_item["endMs"],
            "kind": "planned_crop",
            "portraitMode": range_item.get("portraitMode") or "",
            "trackLabel": range_item.get("selectedPersonLabel") or "",
            "cropRect": range_item.get("cropRect") or {},
            "layout": range_item.get("layout") or None,
            "reason": range_item.get("reason") or "",
            "subtitle": binding,
            "warnings": sorted(set(range_warnings)),
        })

    transcript = "\n".join(clip["subtitle"]["text"] for clip in clips if clip["subtitle"]["text"])
    result = {
        "ok": True,
        "schema": "wowclip.clip-check.v2",
        "clipCount": len(clips),
        "clips": clips,
        "transcript": transcript,
        "warnings": sorted(set(warnings)),
        "content": [
            {
                "type": "text",
                "text": f"[clip_check] {len(clips)} clips, subtitles {sum(1 for clip in clips if clip['subtitle']['text'])}\n{transcript}",
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
