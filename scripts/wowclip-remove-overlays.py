#!/usr/bin/env python3
"""Remove hard subtitles or watermarks from local video material with ProPainter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


PROPAINTER_WEIGHTS = [
    "ProPainter.pth",
    "recurrent_flow_completion.pth",
    "raft-things.pth",
]


def read_input() -> dict[str, Any]:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def require_file(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def require_dir(path: Path, label: str) -> Path:
    if not path.exists() or not path.is_dir():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def resolve_propainter_dir(payload: dict[str, Any], project_root: Path) -> Path:
    raw = (
        payload.get("propainterDir")
        or os.environ.get("WOWCLIP_PROPAINTER_DIR")
        or project_root / "assets" / "models" / "propainter" / "ProPainter"
    )
    path = Path(raw).expanduser().resolve()
    require_dir(path, "propainterDir")
    require_file(path / "inference_propainter.py", "ProPainter inference script")
    return path


def link_weights(propainter_dir: Path, weights_dir: Path | None) -> list[str]:
    weights_root = propainter_dir / "weights"
    weights_root.mkdir(parents=True, exist_ok=True)
    resolved = []
    for name in PROPAINTER_WEIGHTS:
        target = weights_root / name
        if weights_dir is not None:
            source = require_file(weights_dir / name, f"weightsDir/{name}")
            if target.exists() or target.is_symlink():
                if target.resolve() == source.resolve():
                    pass
                else:
                    target.unlink()
                    target.symlink_to(source)
            else:
                target.symlink_to(source)
        require_file(target, f"ProPainter weight {name}")
        resolved.append(str(target.resolve()))
    return resolved


def parse_rect(rect: dict[str, Any]) -> tuple[float, float, float, float]:
    x = float(rect.get("x", 0.0))
    y = float(rect.get("y", 0.0))
    width = float(rect.get("width", 1.0))
    height = float(rect.get("height", 1.0))
    if width <= 0 or height <= 0:
        raise ValueError("maskRect width and height must be positive")
    x2 = min(1.0, x + width)
    y2 = min(1.0, y + height)
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    if x2 <= x or y2 <= y:
        raise ValueError("maskRect is outside the normalized frame")
    return x, y, x2, y2


def mask_rects(payload: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    rects_raw = payload.get("maskRects")
    if rects_raw is None:
        rects_raw = [payload.get("maskRect") or {"x": 0.0, "y": 0.80, "width": 1.0, "height": 0.19}]
    if not isinstance(rects_raw, list) or not rects_raw:
        raise ValueError("maskRects must be a non-empty list")
    return [parse_rect(item) for item in rects_raw]


def write_mask(path: Path, width: int, height: int, rects: list[tuple[float, float, float, float]]) -> Path:
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for x, y, x2, y2 in rects:
        left = int(round(x * width))
        top = int(round(y * height))
        right = max(left, int(round(x2 * width)) - 1)
        bottom = max(top, int(round(y2 * height)) - 1)
        draw.rectangle([left, top, right, bottom], fill=255)
    path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(path)
    return path


def run_json_command(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


def probe_video(source_path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ValueError("ffprobe is required")
    result = subprocess.run([
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,duration",
        "-of",
        "json",
        str(source_path),
    ], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    streams = json.loads(result.stdout).get("streams") or []
    if not streams:
        raise ValueError(f"no video stream found: {source_path}")
    return streams[0]


def fps_from_probe(probed: dict[str, Any]) -> float:
    raw = str(probed.get("avg_frame_rate") or "0/1")
    if "/" in raw:
        num, den = raw.split("/", 1)
        denominator = float(den)
        return float(num) / denominator if denominator else 0.0
    return float(raw or 0.0)


def prepare_frame_input(payload: dict[str, Any], source_path: Path, run_dir: Path, probed: dict[str, Any]) -> tuple[Path, int]:
    existing_frames = payload.get("inputFramesDir")
    if existing_frames:
        frames_dir = Path(existing_frames).expanduser().resolve()
        require_dir(frames_dir, "inputFramesDir")
        return frames_dir, int(payload.get("saveFps") or payload.get("processingFps") or round(fps_from_probe(probed)) or 24)

    start_ms = int(payload.get("startMs", 0))
    end_ms = payload.get("endMs")
    duration_ms = payload.get("durationMs")
    processing_fps = float(payload.get("processingFps") or fps_from_probe(probed) or 24)
    if end_ms is not None:
        duration_ms = max(1, int(end_ms) - start_ms)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is required")

    run_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = run_dir / "input_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-y"]
    if start_ms > 0:
        command.extend(["-ss", f"{start_ms / 1000:.3f}"])
    command.extend(["-i", str(source_path)])
    if duration_ms is not None:
        command.extend(["-t", f"{int(duration_ms) / 1000:.3f}"])
    filters = [f"fps={processing_fps:.6g}"]
    if payload.get("processingWidth") and payload.get("processingHeight"):
        filters.append(f"scale={int(payload['processingWidth'])}:{int(payload['processingHeight'])}")
    elif payload.get("processingWidth"):
        filters.append(f"scale={int(payload['processingWidth'])}:-2")
    elif payload.get("processingHeight"):
        filters.append(f"scale=-2:{int(payload['processingHeight'])}")
    if filters:
        command.extend(["-vf", ",".join(filters)])
    command.append(str(frames_dir / "%05d.png"))
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    frame_count = len(list(frames_dir.glob("*.png")))
    if frame_count == 0:
        raise RuntimeError("ffmpeg extracted zero frames for overlay removal")
    return frames_dir, int(payload.get("saveFps") or round(processing_fps) or 24)


def propainter_command(
    python_path: str,
    propainter_dir: Path,
    input_path: Path,
    mask_path: Path,
    output_root: Path,
    payload: dict[str, Any],
) -> list[str]:
    command = [
        python_path,
        "inference_propainter.py",
        "--video",
        str(input_path),
        "--mask",
        str(mask_path),
        "--output",
        str(output_root),
        "--mask_dilation",
        str(int(payload.get("maskDilation", 2))),
        "--raft_iter",
        str(int(payload.get("raftIter", 2))),
        "--subvideo_length",
        str(int(payload.get("subvideoLength", 24))),
        "--neighbor_length",
        str(int(payload.get("neighborLength", 6))),
        "--ref_stride",
        str(int(payload.get("refStride", 6))),
    ]
    if payload.get("processingWidth") and payload.get("processingHeight"):
        command.extend(["--width", str(int(payload["processingWidth"])), "--height", str(int(payload["processingHeight"]))])
    if payload.get("saveFps"):
        command.extend(["--save_fps", str(int(payload["saveFps"]))])
    if payload.get("saveFrames"):
        command.append("--save_frames")
    if payload.get("fp16"):
        command.append("--fp16")
    return command


def extract_first_frame(video_path: Path, frame_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is required")
    result = subprocess.run([
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "select=eq(n\\,0)",
        "-frames:v",
        "1",
        str(frame_path),
    ], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())


def first_image_from_input(input_path: Path, output_path: Path) -> Path:
    if input_path.is_dir():
        images = sorted([*input_path.glob("*.png"), *input_path.glob("*.jpg"), *input_path.glob("*.jpeg")])
        if not images:
            raise ValueError(f"input frame directory is empty: {input_path}")
        shutil.copy2(images[0], output_path)
        return output_path
    extract_first_frame(input_path, output_path)
    return output_path


def write_contact_sheet(input_path: Path, output_path: Path, mask_path: Path, sheet_path: Path) -> Path:
    tmp_dir = sheet_path.parent / "contact_frames"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    source_frame = tmp_dir / "source.jpg"
    output_frame = tmp_dir / "output.jpg"
    first_image_from_input(input_path, source_frame)
    extract_first_frame(output_path, output_frame)
    source = Image.open(source_frame).convert("RGB")
    output = Image.open(output_frame).convert("RGB").resize(source.size)
    mask = Image.open(mask_path).convert("L").resize(source.size)
    overlay = Image.new("RGB", source.size, (0, 255, 0))
    alpha = mask.point(lambda value: 120 if value else 0)
    masked = Image.composite(overlay, source, alpha)
    label_h = 28
    sheet = Image.new("RGB", (source.width * 3, source.height + label_h), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate([("source", source), ("mask", masked), ("cleaned", output)]):
        x = index * source.width
        sheet.paste(image, (x, label_h))
        draw.text((x + 8, 8), label, fill=(0, 0, 0))
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path, quality=92)
    return sheet_path


def main() -> int:
    try:
        payload = read_input()
        source_path = Path(payload.get("sourcePath") or payload.get("path") or "").expanduser().resolve()
        require_file(source_path, "sourcePath")
        project_root = Path(payload.get("projectRootDir") or source_path.parent).expanduser().resolve()
        project_root.mkdir(parents=True, exist_ok=True)
        run_dir = Path(payload.get("workDir") or project_root / "cache" / "overlays" / source_path.stem).expanduser().resolve()
        propainter_dir = resolve_propainter_dir(payload, project_root)
        weights_dir = Path(payload["weightsDir"]).expanduser().resolve() if payload.get("weightsDir") else None
        weights = link_weights(propainter_dir, weights_dir)

        probed = probe_video(source_path)
        mask_width = int(payload.get("maskWidth") or payload.get("processingWidth") or probed["width"])
        mask_height = int(payload.get("maskHeight") or payload.get("processingHeight") or probed["height"])
        mask_path = Path(payload.get("maskPath") or run_dir / "overlay_mask.png").expanduser().resolve()
        write_mask(mask_path, mask_width, mask_height, mask_rects(payload))

        input_path, save_fps = prepare_frame_input(payload, source_path, run_dir, probed)
        payload = {**payload, "saveFps": payload.get("saveFps") or save_fps}
        output_root = Path(payload.get("propainterOutputDir") or run_dir / "propainter").expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        python_path = str(Path(payload.get("pythonPath") or sys.executable).expanduser())
        command = propainter_command(python_path, propainter_dir, input_path, mask_path, output_root, payload)

        if payload.get("dryRun"):
            print(json.dumps({
                "ok": True,
                "dryRun": True,
                "command": command,
                "cwd": str(propainter_dir),
                "maskPath": str(mask_path),
                "inputPath": str(input_path),
                "weights": weights,
            }, ensure_ascii=False, indent=2))
            return 0

        env = dict(os.environ)
        env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        result = subprocess.run(command, cwd=str(propainter_dir), env=env, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())

        produced = output_root / input_path.name / "inpaint_out.mp4"
        require_file(produced, "ProPainter output")
        output_path = Path(payload.get("outputPath") or project_root / "exports" / f"{source_path.stem}_overlay_removed.mp4").expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced, output_path)

        contact_sheet_path = Path(payload.get("contactSheetPath") or run_dir / "overlay_removal_contact_sheet.jpg").expanduser().resolve()
        write_contact_sheet(input_path, output_path, mask_path, contact_sheet_path)

        print(json.dumps({
            "ok": True,
            "sourcePath": str(source_path),
            "inputPath": str(input_path),
            "outputPath": str(output_path),
            "maskPath": str(mask_path),
            "contactSheetPath": str(contact_sheet_path),
            "propainterDir": str(propainter_dir),
            "weights": weights,
            "stdout": result.stdout[-4000:],
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
