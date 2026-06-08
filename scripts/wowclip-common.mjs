import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

export async function readJsonInput() {
  const arg = process.argv.slice(2).join(" ").trim();
  if (arg) return JSON.parse(arg);
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString("utf8").trim();
  return text ? JSON.parse(text) : {};
}

export function writeJson(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

export function absPath(filePath, baseDir = process.cwd()) {
  const raw = String(filePath || "").trim();
  if (!raw) return "";
  return path.isAbsolute(raw) ? path.resolve(raw) : path.resolve(baseDir, raw);
}

export async function readJsonFile(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

export async function writeJsonFile(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

export async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
  return dirPath;
}

export function msToTicks(ms, ticksPerSecond = 1000) {
  return Math.round((Math.max(0, Number(ms) || 0) / 1000) * ticksPerSecond);
}

export function ticksToMs(ticks, ticksPerSecond = 1000) {
  return Math.round((Math.max(0, Number(ticks) || 0) / ticksPerSecond) * 1000);
}

export async function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd || process.cwd(),
      env: options.env || process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", reject);
    child.on("close", (code) => {
      const result = {
        code,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
      };
      if (code === 0) resolve(result);
      else {
        const error = new Error(`${command} failed with code ${code}: ${result.stderr || result.stdout}`);
        error.result = result;
        reject(error);
      }
    });
  });
}

export function validateTimeline(timeline) {
  const errors = [];
  const add = (code, message, pathValue = "") => errors.push({ code, message, path: pathValue });
  if (!timeline || typeof timeline !== "object" || Array.isArray(timeline)) {
    return [{ code: "TIMELINE_NOT_OBJECT", message: "timeline must be an object", path: "" }];
  }
  const isWowClipEDL = timeline.kind === "wowclip.timeline.v1";
  const isLegacyWowClipTimeline = timeline.schema === "wowclip.timeline.v1";
  if (!isWowClipEDL && !isLegacyWowClipTimeline) {
    add("INVALID_SCHEMA", "timeline must be wowclip.timeline.v1 edl.json", "/kind");
  }
  if (isWowClipEDL && (!Number.isInteger(timeline.schemaVersion) || timeline.schemaVersion < 2)) {
    add("INVALID_SCHEMA_VERSION", "schemaVersion must be integer >= 2", "/schemaVersion");
  }
  if (!Number.isInteger(timeline.version) || timeline.version < 0) add("INVALID_VERSION", "version must be a non-negative integer", "/version");
  const ticksPerSecond = Number(timeline.timebase?.ticksPerSecond || 0);
  if (!Number.isInteger(ticksPerSecond) || ticksPerSecond <= 0) add("INVALID_TIMEBASE", "timebase.ticksPerSecond must be positive", "/timebase/ticksPerSecond");
  if (!(Number(timeline.timebase?.fps || 0) > 0)) add("INVALID_FPS", "timebase.fps must be positive", "/timebase/fps");
  const canvas = isWowClipEDL ? timeline.ui?.canvas : timeline.canvas;
  if (!(Number(canvas?.width || 0) > 0)) add("INVALID_CANVAS_WIDTH", "canvas.width must be positive", isWowClipEDL ? "/ui/canvas/width" : "/canvas/width");
  if (!(Number(canvas?.height || 0) > 0)) add("INVALID_CANVAS_HEIGHT", "canvas.height must be positive", isWowClipEDL ? "/ui/canvas/height" : "/canvas/height");
  const assets = timeline.assets && typeof timeline.assets === "object" && !Array.isArray(timeline.assets) ? timeline.assets : null;
  if (!assets) add("INVALID_ASSETS", "assets must be an object", "/assets");
  const tracksPath = isWowClipEDL ? "/timeline/tracks" : "/tracks";
  const durationPath = isWowClipEDL ? "/timeline/durationTicks" : "/durationTicks";
  const tracks = Array.isArray(isWowClipEDL ? timeline.timeline?.tracks : timeline.tracks)
    ? (isWowClipEDL ? timeline.timeline.tracks : timeline.tracks)
    : null;
  if (!tracks) add("INVALID_TRACKS", "tracks must be an array", tracksPath);
  const durationTicks = Number(isWowClipEDL ? timeline.timeline?.durationTicks || 0 : timeline.durationTicks || 0);
  if (!Number.isInteger(durationTicks) || durationTicks < 0) add("INVALID_DURATION", "durationTicks must be non-negative", durationPath);

  if (tracks) {
    tracks.forEach((track, trackIndex) => {
      const trackPath = `${tracksPath}/${trackIndex}`;
      if (!track || typeof track !== "object") {
        add("INVALID_TRACK", "track must be an object", trackPath);
        return;
      }
      const trackType = String(track.type || "");
      if (!Array.isArray(track.clips)) add("INVALID_CLIPS", "track.clips must be an array", `${trackPath}/clips`);
      const clips = Array.isArray(track.clips) ? track.clips : [];
      clips.forEach((clip, clipIndex) => {
        const clipPath = `${trackPath}/clips/${clipIndex}`;
        const start = Number(clip?.dstStart);
        const end = Number(clip?.dstEnd);
        if (!Number.isInteger(start) || start < 0) add("INVALID_CLIP_START", "clip.dstStart must be a non-negative integer", `${clipPath}/dstStart`);
        if (!Number.isInteger(end) || end <= start) add("INVALID_CLIP_END", "clip.dstEnd must be greater than dstStart", `${clipPath}/dstEnd`);
        if (durationTicks > 0 && end > durationTicks) add("CLIP_EXCEEDS_DURATION", "clip.dstEnd exceeds durationTicks", `${clipPath}/dstEnd`);
        if (clip?.kind === "subtitle" || trackType === "subtitle") {
          if (typeof clip.text !== "string" || !clip.text.trim()) add("INVALID_SUBTITLE_TEXT", "subtitle text is required", `${clipPath}/text`);
        } else {
          const assetId = String(clip?.assetId || "").trim();
          if (!assetId) add("MISSING_ASSET_ID", "media clip assetId is required", `${clipPath}/assetId`);
          else if (assets && !assets[assetId]) add("UNKNOWN_ASSET_ID", `unknown asset ${assetId}`, `${clipPath}/assetId`);
          if (clip?.srcIn !== undefined || clip?.srcOut !== undefined) {
            const srcIn = Number(clip?.srcIn);
            const srcOut = Number(clip?.srcOut);
            if (!Number.isInteger(srcIn) || srcIn < 0) add("INVALID_SRC_IN", "clip.srcIn must be a non-negative integer", `${clipPath}/srcIn`);
            if (!Number.isInteger(srcOut) || srcOut <= srcIn) add("INVALID_SRC_OUT", "clip.srcOut must be greater than srcIn", `${clipPath}/srcOut`);
          }
        }
      });
      if (trackType === "video" || trackType === "audio") {
        const ordered = clips
          .map((clip, index) => ({ index, start: Number(clip?.dstStart), end: Number(clip?.dstEnd) }))
          .filter((clip) => Number.isInteger(clip.start) && Number.isInteger(clip.end))
          .sort((a, b) => a.start - b.start || a.end - b.end);
        for (let index = 1; index < ordered.length; index += 1) {
          if (ordered[index].start < ordered[index - 1].end) {
            add("TRACK_CLIP_OVERLAP", "video/audio clips must not overlap on the same track", `${trackPath}/clips/${ordered[index].index}`);
          }
        }
      }
    });
  }
  return errors;
}

