#!/usr/bin/env python3
"""Select subtitle-driven candidate clips from word-level transcripts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def normalize_segments(doc: dict) -> list[dict]:
    segments = []
    for index, segment in enumerate(doc.get("segments") or [], start=1):
        start_ms = int(segment.get("startMs", round(float(segment.get("start", 0)) * 1000)))
        end_ms = int(segment.get("endMs", round(float(segment.get("end", 0)) * 1000)))
        text = str(segment.get("text") or "").strip()
        if end_ms <= start_ms or not text:
            continue
        words = []
        for word_index, word in enumerate(segment.get("words") or [], start=1):
            word_start = int(word.get("startMs", round(float(word.get("start", start_ms / 1000)) * 1000)))
            word_end = int(word.get("endMs", round(float(word.get("end", end_ms / 1000)) * 1000)))
            token = str(word.get("word") or word.get("text") or "").strip()
            if token and word_end > word_start:
                words.append({"id": word.get("id") or f"seg-{index:04d}-w{word_index:03d}", "startMs": word_start, "endMs": word_end, "word": token})
        segments.append({"id": segment.get("id") or f"seg-{index:04d}", "startMs": start_ms, "endMs": end_ms, "text": text, "words": words})
    return segments


def sentence_boundary(text: str) -> bool:
    return bool(re.search(r"[。！？!?\.]\s*$", text.strip()))


def join_text(items: list[dict]) -> str:
    return " ".join(item["text"] for item in items).strip()


def score_candidate(items: list[dict], min_ms: int, max_ms: int) -> float:
    duration = int(items[-1]["endMs"]) - int(items[0]["startMs"])
    text = join_text(items)
    word_count = sum(len(item.get("words") or []) for item in items)
    density = min(1.0, word_count / max(1, duration / 1200))
    duration_score = 1.0 if min_ms <= duration <= max_ms else max(0.0, 1.0 - abs(duration - ((min_ms + max_ms) / 2)) / max_ms)
    hook_bonus = 0.12 if re.search(r"(why|how|secret|mistake|best|worst|because|但是|为什么|如何|关键|问题|方法|秘密)", text, re.I) else 0.0
    boundary_bonus = 0.08 if sentence_boundary(items[-1]["text"]) else 0.0
    return round(min(1.0, density * 0.45 + duration_score * 0.45 + hook_bonus + boundary_bonus), 4)


def build_candidates(segments: list[dict], min_ms: int, max_ms: int, max_clips: int) -> list[dict]:
    candidates = []
    index = 0
    while index < len(segments):
        group = []
        start_ms = int(segments[index]["startMs"])
        cursor = index
        while cursor < len(segments):
            group.append(segments[cursor])
            duration = int(group[-1]["endMs"]) - start_ms
            if duration >= min_ms and (sentence_boundary(group[-1]["text"]) or duration >= max_ms * 0.8):
                break
            if duration >= max_ms:
                break
            cursor += 1
        if group:
            end_ms = int(group[-1]["endMs"])
            duration = end_ms - start_ms
            if duration >= max(1000, min_ms // 2):
                words = [word for item in group for word in item.get("words") or []]
                candidates.append({
                    "id": f"cand-{len(candidates) + 1:04d}",
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "durationMs": duration,
                    "text": join_text(group),
                    "segmentIds": [item["id"] for item in group],
                    "wordCount": len(words),
                    "hasWordTimestamps": bool(words),
                    "score": score_candidate(group, min_ms, max_ms),
                })
        index = max(cursor + 1, index + 1)
    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:max_clips]


def build_highlight_plan(candidates: list[dict], source_asset_id: str) -> dict:
    highlights = []
    clip_plans = []
    for index, candidate in enumerate(candidates, start=1):
        highlight_id = f"H{index:03d}"
        start_ms = int(candidate["startMs"])
        end_ms = int(candidate["endMs"])
        duration_ms = end_ms - start_ms
        hook_end = min(end_ms, start_ms + 3000)
        segments = [{
            "highlightId": highlight_id,
            "role": "hook",
            "startMs": start_ms,
            "endMs": hook_end,
            "reason": "Use the opening sentence as a front-loaded hook.",
            "actions": ["hook_frontload"],
        }]
        if hook_end < end_ms:
            segments.append({
                "highlightId": highlight_id,
                "role": "body",
                "startMs": hook_end,
                "endMs": end_ms,
                "reason": "Keep the core explanation after the hook.",
                "actions": ["keep_context", "tighten_pause"],
            })
        highlights.append({
            "id": highlight_id,
            "title": candidate["text"][:36] or f"Highlight {index}",
            "startMs": start_ms,
            "endMs": end_ms,
            "text": candidate["text"],
            "reason": f"Subtitle-driven candidate score {candidate.get('score', 0)}.",
            "tags": ["auto_candidate"],
        })
        clip_plans.append({
            "id": f"CP{index:03d}",
            "title": f"Clip Plan {index}",
            "summary": candidate["text"][:80],
            "reason": "Generated from a subtitle candidate with hook front-loaded.",
            "highlightIds": [highlight_id],
            "segments": segments,
            "tags": ["auto_candidate"],
            "durationMs": duration_ms,
        })
    return {
        "schema": "wowclip.highlight-plan.v1",
        "sourceAssetId": source_asset_id,
        "highlights": highlights,
        "clipPlans": clip_plans,
    }


def main() -> int:
    payload = read_input()
    transcript_path = Path(payload.get("transcriptPath") or "").expanduser().resolve()
    if not transcript_path.exists():
        print(json.dumps({"ok": False, "error": "transcriptPath does not exist"}, indent=2))
        return 1
    project_root = Path(payload.get("projectRootDir") or transcript_path.parent.parent).expanduser().resolve()
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    min_ms = int(payload.get("minDurationMs", 15000))
    max_ms = int(payload.get("maxDurationMs", 60000))
    max_clips = int(payload.get("maxClips", 5))
    source_asset_id = str(payload.get("sourceAssetId") or payload.get("assetId") or "A001")
    candidates = build_candidates(normalize_segments(transcript), min_ms, max_ms, max_clips)
    output_path = Path(payload.get("outputPath") or project_root / "plans" / "clips" / "candidates.json").expanduser().resolve()
    highlight_plan_path = Path(payload.get("highlightPlanPath") or project_root / "plans" / "clips" / "highlight-plan.json").expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    highlight_plan_path.parent.mkdir(parents=True, exist_ok=True)
    highlight_plan = build_highlight_plan(candidates, source_asset_id)
    result = {
        "schema": "wowclip.clip-candidates.v1",
        "transcriptPath": str(transcript_path),
        "minDurationMs": min_ms,
        "maxDurationMs": max_ms,
        "candidates": candidates,
        "highlightPlanPath": str(highlight_plan_path),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    highlight_plan_path.write_text(json.dumps(highlight_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": bool(candidates),
        "outputPath": str(output_path),
        "highlightPlanPath": str(highlight_plan_path),
        "candidateCount": len(candidates),
        "clipPlanCount": len(highlight_plan["clipPlans"]),
        "candidates": candidates,
    }, ensure_ascii=False, indent=2))
    return 0 if candidates else 1


if __name__ == "__main__":
    raise SystemExit(main())
