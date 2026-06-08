#!/usr/bin/env node
import { absPath, readJsonFile, readJsonInput, validatePortraitPlan, validateTimeline, writeJson } from "./wowclip-common.mjs";

try {
  const input = await readJsonInput();
  const timelinePath = input.edlPath || input.timelinePath || "";
  const timeline = input.edl || input.timeline || (timelinePath ? await readJsonFile(absPath(timelinePath)) : null);
  const portraitPlan = input.portraitPlan || (input.portraitPlanPath ? await readJsonFile(absPath(input.portraitPlanPath)) : null);
  const timelineErrors = timeline ? validateTimeline(timeline) : [];
  const portraitPlanErrors = portraitPlan ? validatePortraitPlan(portraitPlan) : [];
  if (!timeline && !portraitPlan) throw new Error("edl/edlPath, timeline/timelinePath, or portraitPlan/portraitPlanPath is required");
  const isWowClipEDL = timeline?.kind === "wowclip.timeline.v1";
  const tracks = isWowClipEDL ? timeline?.timeline?.tracks : timeline?.tracks;
  const errors = [...timelineErrors, ...portraitPlanErrors];
  writeJson({
    ok: errors.length === 0,
    errors,
    timeline: timeline ? {
      kind: timeline.kind || timeline.schema,
      version: timeline.version,
      durationTicks: isWowClipEDL ? timeline.timeline?.durationTicks : timeline.durationTicks,
      assetCount: timeline.assets ? Object.keys(timeline.assets).length : 0,
      trackCount: Array.isArray(tracks) ? tracks.length : 0,
    } : null,
    portraitPlan: portraitPlan ? {
      assetId: portraitPlan.assetId,
      rangeCount: Array.isArray(portraitPlan.ranges) ? portraitPlan.ranges.length : 0,
    } : null,
  });
  if (errors.length > 0) process.exitCode = 1;
} catch (error) {
  writeJson({ ok: false, errors: [{ code: "VALIDATE_FAILED", message: String(error?.message || error), path: "" }] });
  process.exitCode = 1;
}