export function validatePortraitPlan(plan) {
  const errors = [];
  const add = (code, message, pathValue = "") => errors.push({ code, message, path: pathValue });
  if (!plan || typeof plan !== "object" || Array.isArray(plan)) {
    return [{ code: "PLAN_NOT_OBJECT", message: "plan must be an object", path: "" }];
  }
  if (plan.schema !== "wowclip.portrait-plan.v1") add("INVALID_SCHEMA", "schema must be wowclip.portrait-plan.v1", "/schema");
  if (!String(plan.assetId || "").trim()) add("MISSING_ASSET_ID", "assetId is required", "/assetId");
  if (!(Number(plan.target?.width || 0) > 0)) add("INVALID_TARGET_WIDTH", "target.width must be positive", "/target/width");
  if (!(Number(plan.target?.height || 0) > 0)) add("INVALID_TARGET_HEIGHT", "target.height must be positive", "/target/height");
  if (!Array.isArray(plan.ranges)) add("INVALID_RANGES", "ranges must be an array", "/ranges");
  (Array.isArray(plan.ranges) ? plan.ranges : []).forEach((range, index) => {
    const rangePath = `/ranges/${index}`;
    if (!Number.isInteger(range.startMs) || range.startMs < 0) add("INVALID_START_MS", "startMs must be non-negative integer", `${rangePath}/startMs`);
    if (!Number.isInteger(range.endMs) || range.endMs <= range.startMs) add("INVALID_END_MS", "endMs must be greater than startMs", `${rangePath}/endMs`);
    const rect = range.cropRect;
    if (!rect || typeof rect !== "object") {
      add("INVALID_CROP_RECT", "cropRect is required", `${rangePath}/cropRect`);
      return;
    }
    for (const key of ["x", "y", "width", "height"]) {
      if (!(Number(rect[key]) >= 0)) add("INVALID_CROP_RECT_VALUE", `cropRect.${key} must be numeric`, `${rangePath}/cropRect/${key}`);
    }
    if (Number(rect.x) + Number(rect.width) > 1.000001) add("CROP_RECT_OUT_OF_BOUNDS", "cropRect x + width exceeds 1", `${rangePath}/cropRect`);
    if (Number(rect.y) + Number(rect.height) > 1.000001) add("CROP_RECT_OUT_OF_BOUNDS", "cropRect y + height exceeds 1", `${rangePath}/cropRect`);
  });
  return errors;
}
