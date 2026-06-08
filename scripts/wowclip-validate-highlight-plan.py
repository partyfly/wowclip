#!/usr/bin/env python3
"""Validate highlight and clip plans before EDL compilation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


VALID_ROLES = {"hook", "proof", "demo", "benefit", "quote", "body", "cta"}
VALID_ACTIONS = {"hook_frontload", "trim_breath", "remove_filler", "tighten_pause", "tighten_demo", "keep_context"}


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def load_plan(payload: dict) -> tuple[dict, Path | None]:
    if isinstance(payload.get("highlightPlan"), dict):
        return payload["highlightPlan"], None
    path_raw = payload.get("highlightPlanPath") or payload.get("planPath") or ""
    if not path_raw:
        raise ValueError("highlightPlanPath or highlightPlan is required")
    path = Path(path_raw).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"highlightPlanPath does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8")), path


def validate(plan: dict, strict: bool = True) -> list[dict]:
    errors = []

    def add(code: str, message: str, path: str) -> None:
        errors.append({"code": code, "message": message, "path": path})

    if plan.get("schema") != "wowclip.highlight-plan.v1":
        add("INVALID_SCHEMA", "schema must be wowclip.highlight-plan.v1", "/schema")
    highlights = plan.get("highlights") or []
    clip_plans = plan.get("clipPlans") or []
    if not isinstance(highlights, list) or not highlights:
        add("MISSING_HIGHLIGHTS", "highlights must be a non-empty array", "/highlights")
        highlights = []
    if not isinstance(clip_plans, list) or not clip_plans:
        add("MISSING_CLIP_PLANS", "clipPlans must be a non-empty array", "/clipPlans")
        clip_plans = []

    highlights_by_id = {}
    for index, highlight in enumerate(highlights):
        path = f"/highlights/{index}"
        highlight_id = str(highlight.get("id") or "").strip()
        if not highlight_id:
            add("MISSING_HIGHLIGHT_ID", "highlight id is required", f"{path}/id")
            continue
        highlights_by_id[highlight_id] = highlight
        start_ms = int(highlight.get("startMs", -1))
        end_ms = int(highlight.get("endMs", -1))
        if end_ms <= start_ms:
            add("INVALID_HIGHLIGHT_RANGE", "highlight endMs must be greater than startMs", path)

    for plan_index, clip_plan in enumerate(clip_plans):
        plan_path = f"/clipPlans/{plan_index}"
        segments = clip_plan.get("segments") or []
        if not isinstance(segments, list) or not segments:
            add("MISSING_SEGMENTS", "clipPlan.segments must be non-empty", f"{plan_path}/segments")
            continue
        total_ms = 0
        previous_key = None
        previous_highlight_id = None
        for segment_index, segment in enumerate(segments):
            segment_path = f"{plan_path}/segments/{segment_index}"
            highlight_id = str(segment.get("highlightId") or "").strip()
            highlight = highlights_by_id.get(highlight_id)
            if not highlight:
                add("UNKNOWN_HIGHLIGHT", "segment.highlightId must reference highlights", f"{segment_path}/highlightId")
                continue
            role = str(segment.get("role") or "body").strip()
            if role not in VALID_ROLES:
                add("INVALID_ROLE", f"segment.role must be one of {sorted(VALID_ROLES)}", f"{segment_path}/role")
            actions = segment.get("actions") or []
            if not isinstance(actions, list) or not actions:
                add("MISSING_ACTIONS", "segment.actions must be non-empty", f"{segment_path}/actions")
            for action in actions:
                if action not in VALID_ACTIONS:
                    add("INVALID_ACTION", f"segment.actions entries must be one of {sorted(VALID_ACTIONS)}", f"{segment_path}/actions")
            start_ms = int(segment.get("startMs", -1))
            end_ms = int(segment.get("endMs", -1))
            if end_ms <= start_ms:
                add("INVALID_SEGMENT_RANGE", "segment endMs must be greater than startMs", segment_path)
                continue
            if start_ms < int(highlight.get("startMs", 0)) or end_ms > int(highlight.get("endMs", 0)):
                add("SEGMENT_OUTSIDE_HIGHLIGHT", "segment range must stay inside its highlight", segment_path)
            total_ms += end_ms - start_ms
            info_key = "|".join(str(tag).lower() for tag in (highlight.get("tags") or [])) or str(highlight.get("title") or "").lower()
            if strict and previous_key and info_key and info_key == previous_key and previous_highlight_id != highlight_id:
                add("CONSECUTIVE_DUPLICATE_INFO", "consecutive segments appear to repeat the same information point", segment_path)
            previous_key = info_key
            previous_highlight_id = highlight_id
        first_role = str(segments[0].get("role") or "")
        if first_role != "hook":
            add("HOOK_NOT_FIRST", "first clipPlan segment must have role hook", f"{plan_path}/segments/0/role")
        first_duration = int(segments[0].get("endMs", 0)) - int(segments[0].get("startMs", 0))
        if first_duration > 3000 and strict:
            add("HOOK_TOO_LONG", "hook segment should finish within 3 seconds", f"{plan_path}/segments/0")
        min_ms = 30_000 if strict else 1
        max_ms = 60_000 if strict else int(clip_plan.get("maxDurationMs") or 60_000)
        if total_ms < min_ms:
            add("CLIP_PLAN_TOO_SHORT", f"clipPlan duration must be at least {min_ms} ms", plan_path)
        if total_ms > max_ms:
            add("CLIP_PLAN_TOO_LONG", f"clipPlan duration must be at most {max_ms} ms", plan_path)

    return errors


def main() -> int:
    try:
        payload = read_input()
        plan, path = load_plan(payload)
        errors = validate(plan, strict=bool(payload.get("strict", True)))
        print(json.dumps({
            "ok": not errors,
            "highlightPlanPath": str(path) if path else "",
            "errors": errors,
            "highlightCount": len(plan.get("highlights") or []),
            "clipPlanCount": len(plan.get("clipPlans") or []),
        }, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
