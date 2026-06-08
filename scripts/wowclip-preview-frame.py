#!/usr/bin/env python3
"""Generate a local preview frame using FFmpeg and optional portrait crop plan."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def main() -> int:
    payload = read_input()
    source_path = Path(payload.get("sourcePath") or "").expanduser().resolve()
    if not source_path.exists():
        print(json.dumps({"ok": False, "error": "sourcePath is required for MVP preview"}, indent=2))
        return 1
    output_path = Path(payload.get("outputPath") or "preview.jpg").expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = payload.get("ffmpegPath") or shutil.which("ffmpeg")
    if not ffmpeg:
        print(json.dumps({"ok": False, "error": "ffmpeg is required"}, indent=2))
        return 1
    time_sec = float(payload.get("timeMs", 0)) / 1000.0
    vf = None
    if payload.get("cropRect"):
        rect = payload["cropRect"]
        vf = f"crop=iw*{rect['width']}:ih*{rect['height']}:iw*{rect['x']}:ih*{rect['y']},scale={payload.get('targetWidth',1080)}:{payload.get('targetHeight',1920)}"
    cmd = [ffmpeg, "-y", "-ss", str(time_sec), "-i", str(source_path), "-frames:v", "1"]
    if vf:
        cmd.extend(["-vf", vf])
    cmd.extend(["-q:v", "2", str(output_path)])
    subprocess.run(cmd, check=True)
    print(json.dumps({"ok": True, "outputPath": str(output_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

