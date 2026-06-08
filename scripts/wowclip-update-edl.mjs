#!/usr/bin/env node
import { absPath, readJsonFile, readJsonInput, validateTimeline, writeJson, writeJsonFile } from "./wowclip-common.mjs";

function runTransform(script, edl) {
  const fn = new Function("edl", `"use strict";\n${script}`);
  const cloned = JSON.parse(JSON.stringify(edl));
  const result = fn(cloned);
  return result === undefined ? cloned : result;
}

function normalizeEDL(edl, nextVersion) {
  const normalized = JSON.parse(JSON.stringify(edl));
  normalized.kind = "cutpilot.timeline.v1";
  normalized.schemaVersion = Math.max(2, Number(normalized.schemaVersion || 2));
  normalized.version = nextVersion;
  normalized.timeline ||= {};
  normalized.timeline.tracks ||= [];
  normalized.timeline.durationTicks = Math.max(
    Number(normalized.timeline.durationTicks || 0),
    ...normalized.timeline.tracks.flatMap((track) => (track.clips || []).map((clip) => Number(clip.dstEnd || 0))),
  );
  normalized.timebase ||= { fps: 30, ticksPerSecond: 1000, tcStartTicks: 0 };
  normalized.timebase.ticksPerSecond ||= 1000;
  normalized.timebase.fps ||= 30;
  normalized.ui ||= {};
  normalized.ui.canvas ||= { width: 1080, height: 1920, aspect: "9:16" };
  return normalized;
}

try {
  const input = await readJsonInput();
  const edlPath = absPath(input.edlPath || "edl.json", input.projectRootDir || process.cwd());
  const script = String(input.script || "").trim();
  if (!script) throw new Error("script is required");
  if (!Number.isInteger(input.baseVersion)) throw new Error("baseVersion is required");
  const current = await readJsonFile(edlPath);
  if (current.kind !== "cutpilot.timeline.v1") throw new Error("edl must be cutpilot.timeline.v1");
  if (Number(current.version || 0) !== input.baseVersion) {
    throw new Error(`EDL_VERSION_CONFLICT: expected ${current.version || 0}, got ${input.baseVersion}`);
  }
  const updated = normalizeEDL(runTransform(script, current), Number(current.version || 0) + 1);
  const errors = validateTimeline(updated);
  if (errors.length > 0) {
    writeJson({ ok: false, errors });
    process.exitCode = 1;
  } else {
    await writeJsonFile(edlPath, updated);
    writeJson({
      ok: true,
      edlPath,
      previousVersion: Number(current.version || 0),
      version: updated.version,
      summary: input.summary || "Update EDL",
    });
  }
} catch (error) {
  writeJson({ ok: false, error: String(error?.message || error) });
  process.exitCode = 1;
}
