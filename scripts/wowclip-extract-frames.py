#!/usr/bin/env python3
"""Extract timestamped frames for WowClip analysis."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def default_times(start_ms: int, end_ms: int, max_frames: int) -> list[int]:
    if end_ms <= start_ms:
        return [start_ms]
    count = max(1, min(max_frames, 240))
    if count == 1:
        return [(start_ms + end_ms) // 2]
    return [int(round(start_ms + (end_ms - start_ms) * i / (count - 1))) for i in range(count)]


def main() -> int:
    payload = read_input()
    source_path = Path(payload.get("sourcePath") or payload.get("path") or "").expanduser().resolve()
    if not source_path.exists():
        print(json.dumps({"ok": False, "error": "sourcePath does not exist"}, indent=2))
        return 1

    project_root = Path(payload.get("projectRootDir") or source_path.parent).expanduser().resolve()
    output_dir = Path(payload.get("outputDir") or project_root / "cache" / "frames" / source_path.stem).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = payload.get("ffmpegPath") or shutil.which("ffmpeg")
    if not ffmpeg:
        print(json.dumps({"ok": False, "error": "ffmpeg is required"}, indent=2))
        return 1

    start_ms = int(payload.get("startMs", 0))
    end_ms = int(payload.get("endMs", max(start_ms + 1, int(payload.get("durationMs", 0) or 0))))
    if end_ms <= start_ms:
        end_ms = start_ms + 1
    if isinstance(payload.get("timesMs"), list) and payload["timesMs"]:
        times_ms = sorted({int(max(start_ms, min(end_ms, value))) for value in payload["timesMs"]})
    else:
        times_ms = default_times(start_ms, end_ms, int(payload.get("maxFrames", 12)))

    max_width = int(payload.get("maxWidth", 960))
    frames = []
    for time_ms in times_ms:
        output_path = output_dir / f"frame-{time_ms:010d}.jpg"
        vf = f"scale='min({max_width},iw)':-2"
        subprocess.run([
            ffmpeg,
            "-y",
            "-ss",
            f"{time_ms / 1000:.3f}",
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            "-vf",
            vf,
            "-q:v",
            "2",
            str(output_path),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        frames.append({
            "timeMs": time_ms,
            "timeSec": round(time_ms / 1000, 3),
            "path": str(output_path),
        })

    manifest_path = output_dir / "frames.json"
    manifest = {
        "schema": "wowclip.frames.v1",
        "sourcePath": str(source_path),
        "range": {"startMs": start_ms, "endMs": end_ms, "durationMs": end_ms - start_ms},
        "frames": frames,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "sourcePath": str(source_path),
        "outputDir": str(output_dir),
        "manifestPath": str(manifest_path),
        "frameCount": len(frames),
        "frames": frames,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
