#!/usr/bin/env node
import { absPath, msToTicks, readJsonFile, readJsonInput, validatePortraitPlan, validateTimeline, writeJson, writeJsonFile } from "./wowclip-common.mjs";

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function applyPlanToClip(clip, range, ticksPerSecond) {
  const startTicks = msToTicks(range.startMs, ticksPerSecond);
  const endTicks = msToTicks(range.endMs, ticksPerSecond);
  const overlaps = clip.dstStart < endTicks && clip.dstEnd > startTicks;
  if (!overlaps) return clip;
  return {
    ...clip,
    placement: {
      ...(clip.placement && typeof clip.placement === "object" ? clip.placement : {}),
      fit: "cover",
      mode: "portrait_reframe",
      targetWidth: 1080,
      targetHeight: 1920,
      cropRect: range.cropRect,
      personLabel: range.selectedPersonLabel || "",
      confidence: Number(range.confidence || 0),
      reason: range.reason || "",
    },
  };
}

try {
  const input = await readJsonInput();
  const timelinePath = absPath(input.timelinePath || "timeline.json", input.projectRootDir);
  const planPath = absPath(input.portraitPlanPath || input.planPath || "", input.projectRootDir);
  if (!planPath) throw new Error("portraitPlanPath is required");
  const timeline = await readJsonFile(timelinePath);
  const plan = await readJsonFile(planPath);
  const planErrors = validatePortraitPlan(plan);
  if (planErrors.length > 0) {
    writeJson({ ok: false, errorCode: "PORTRAIT_PLAN_INVALID", errors: planErrors });
    process.exit(1);
  }
  const ticksPerSecond = Number(timeline.timebase?.ticksPerSecond || 1000);
  const next = clone(timeline);
  next.canvas = {
    ...(next.canvas || {}),
    width: Number(plan.target?.width || 1080),
    height: Number(plan.target?.height || 1920),
    aspectRatio: plan.target?.aspectRatio || "9:16",
  };
  for (const track of Array.isArray(next.tracks) ? next.tracks : []) {
    if (track.type !== "video") continue;
    track.clips = (Array.isArray(track.clips) ? track.clips : []).map((clip) => {
      if (clip.assetId !== plan.assetId) return clip;
      let updated = clip;
      for (const range of plan.ranges) updated = applyPlanToClip(updated, range, ticksPerSecond);
      return updated;
    });
  }
  next.version = Number(next.version || 0) + 1;
  const errors = validateTimeline(next);
  if (errors.length > 0) {
    writeJson({ ok: false, errorCode: "TIMELINE_INVALID", errors });
    process.exit(1);
  }
  await writeJsonFile(timelinePath, next);
  writeJson({ ok: true, timelinePath, version: next.version, appliedRanges: plan.ranges.length, assetId: plan.assetId });
} catch (error) {
  writeJson({ ok: false, error: String(error?.message || error) });
  process.exitCode = 1;
}

