#!/usr/bin/env python3
"""Local transcription wrapper for faster-whisper or whisper.cpp."""

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


def srt_timestamp(ms: int) -> str:
    ms = max(0, int(ms))
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def write_srt(path: Path, segments: list[dict]) -> None:
    rows = []
    for index, segment in enumerate(segments, start=1):
        rows.append(str(index))
        rows.append(f"{srt_timestamp(segment['startMs'])} --> {srt_timestamp(segment['endMs'])}")
        rows.append(segment["text"])
        rows.append("")
    path.write_text("\n".join(rows), encoding="utf-8")


def normalize_words(segment: dict, segment_index: int) -> list[dict]:
    words = []
    for word_index, word in enumerate(segment.get("words") or [], start=1):
        start_ms = int(word.get("startMs", round(float(word.get("start", segment.get("startMs", 0) / 1000)) * 1000)))
        end_ms = int(word.get("endMs", round(float(word.get("end", segment.get("endMs", 0) / 1000)) * 1000)))
        token = str(word.get("word") or word.get("text") or "").strip()
        if token and end_ms > start_ms:
            words.append({
                "id": word.get("id") or f"seg-{segment_index:04d}-w{word_index:03d}",
                "startMs": start_ms,
                "endMs": end_ms,
                "word": token,
            })
    return words


def should_split_after(text: str) -> bool:
    return text.rstrip().endswith((".", "?", "!", "。", "？", "！", ";", "；"))


def compact_text(tokens: list[str]) -> str:
    text = "".join(tokens)
    if " " in " ".join(tokens):
        text = " ".join(token.strip() for token in tokens if token.strip())
    return text.strip()


def split_words_into_engineered_entries(words: list[dict], max_chars: int, max_ms: int, max_gap_ms: int) -> list[dict]:
    entries = []
    current = []
    for word in words:
        if current:
            gap_ms = int(word["startMs"]) - int(current[-1]["endMs"])
            candidate_text = compact_text([item["word"] for item in current] + [word["word"]])
            current_duration = int(word["endMs"]) - int(current[0]["startMs"])
            if gap_ms > max_gap_ms or len(candidate_text) > max_chars or current_duration > max_ms or should_split_after(current[-1]["word"]):
                entries.append({
                    "startMs": int(current[0]["startMs"]),
                    "endMs": int(current[-1]["endMs"]),
                    "text": compact_text([item["word"] for item in current]),
                    "words": current,
                })
                current = []
        current.append(word)
    if current:
        entries.append({
            "startMs": int(current[0]["startMs"]),
            "endMs": int(current[-1]["endMs"]),
            "text": compact_text([item["word"] for item in current]),
            "words": current,
        })
    return entries


def split_text_segment(segment: dict, max_chars: int, max_ms: int) -> list[dict]:
    text = str(segment.get("text") or "").strip()
    if not text:
        return []
    start_ms = int(segment["startMs"])
    end_ms = int(segment["endMs"])
    duration_ms = max(1, end_ms - start_ms)
    chunks = []
    cursor = 0
    while cursor < len(text):
        chunk = text[cursor:cursor + max_chars].strip()
        if not chunk:
            cursor += max_chars
            continue
        chunks.append(chunk)
        cursor += max_chars
    if not chunks:
        return []
    entries = []
    for index, chunk in enumerate(chunks):
        chunk_start = start_ms + round(duration_ms * index / len(chunks))
        chunk_end = start_ms + round(duration_ms * (index + 1) / len(chunks))
        entries.append({"startMs": chunk_start, "endMs": max(chunk_start + 1, chunk_end), "text": chunk, "words": []})
    return entries


def build_engineered_subtitles(segments: list[dict], max_chars: int = 26, max_ms: int = 6000, max_gap_ms: int = 1000) -> list[dict]:
    entries = []
    for segment in segments:
        words = segment.get("words") or []
        split_entries = split_words_into_engineered_entries(words, max_chars, max_ms, max_gap_ms) if words else split_text_segment(segment, max_chars, max_ms)
        for entry in split_entries:
            if entry["endMs"] > entry["startMs"] and entry["text"]:
                entry["id"] = f"sub-{len(entries) + 1:04d}"
                entries.append(entry)
    return entries


def write_words_srt(path: Path, segments: list[dict]) -> None:
    rows = []
    index = 1
    for segment in segments:
        for word in segment.get("words") or []:
            rows.append(str(index))
            rows.append(f"{srt_timestamp(word['startMs'])} --> {srt_timestamp(word['endMs'])}")
            rows.append(str(word["word"]).strip())
            rows.append("")
            index += 1
    path.write_text("\n".join(rows), encoding="utf-8")


