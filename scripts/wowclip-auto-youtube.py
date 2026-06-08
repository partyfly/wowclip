#!/usr/bin/env python3
"""Run the local YouTube-to-portrait WowClip pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def run_json(command: list[str], stage: str) -> dict:
    completed = subprocess.run(command, text=True, capture_output=True)
    try:
        result = json.loads(completed.stdout or "{}")
    except Exception:
        result = {"ok": False, "stdout": completed.stdout, "stderr": completed.stderr}
    if completed.returncode != 0 or not result.get("ok"):
        result["stage"] = stage
        if completed.stderr and "stderr" not in result:
            result["stderr"] = completed.stderr
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def script_path(name: str) -> str:
    return str(Path(__file__).resolve().parent / name)


def json_arg(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def accepted_ranges(precheck: dict, candidates: dict, max_clips: int) -> list[dict]:
    by_id = {item["id"]: item for item in candidates.get("candidates") or []}
    ranges = []
    for check in precheck.get("checks") or []:
        if not check.get("ok"):
            continue
        candidate = by_id.get(check["id"])
        if not candidate:
            continue
        ranges.append({"startMs": int(candidate["startMs"]), "endMs": int(candidate["endMs"])})
        if len(ranges) >= max_clips:
            break
    return ranges


def ranges_from_clip_plan(highlight_plan: dict, selected_clip_plan_id: str | None = None) -> list[dict]:
    clip_plans = highlight_plan.get("clipPlans") or []
    if not clip_plans:
        return []
    selected = None
    if selected_clip_plan_id:
        selected = next((item for item in clip_plans if str(item.get("id")) == selected_clip_plan_id), None)
    selected = selected or clip_plans[0]
    ranges = []
    for segment in selected.get("segments") or []:
        start_ms = int(segment.get("startMs", 0))
        end_ms = int(segment.get("endMs", start_ms))
        if end_ms > start_ms:
            ranges.append({"startMs": start_ms, "endMs": end_ms})
    return ranges


def main() -> int:
    payload = read_input()
    scripts_dir = Path(__file__).resolve().parent
    project_root = Path(payload.get("projectRootDir") or "wowclip-youtube-project").expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    stages = []

    try:
        source_path_raw = payload.get("sourcePath") or ""
        if source_path_raw:
            source_path = str(Path(source_path_raw).expanduser().resolve())
            ingest_result = {"ok": True, "projectRootDir": str(project_root), "sourcePath": source_path}
        else:
            ingest_payload = {
                "url": payload.get("url"),
                "projectRootDir": str(project_root),
                "cookiesPath": payload.get("cookiesPath") or "",
                "subLangs": payload.get("subLangs") or "en.*,zh.*",
            }
            ingest_result = run_json(["python3", script_path("wowclip-ingest-youtube.py"), json_arg(ingest_payload)], "ingest_youtube")
            source_path = ingest_result["sourcePath"]
        stages.append({"stage": "ingest_youtube", **ingest_result})

        transcript_result = run_json(["python3", script_path("wowclip-transcribe-local.py"), json_arg({
            "sourcePath": source_path,
            "projectRootDir": str(project_root),
            "language": payload.get("language") or None,
            "model": payload.get("asrModel") or "large-v3-turbo",
            "device": payload.get("device") or "auto",
            "computeType": payload.get("computeType") or "auto",
            "segments": payload.get("segments") or [],
        })], "transcribe")
        stages.append({"stage": "transcribe", **transcript_result})

        select_result = run_json(["python3", script_path("wowclip-select-clips.py"), json_arg({
            "transcriptPath": transcript_result["jsonPath"],
            "projectRootDir": str(project_root),
            "minDurationMs": int(payload.get("minDurationMs", 15000)),
            "maxDurationMs": int(payload.get("maxDurationMs", 60000)),
            "maxClips": int(payload.get("maxClips", 5)),
        })], "select_clips")
        stages.append({"stage": "select_clips", **select_result})
        candidates_path = select_result["outputPath"]
        highlight_plan_path = select_result["highlightPlanPath"]
        validate_highlight_result = run_json(["python3", script_path("wowclip-validate-highlight-plan.py"), json_arg({
            "highlightPlanPath": highlight_plan_path,
            "strict": bool(payload.get("strictHighlightPlan", False)),
        })], "validate_highlight_plan")
        stages.append({"stage": "validate_highlight_plan", **validate_highlight_result})
        candidates_doc = json.loads(Path(candidates_path).read_text(encoding="utf-8"))
        highlight_plan_doc = json.loads(Path(highlight_plan_path).read_text(encoding="utf-8"))
        all_candidates = candidates_doc.get("candidates") or []
        start_ms = min(int(item["startMs"]) for item in all_candidates)
        end_ms = max(int(item["endMs"]) for item in all_candidates)

        frames_result = run_json(["python3", script_path("wowclip-extract-frames.py"), json_arg({
            "sourcePath": source_path,
            "projectRootDir": str(project_root),
            "startMs": start_ms,
            "endMs": end_ms,
            "maxFrames": int(payload.get("maxFrames", min(180, max(24, ((end_ms - start_ms) // 1000) + 1)))),
        })], "extract_frames")
        stages.append({"stage": "extract_frames", **frames_result})

        montage_result = run_json(["python3", script_path("wowclip-preview-montage.py"), json_arg({
            "manifestPath": frames_result["manifestPath"],
            "outputPath": str(project_root / "cache" / "previews" / "candidate_montage.jpg"),
        })], "preview_montage")
        stages.append({"stage": "preview_montage", "outputPath": montage_result["outputPath"], "frameCount": montage_result["frameCount"]})

        shots_result = run_json(["python3", script_path("wowclip-detect-shots.py"), json_arg({
            "manifestPath": frames_result["manifestPath"],
            "outputPath": str(project_root / "cache" / "frames" / "shots.json"),
            "threshold": float(payload.get("shotThreshold", 0.42)),
            "confidenceThreshold": float(payload.get("shotConfidenceThreshold", 0.80)),
            "minDurationMs": int(payload.get("shotMinDurationMs", 700)),
            "denseSourceScan": payload.get("denseSourceScan", True) is not False,
            "denseScanFps": float(payload.get("denseScanFps", 4.0)),
            "maxDenseFrames": int(payload.get("maxDenseFrames", 1200)),
            "endMs": end_ms,
        })], "detect_shots")
        stages.append({"stage": "detect_shots", **shots_result})
        face_frames_dir = shots_result.get("denseFramesDir") or frames_result["outputDir"]

        detections_result = run_json(["python3", script_path("wowclip-detect-faces.py"), json_arg({
            "framesDir": face_frames_dir,
            "outputPath": str(project_root / "cache" / "faces" / "detections.json"),
            "yunetPath": payload.get("yunetPath") or str(project_root / "assets" / "models" / "opencv" / "face_detection_yunet.onnx"),
        })], "detect_faces")
        stages.append({"stage": "detect_faces", **detections_result})

        precheck_result = run_json(["python3", script_path("wowclip-precheck-candidates.py"), json_arg({
            "candidatesPath": candidates_path,
            "detectionsPath": detections_result["outputPath"],
            "outputPath": str(project_root / "cache" / "previews" / "candidate_precheck.json"),
            "minScore": float(payload.get("candidateMinScore", 0.45)),
        })], "precheck_candidates")
        stages.append({"stage": "precheck_candidates", **precheck_result})

        track_result = run_json(["python3", script_path("wowclip-track-faces.py"), json_arg({
            "detectionsPath": detections_result["outputPath"],
            "sfacePath": payload.get("sfacePath") or str(project_root / "assets" / "models" / "opencv" / "face_recognition_sface.onnx"),
            "outputPath": str(project_root / "cache" / "faces" / "tracks.json"),
        })], "track_faces")
        stages.append({"stage": "track_faces", **track_result})

        ranges = ranges_from_clip_plan(highlight_plan_doc, payload.get("selectedClipPlanId"))
        if not ranges:
            ranges = accepted_ranges(precheck_result, candidates_doc, int(payload.get("maxClips", 5)))
        if not ranges:
            raise RuntimeError(json.dumps({"ok": False, "stage": "precheck_candidates", "error": "no accepted candidate ranges"}, ensure_ascii=False, indent=2))
        plan_result = run_json(["python3", script_path("wowclip-plan-portrait.py"), json_arg({
            "detectionsPath": detections_result["outputPath"],
            "tracksPath": track_result["outputPath"],
            "shotsPath": shots_result["outputPath"],
            "embeddedPortraitPath": shots_result["outputPath"],
            "ranges": ranges,
            "assetId": payload.get("assetId") or "A001",
            "portraitMode": payload.get("portraitMode") or "auto",
            "outputPath": str(project_root / "plans" / "portrait" / "plan.json"),
        })], "plan_portrait")
        planned_ranges = plan_result["plan"].get("ranges") or []
        stages.append({"stage": "plan_portrait", "outputPath": plan_result["outputPath"], "rangeCount": len(planned_ranges)})
        if not planned_ranges:
            raise RuntimeError(json.dumps({
                "ok": False,
                "stage": "plan_portrait",
                "error": "no face-centered portrait ranges",
                "portraitPlanPath": plan_result["outputPath"],
            }, ensure_ascii=False, indent=2))

        materials_result = run_json(["python3", script_path("wowclip-portrait-materials.py"), json_arg({
            "tracksPath": track_result["outputPath"],
            "transcriptPath": transcript_result["jsonPath"],
            "ranges": planned_ranges,
            "outputPath": str(project_root / "cache" / "previews" / "portrait_materials.json"),
        })], "portrait_materials")
        stages.append({
            "stage": "portrait_materials",
            "outputPath": materials_result["outputPath"],
            "materialCount": materials_result["materialCount"],
        })
        if int(materials_result.get("materialCount") or 0) <= 0:
            raise RuntimeError(json.dumps({
                "ok": False,
                "stage": "portrait_materials",
                "error": "no face-centered portrait materials",
                "portraitMaterialsPath": materials_result["outputPath"],
            }, ensure_ascii=False, indent=2))

        clip_check_result = run_json(["python3", script_path("wowclip-clip-check.py"), json_arg({
            "portraitPlanPath": plan_result["outputPath"],
            "tracksPath": track_result["outputPath"],
            "transcriptPath": transcript_result["jsonPath"],
            "outputPath": str(project_root / "cache" / "previews" / "clip_check.json"),
            "minWords": int(payload.get("minWords", 1)),
        })], "final_clip_check")
        stages.append({"stage": "final_clip_check", **clip_check_result})

        timeline_result = run_json(["python3", script_path("wowclip-build-timeline.py"), json_arg({
            "sourcePath": source_path,
            "portraitPlanPath": plan_result["outputPath"],
            "clipCheckPath": clip_check_result["outputPath"],
            "transcriptPath": transcript_result["jsonPath"],
            "highlightPlanPath": highlight_plan_path,
            "selectedClipPlanId": payload.get("selectedClipPlanId") or "",
            "projectRootDir": str(project_root),
            "outputPath": str(project_root / "edl.json"),
        })], "build_timeline")
        stages.append({"stage": "build_timeline", **timeline_result})

        export_path = str(project_root / "exports" / "youtube_portrait.mp4")
        if bool(payload.get("export", True)):
            export_result = run_json(["python3", script_path("wowclip-export.py"), json_arg({
                "edlPath": timeline_result["edlPath"],
                "outputPath": payload.get("outputPath") or export_path,
                "burnSubtitles": bool(payload.get("burnSubtitles", True)),
            })], "export")
            stages.append({"stage": "export", **export_result})
        result = {
            "ok": True,
            "projectRootDir": str(project_root),
            "sourcePath": source_path,
            "transcriptPath": transcript_result["jsonPath"],
            "candidatesPath": candidates_path,
            "highlightPlanPath": highlight_plan_path,
            "candidatePrecheckPath": precheck_result["outputPath"],
            "shotsPath": shots_result["outputPath"],
            "portraitPlanPath": plan_result["outputPath"],
            "portraitMaterialsPath": materials_result["outputPath"],
            "clipCheckPath": clip_check_result["outputPath"],
            "edlPath": timeline_result["edlPath"],
            "outputPath": payload.get("outputPath") or export_path,
            "stages": stages,
        }
        (project_root / "wowclip-auto-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        message = str(error)
        try:
            parsed = json.loads(message)
        except Exception:
            parsed = {"ok": False, "error": message}
        parsed["stages"] = stages
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
