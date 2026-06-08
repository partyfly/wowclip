#!/usr/bin/env python3
"""Ingest a YouTube URL into a local WowClip project with yt-dlp."""

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


def media_candidates(sources_dir: Path) -> list[Path]:
    ignored = {".json", ".webp", ".jpg", ".jpeg", ".png", ".srt", ".vtt", ".part", ".ytdl"}
    return sorted([
        path for path in sources_dir.glob("source.*")
        if path.is_file() and path.suffix.lower() not in ignored
    ], key=lambda path: path.stat().st_mtime, reverse=True)


def main() -> int:
    payload = read_input()
    url = str(payload.get("url") or "").strip()
    if not url:
        print(json.dumps({"ok": False, "error": "url is required"}, indent=2))
        return 1
    if "youtube.com" not in url and "youtu.be" not in url:
        print(json.dumps({"ok": False, "error": "only YouTube URLs are supported by this ingester"}, indent=2))
        return 1

    project_root = Path(payload.get("projectRootDir") or "wowclip-youtube-project").expanduser().resolve()
    sources_dir = project_root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    yt_dlp = payload.get("ytDlpPath") or shutil.which("yt-dlp")
    if not yt_dlp:
        print(json.dumps({"ok": False, "error": "yt-dlp is required", "install": "pip install yt-dlp"}, indent=2))
        return 1

    metadata_path = sources_dir / "metadata.json"
    dump_command = [yt_dlp, "--dump-single-json", "--no-playlist", url]
    cookies_path_raw = payload.get("cookiesPath") or ""
    if cookies_path_raw:
        dump_command[1:1] = ["--cookies", str(Path(cookies_path_raw).expanduser().resolve())]
    dump = subprocess.run(dump_command, check=True, text=True, capture_output=True)
    metadata = json.loads(dump.stdout or "{}")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    output_template = str(sources_dir / "source.%(ext)s")
    command = [
        yt_dlp,
        "--no-playlist",
        "--write-info-json",
        "--write-thumbnail",
        "--write-auto-subs",
        "--write-subs",
        "--sub-format",
        "srt/best",
        "--sub-langs",
        str(payload.get("subLangs") or "en.*,zh.*,ja.*,ko.*"),
        "-f",
        str(payload.get("format") or "bv*+ba/b"),
        "-o",
        output_template,
        url,
    ]
    if cookies_path_raw:
        command[1:1] = ["--cookies", str(Path(cookies_path_raw).expanduser().resolve())]
    if payload.get("skipDownload"):
        command[1:1] = ["--skip-download"]
    subprocess.run(command, check=True)

    candidates = media_candidates(sources_dir)
    source_path = candidates[0] if candidates else None
    source_links_path = project_root / "source-links.json"
    source_links = {
        "schema": "wowclip.source-links.v1",
        "platform": "youtube",
        "url": url,
        "title": metadata.get("title") or "",
        "channel": metadata.get("channel") or metadata.get("uploader") or "",
        "durationMs": int(round(float(metadata.get("duration") or 0) * 1000)),
        "sourcePath": str(source_path) if source_path else "",
        "metadataPath": str(metadata_path),
    }
    source_links_path.write_text(json.dumps(source_links, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": bool(source_path) or bool(payload.get("skipDownload")),
        "projectRootDir": str(project_root),
        "sourcePath": str(source_path) if source_path else "",
        "sourceLinksPath": str(source_links_path),
        "metadataPath": str(metadata_path),
        "title": source_links["title"],
        "channel": source_links["channel"],
        "durationMs": source_links["durationMs"],
    }, ensure_ascii=False, indent=2))
    return 0 if source_path or payload.get("skipDownload") else 1


if __name__ == "__main__":
    raise SystemExit(main())
