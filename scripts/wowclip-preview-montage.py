#!/usr/bin/env python3
"""Create a Look/ClipCheck-style montage for analysis frames."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def load_frames(payload: dict) -> list[dict]:
    if isinstance(payload.get("frames"), list):
        return payload["frames"]
    manifest_path = payload.get("manifestPath")
    if manifest_path:
        doc = json.loads(Path(manifest_path).expanduser().resolve().read_text(encoding="utf-8"))
        return doc.get("frames") or []
    frames_dir = Path(payload.get("framesDir") or "").expanduser().resolve()
    frames = []
    for path in sorted([*frames_dir.glob("*.jpg"), *frames_dir.glob("*.jpeg"), *frames_dir.glob("*.png")]):
        parts = path.stem.split("-")
        time_ms = int(parts[-1]) if parts[-1].isdigit() else 0
        frames.append({"timeMs": time_ms, "path": str(path)})
    return frames


def main() -> int:
    payload = read_input()
    frames = load_frames(payload)
    if not frames:
        print(json.dumps({"ok": False, "error": "no frames found"}, indent=2))
        return 1
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        print(json.dumps({"ok": False, "error": "Pillow is required", "install": "pip install pillow"}, indent=2))
        return 1

    thumb_w = int(payload.get("thumbWidth", 320))
    thumb_h = int(payload.get("thumbHeight", 180))
    columns = int(payload.get("columns", min(4, max(1, math.ceil(math.sqrt(len(frames)))))))
    rows = math.ceil(len(frames) / columns)
    label_h = 28
    canvas = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)

    rendered = []
    for index, frame in enumerate(frames):
        path = Path(frame["path"]).expanduser().resolve()
        if not path.exists():
            continue
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (thumb_w, thumb_h), (0, 0, 0))
        tile.paste(image, ((thumb_w - image.width) // 2, (thumb_h - image.height) // 2))
        col = index % columns
        row = index // columns
        x = col * thumb_w
        y = row * (thumb_h + label_h)
        canvas.paste(tile, (x, y))
        time_ms = int(frame.get("timeMs", 0))
        label = f"{time_ms / 1000:.2f}s"
        draw.rectangle((x, y + thumb_h, x + thumb_w, y + thumb_h + label_h), fill=(28, 28, 28))
        draw.text((x + 8, y + thumb_h + 7), label, fill=(230, 230, 230))
        rendered.append({**frame, "tile": {"x": x, "y": y, "width": thumb_w, "height": thumb_h}})

    output_path = Path(payload.get("outputPath") or Path(frames[0]["path"]).parent / "montage.jpg").expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)
    print(json.dumps({
        "ok": True,
        "outputPath": str(output_path),
        "columns": columns,
        "rows": rows,
        "frameCount": len(rendered),
        "frames": rendered,
        "content": [
            {"type": "text", "text": f"[wowclip-look] montage {len(rendered)} frames"},
            {"type": "image", "path": str(output_path), "mimeType": "image/jpeg"},
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