def write_dense_words(path: Path, segments: list[dict]) -> None:
    rows = ["segmentId\twordId\tstartMs\tendMs\tword"]
    for segment in segments:
        for word in segment.get("words") or []:
            token = str(word["word"]).replace("\t", " ").replace("\n", " ").strip()
            rows.append(f"{segment['id']}\t{word['id']}\t{word['startMs']}\t{word['endMs']}\t{token}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    payload = read_input()
    source_path = Path(payload.get("sourcePath") or payload.get("path") or "").expanduser().resolve()
    if not source_path.exists():
        print(json.dumps({"ok": False, "error": "sourcePath does not exist"}, indent=2))
        return 1
    project_root = Path(payload.get("projectRootDir") or source_path.parent).expanduser().resolve()
    transcripts_dir = project_root / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    stem = source_path.stem
    audio_path = transcripts_dir / f"{stem}.wav"
    json_path = transcripts_dir / f"{stem}.json"
    srt_path = transcripts_dir / f"{stem}.srt"
    liveclipper_dir = project_root / "LiveClipper"
    subtitles_dir = liveclipper_dir / "subtitles"

    ffmpeg = payload.get("ffmpegPath") or shutil.which("ffmpeg")
    if not ffmpeg:
        print(json.dumps({"ok": False, "error": "ffmpeg is required"}, indent=2))
        return 1
    subprocess.run([ffmpeg, "-y", "-i", str(source_path), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)], check=True)

    segments = payload.get("segments") or []
    if not segments:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception:
            print(json.dumps({
                "ok": False,
                "error": "faster-whisper is not installed and no segments were provided",
                "audioPath": str(audio_path),
                "install": "pip install faster-whisper",
            }, ensure_ascii=False, indent=2))
            return 1

        model_name = payload.get("model") or "large-v3-turbo"
        compute_type = payload.get("computeType") or "auto"
        model = WhisperModel(model_name, device=payload.get("device") or "auto", compute_type=compute_type)
        result_segments, info = model.transcribe(str(audio_path), language=payload.get("language") or None, vad_filter=True, word_timestamps=True)
        segments = [
            {
                "id": f"seg-{index:04d}",
                "startMs": int(round(segment.start * 1000)),
                "endMs": int(round(segment.end * 1000)),
                "text": segment.text.strip(),
                "words": [
                    {
                        "startMs": int(round(word.start * 1000)),
                        "endMs": int(round(word.end * 1000)),
                        "word": word.word,
                    }
                    for word in (segment.words or [])
                ],
            }
            for index, segment in enumerate(result_segments, start=1)
            if segment.text.strip()
        ]
    else:
        normalized = []
        for index, segment in enumerate(segments, start=1):
            start_ms = int(segment.get("startMs", round(float(segment.get("start", 0)) * 1000)))
            end_ms = int(segment.get("endMs", round(float(segment.get("end", 0)) * 1000)))
            text = str(segment.get("text", "")).strip()
            if text and end_ms > start_ms:
                normalized_segment = {"id": segment.get("id") or f"seg-{index:04d}", "startMs": start_ms, "endMs": end_ms, "text": text, "words": segment.get("words") or []}
                normalized_segment["words"] = normalize_words(normalized_segment, index)
                normalized.append(normalized_segment)
        segments = normalized

    for index, segment in enumerate(segments, start=1):
        segment["words"] = normalize_words(segment, index)
    engineered_entries = build_engineered_subtitles(segments, max_chars=int(payload.get("verticalMaxChars", 26)))
    subtitles_dir.mkdir(parents=True, exist_ok=True)
    merged_srt_path = subtitles_dir / "merged.srt"
    merged_words_srt_path = subtitles_dir / "merged_words.srt"
    dense_words_path = subtitles_dir / "merged_words_dense.tsv"
    workflow_state_path = liveclipper_dir / "workflow-state.json"

    json_path.write_text(json.dumps({"sourcePath": str(source_path), "segments": segments, "engineeredSubtitles": engineered_entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_srt(srt_path, engineered_entries)
    write_srt(merged_srt_path, engineered_entries)
    write_words_srt(merged_words_srt_path, segments)
    write_dense_words(dense_words_path, segments)
    workflow_state_path.write_text(json.dumps({
        "sourcePath": str(source_path),
        "subtitles": {
            "rawTranscriptPath": str(json_path),
            "mergedSRTPath": str(merged_srt_path),
            "mergedWordsSRTPath": str(merged_words_srt_path),
            "mergedWordsDenseTSVPath": str(dense_words_path),
            "entryCount": len(engineered_entries),
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "audioPath": str(audio_path),
        "jsonPath": str(json_path),
        "srtPath": str(srt_path),
        "mergedSRTPath": str(merged_srt_path),
        "mergedWordsSRTPath": str(merged_words_srt_path),
        "mergedWordsDenseTSVPath": str(dense_words_path),
        "workflowStatePath": str(workflow_state_path),
        "segmentCount": len(segments),
        "subtitleEntryCount": len(engineered_entries),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
