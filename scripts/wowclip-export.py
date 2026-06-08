#!/usr/bin/env python3
"""Export a local MP4 from a standard WowClip EDL."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def read_input() -> dict:
    if len(sys.argv) > 1:
        return json.loads(" ".join(sys.argv[1:]))
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def load_edl(payload: dict) -> tuple[dict, Path | None]:
    if isinstance(payload.get("edl"), dict):
        return payload["edl"], None
    edl_path_raw = payload.get("edlPath")
    if not edl_path_raw:
        raise ValueError("edlPath or inline edl is required")
    edl_path = Path(edl_path_raw).expanduser().resolve()
    if not edl_path.exists():
        raise ValueError(f"edlPath does not exist: {edl_path}")
    return json.loads(edl_path.read_text(encoding="utf-8")), edl_path


def srt_timestamp(ms: int) -> str:
    ms = max(0, int(ms))
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def escape_srt_text(text: str) -> str:
    return str(text).replace("\r", " ").replace("\n", " ").strip()


def write_srt(path: Path, subtitles: list[dict], interval_start_ms: int, interval_end_ms: int) -> bool:
    rows = []
    index = 1
    for subtitle in subtitles:
        start_ms = int(subtitle.get("dstStart", 0))
        end_ms = int(subtitle.get("dstEnd", 0))
        text = str(subtitle.get("text") or "").strip()
        overlap_start = max(start_ms, interval_start_ms)
        overlap_end = min(end_ms, interval_end_ms)
        if not text or overlap_end <= overlap_start:
            continue
        rows.append(str(index))
        rows.append(f"{srt_timestamp(overlap_start - interval_start_ms)} --> {srt_timestamp(overlap_end - interval_start_ms)}")
        rows.append(escape_srt_text(text))
        rows.append("")
        index += 1
    if not rows:
        return False
    path.write_text("\n".join(rows), encoding="utf-8")
    return True


def ffmpeg_filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def default_font_path() -> Path:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    raise ValueError("no usable fontfile found for ffmpeg drawtext")


def add_drawtext_filters(
    vf: str,
    subtitles: list[dict],
    interval_start_ms: int,
    interval_end_ms: int,
    text_dir: Path,
    height: int,
) -> str:
    filters = [vf] if vf else []
    font_size = max(24, int(height * 0.045))
    margin_y = max(80, int(height * 0.12))
    font_path = default_font_path()
    index = 1
    for subtitle in subtitles:
        start_ms = int(subtitle.get("dstStart", 0))
        end_ms = int(subtitle.get("dstEnd", 0))
        text = str(subtitle.get("text") or "").strip()
        overlap_start = max(start_ms, interval_start_ms)
        overlap_end = min(end_ms, interval_end_ms)
        if not text or overlap_end <= overlap_start:
            continue
        text_path = text_dir / f"subtitle-{interval_start_ms}-{index:04d}.txt"
        text_path.write_text(escape_srt_text(text), encoding="utf-8")
        start_sec = (overlap_start - interval_start_ms) / 1000.0
        end_sec = (overlap_end - interval_start_ms) / 1000.0
        filters.append(
            "drawtext="
            f"fontfile='{ffmpeg_filter_path(font_path)}':"
            f"textfile='{ffmpeg_filter_path(text_path)}':"
            "fontcolor=white:"
            f"fontsize={font_size}:"
            "borderw=3:"
            "bordercolor=black:"
            "x=(w-text_w)/2:"
            f"y=h-{margin_y}:"
            f"enable='between(t,{start_sec:.3f},{end_sec:.3f})'"
        )
        index += 1
    return ",".join(filters)


def canvas_from_edl(edl: dict) -> dict:
    canvas = (edl.get("ui") or {}).get("canvas") or {}
    return {
        "width": int(canvas.get("width") or 1080),
        "height": int(canvas.get("height") or 1920),
        "aspect": canvas.get("aspect") or "9:16",
    }


def timeline_tracks(edl: dict) -> list[dict]:
    return ((edl.get("timeline") or {}).get("tracks") or [])


def track_clips(edl: dict, track_type: str) -> list[dict]:
    clips = []
    for track in timeline_tracks(edl):
        if track.get("type") == track_type:
            clips.extend(track.get("clips") or [])
    return sorted(clips, key=lambda clip: (int(clip.get("dstStart", 0)), int(clip.get("dstEnd", 0))))


def duration_ticks(edl: dict, video_clips: list[dict], audio_clips: list[dict], subtitle_clips: list[dict]) -> int:
    declared = int((edl.get("timeline") or {}).get("durationTicks") or 0)
    discovered = 0
    for clip in [*video_clips, *audio_clips, *subtitle_clips]:
        discovered = max(discovered, int(clip.get("dstEnd", 0)))
    return max(declared, discovered)


def asset_path(assets: dict, asset_id: str) -> Path:
    asset = assets.get(asset_id)
    if not asset:
        raise ValueError(f"unknown assetId: {asset_id}")
    path_raw = asset.get("sourcePath") or asset.get("path")
    if not path_raw:
        raise ValueError(f"asset has no sourcePath: {asset_id}")
    path = Path(path_raw).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"asset sourcePath does not exist: {path}")
    return path


def crop_scale_filter(rect: dict, width: int, height: int) -> str:
    return f"crop=iw*{rect['width']}:ih*{rect['height']}:iw*{rect['x']}:ih*{rect['y']},scale={width}:{height}"


def cover_filter(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"


def speaker_crop_filter(placement: dict, width: int, height: int) -> str:
    rect = placement.get("cropRect")
    return crop_scale_filter(rect, width, height) if rect else cover_filter(width, height)


def blurred_background_filter(placement: dict, width: int, height: int) -> str:
    rect = placement.get("cropRect")
    if not rect:
        return cover_filter(width, height)
    fg_width = int(width * 0.92)
    return (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=24:2[bg];"
        f"[0:v]{crop_scale_filter(rect, fg_width, -2)}[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )


def dialogue_stack_filter(placement: dict, width: int, height: int) -> str:
    layout = placement.get("layout") or {}
    panels = layout.get("panels") or []
    if len(panels) < 2:
        return speaker_crop_filter(placement, width, height)
    top_rect = panels[0].get("cropRect") or placement.get("cropRect")
    bottom_rect = panels[1].get("cropRect") or placement.get("cropRect")
    if not top_rect or not bottom_rect:
        return speaker_crop_filter(placement, width, height)
    panel_h = height // 2
    return (
        f"[0:v]{crop_scale_filter(top_rect, width, panel_h)}[top];"
        f"[0:v]{crop_scale_filter(bottom_rect, width, height - panel_h)}[bottom];"
        f"[top][bottom]vstack=inputs=2"
    )


def video_filter_for_clip(clip: dict, width: int, height: int) -> tuple[str, bool]:
    placement = clip.get("placement") or {}
    mode = str(placement.get("portraitMode") or placement.get("mode") or "")
    if mode == "blurred_background":
        return blurred_background_filter(placement, width, height), True
    if mode == "dialogue_stack":
        return dialogue_stack_filter(placement, width, height), True
    return speaker_crop_filter(placement, width, height), False


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def render_video_clip(
    ffmpeg: str,
    assets: dict,
    clip: dict,
    canvas: dict,
    subtitles: list[dict],
    output_path: Path,
    burn_subtitles: bool,
) -> None:
    source_path = asset_path(assets, str(clip.get("assetId") or ""))
    src_in_ms = int(clip.get("srcIn") or 0)
    dst_start_ms = int(clip["dstStart"])
    dst_end_ms = int(clip["dstEnd"])
    duration_ms = max(1, dst_end_ms - dst_start_ms)
    width = int(canvas["width"])
    height = int(canvas["height"])
    vf, complex_filter = video_filter_for_clip(clip, width, height)
    if burn_subtitles:
        vf = add_drawtext_filters(vf, subtitles, dst_start_ms, dst_end_ms, output_path.parent, height)
    command = [
        ffmpeg,
        "-y",
        "-ss", f"{src_in_ms / 1000.0:.3f}",
        "-i", str(source_path),
        "-t", f"{duration_ms / 1000.0:.3f}",
    ]
    command.extend(["-filter_complex" if complex_filter else "-vf", vf])
    command.extend([
        "-an",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ])
    run(command)


def render_black_video(
    ffmpeg: str,
    canvas: dict,
    start_ms: int,
    end_ms: int,
    subtitles: list[dict],
    output_path: Path,
    burn_subtitles: bool,
    fps: int,
) -> None:
    width = int(canvas["width"])
    height = int(canvas["height"])
    duration_ms = max(1, end_ms - start_ms)
    vf = ""
    if burn_subtitles:
        vf = add_drawtext_filters(vf, subtitles, start_ms, end_ms, output_path.parent, height)
    command = [
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={width}x{height}:r={fps}",
        "-t", f"{duration_ms / 1000.0:.3f}",
    ]
    if vf:
        command.extend(["-vf", vf])
    command.extend([
        "-an",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ])
    run(command)


def concat_files(ffmpeg: str, segment_paths: list[Path], output_path: Path, copy_streams: bool = True) -> None:
    concat_path = output_path.with_suffix(".concat.txt")
    rows = [f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for path in segment_paths]
    concat_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    command = [
        ffmpeg,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_path),
    ]
    command.extend(["-c", "copy"] if copy_streams else ["-c:v", "libx264", "-c:a", "aac"])
    if output_path.suffix.lower() == ".mp4":
        command.extend(["-movflags", "+faststart"])
    command.append(str(output_path))
    run(command)


def render_video_timeline(
    ffmpeg: str,
    edl: dict,
    canvas: dict,
    assets: dict,
    video_clips: list[dict],
    subtitle_clips: list[dict],
    duration_ms: int,
    temp_dir: Path,
    burn_subtitles: bool,
) -> Path:
    fps = int((edl.get("timebase") or {}).get("fps") or 30)
    segment_paths = []
    cursor = 0
    segment_index = 1
    for clip in video_clips:
        dst_start = int(clip["dstStart"])
        dst_end = int(clip["dstEnd"])
        if dst_start > cursor:
            gap_path = temp_dir / f"video-{segment_index:04d}-gap.mp4"
            render_black_video(ffmpeg, canvas, cursor, dst_start, subtitle_clips, gap_path, burn_subtitles, fps)
            segment_paths.append(gap_path)
            segment_index += 1
        segment_path = temp_dir / f"video-{segment_index:04d}.mp4"
        render_video_clip(ffmpeg, assets, clip, canvas, subtitle_clips, segment_path, burn_subtitles)
        segment_paths.append(segment_path)
        cursor = max(cursor, dst_end)
        segment_index += 1
    if cursor < duration_ms:
        gap_path = temp_dir / f"video-{segment_index:04d}-tail.mp4"
        render_black_video(ffmpeg, canvas, cursor, duration_ms, subtitle_clips, gap_path, burn_subtitles, fps)
        segment_paths.append(gap_path)
    if not segment_paths:
        raise ValueError("EDL has no video segments to export")
    timeline_video_path = temp_dir / "timeline-video.mp4"
    concat_files(ffmpeg, segment_paths, timeline_video_path)
    return timeline_video_path


def render_audio_clip(ffmpeg: str, assets: dict, clip: dict, output_path: Path) -> None:
    source_path = asset_path(assets, str(clip.get("assetId") or ""))
    src_in_ms = int(clip.get("srcIn") or 0)
    duration_ms = max(1, int(clip["dstEnd"]) - int(clip["dstStart"]))
    run([
        ffmpeg,
        "-y",
        "-ss", f"{src_in_ms / 1000.0:.3f}",
        "-i", str(source_path),
        "-t", f"{duration_ms / 1000.0:.3f}",
        "-vn",
        "-ac", "2",
        "-ar", "48000",
        "-c:a", "pcm_s16le",
        str(output_path),
    ])


def render_silence(ffmpeg: str, duration_ms: int, output_path: Path) -> None:
    run([
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", f"{max(1, duration_ms) / 1000.0:.3f}",
        "-c:a", "pcm_s16le",
        str(output_path),
    ])


def render_audio_timeline(ffmpeg: str, assets: dict, audio_clips: list[dict], duration_ms: int, temp_dir: Path) -> Path | None:
    if not audio_clips:
        return None
    segment_paths = []
    cursor = 0
    segment_index = 1
    for clip in audio_clips:
        dst_start = int(clip["dstStart"])
        dst_end = int(clip["dstEnd"])
        if dst_start > cursor:
            gap_path = temp_dir / f"audio-{segment_index:04d}-gap.wav"
            render_silence(ffmpeg, dst_start - cursor, gap_path)
            segment_paths.append(gap_path)
            segment_index += 1
        segment_path = temp_dir / f"audio-{segment_index:04d}.wav"
        render_audio_clip(ffmpeg, assets, clip, segment_path)
        segment_paths.append(segment_path)
        cursor = max(cursor, dst_end)
        segment_index += 1
    if cursor < duration_ms:
        gap_path = temp_dir / f"audio-{segment_index:04d}-tail.wav"
        render_silence(ffmpeg, duration_ms - cursor, gap_path)
        segment_paths.append(gap_path)
    audio_path = temp_dir / "timeline-audio.wav"
    concat_files(ffmpeg, segment_paths, audio_path)
    return audio_path


def mux_output(ffmpeg: str, video_path: Path, audio_path: Path | None, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if audio_path:
        run([
            ffmpeg,
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ])
    else:
        shutil.copyfile(video_path, output_path)


def main() -> int:
    try:
        payload = read_input()
        edl, edl_path = load_edl(payload)
        if edl.get("kind") != "wowclip.timeline.v1":
            raise ValueError("wowclip-export.py only supports wowclip.timeline.v1 edl.json")
        assets = edl.get("assets") or {}
        canvas = canvas_from_edl(edl)
        video_clips = [clip for clip in track_clips(edl, "video") if clip.get("kind") != "subtitle"]
        audio_clips = [clip for clip in track_clips(edl, "audio") if clip.get("kind") != "subtitle"]
        subtitle_clips = track_clips(edl, "subtitle")
        duration_ms = duration_ticks(edl, video_clips, audio_clips, subtitle_clips)
        if duration_ms <= 0:
            raise ValueError("EDL duration is zero")
        if not video_clips:
            raise ValueError("EDL has no video clips")
        default_output = (edl_path.parent / "exports" / "final.mp4") if edl_path else Path("exports/final.mp4").resolve()
        output_path = Path(payload.get("outputPath") or default_output).expanduser().resolve()
        ffmpeg = payload.get("ffmpegPath") or shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("ffmpeg is required")
        burn_subtitles = bool(payload.get("burnSubtitles", True))
        with tempfile.TemporaryDirectory(prefix="wowclip-export-edl-") as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            video_path = render_video_timeline(ffmpeg, edl, canvas, assets, video_clips, subtitle_clips, duration_ms, temp_dir, burn_subtitles)
            audio_path = render_audio_timeline(ffmpeg, assets, audio_clips, duration_ms, temp_dir)
            mux_output(ffmpeg, video_path, audio_path, output_path)
        print(json.dumps({
            "ok": True,
            "edlPath": str(edl_path) if edl_path else "",
            "outputPath": str(output_path),
            "durationMs": duration_ms,
            "videoClipCount": len(video_clips),
            "audioClipCount": len(audio_clips),
            "subtitleClipCount": len(subtitle_clips),
            "burnSubtitles": burn_subtitles,
        }, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
