#!/usr/bin/env node
import path from "node:path";
import { absPath, readJsonInput, run, writeJson } from "./wowclip-common.mjs";

try {
  const input = await readJsonInput();
  const sourcePath = absPath(input.path || input.sourcePath);
  if (!sourcePath) throw new Error("path is required");
  const ffprobe = input.ffprobePath || process.env.FFPROBE_PATH || "ffprobe";
  const { stdout } = await run(ffprobe, [
    "-v", "error",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
    sourcePath,
  ]);
  const probe = JSON.parse(stdout || "{}");
  const streams = Array.isArray(probe.streams) ? probe.streams : [];
  const format = probe.format && typeof probe.format === "object" ? probe.format : {};
  const video = streams.find((stream) => stream.codec_type === "video") || null;
  const audio = streams.find((stream) => stream.codec_type === "audio") || null;
  const durationSec = Number(format.duration || video?.duration || audio?.duration || 0) || 0;
  const rateRaw = String(video?.avg_frame_rate || video?.r_frame_rate || "0/0");
  const [num, den] = rateRaw.split("/").map((value) => Number(value || 0));
  const fps = num > 0 && den > 0 ? num / den : 0;
  const ext = path.extname(sourcePath).toLowerCase();
  const type = video ? "video" : audio ? "audio" : [".jpg", ".jpeg", ".png", ".webp"].includes(ext) ? "image" : "file";
  writeJson({
    ok: true,
    path: sourcePath,
    type,
    durationMs: Math.round(durationSec * 1000),
    width: Number(video?.width || 0) || 0,
    height: Number(video?.height || 0) || 0,
    fps,
    size: Number(format.size || 0) || 0,
    videoCodec: String(video?.codec_name || ""),
    audioCodec: String(audio?.codec_name || ""),
  });
} catch (error) {
  writeJson({ ok: false, error: String(error?.message || error) });
  process.exitCode = 1;
}

