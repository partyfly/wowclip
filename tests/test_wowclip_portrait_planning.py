import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class WowClipPortraitPlanningTests(unittest.TestCase):
    def test_detect_shots_merges_adjacent_frames_by_visual_diff(self):
        module = load_script("wowclip-detect-shots.py")
        frames = [
            {"timeMs": 0, "path": "f0.jpg", "visualDiff": 0.0},
            {"timeMs": 1000, "path": "f1.jpg", "visualDiff": 0.08},
            {"timeMs": 2000, "path": "f2.jpg", "visualDiff": 0.72},
            {"timeMs": 3000, "path": "f3.jpg", "visualDiff": 0.06},
        ]

        shots = module.shots_from_scored_frames(frames, end_ms=4000, threshold=0.45, min_duration_ms=500)

        self.assertEqual(shots, [
            {"id": "shot-0001", "startMs": 0, "endMs": 2000, "frameCount": 2},
            {"id": "shot-0002", "startMs": 2000, "endMs": 4000, "frameCount": 2},
        ])

    def test_detect_shots_uses_fused_cut_score_below_legacy_visual_threshold(self):
        module = load_script("wowclip-detect-shots.py")
        frames = [
            {"timeMs": 0, "path": "f0.jpg", "visualDiff": 0.0, "histogramDiff": 0.0, "hashDiff": 0.0, "edgeDiff": 0.0},
            {"timeMs": 1000, "path": "f1.jpg", "visualDiff": 0.08, "histogramDiff": 0.06, "hashDiff": 0.04, "edgeDiff": 0.05},
            {"timeMs": 2000, "path": "f2.jpg", "visualDiff": 0.34, "histogramDiff": 0.74, "hashDiff": 0.62, "edgeDiff": 0.51},
            {"timeMs": 3000, "path": "f3.jpg", "visualDiff": 0.06, "histogramDiff": 0.05, "hashDiff": 0.03, "edgeDiff": 0.04},
        ]

        scored = module.score_cut_confidence(frames)
        shots = module.shots_from_scored_frames(scored, end_ms=4000, threshold=0.42, min_duration_ms=500)

        self.assertGreater(scored[2]["cutConfidence"], 0.80)
        self.assertEqual([(shot["startMs"], shot["endMs"], shot.get("kind")) for shot in shots], [
            (0, 2000, "hard_cut"),
            (2000, 4000, None),
        ])
        self.assertEqual(shots[0]["confidence"], scored[2]["cutConfidence"])
        self.assertEqual(shots[0]["evidence"]["histogramDiff"], 0.74)

    def test_detect_shots_ignores_single_metric_spike_without_supporting_evidence(self):
        module = load_script("wowclip-detect-shots.py")
        frames = [
            {"timeMs": 0, "path": "f0.jpg", "visualDiff": 0.0, "histogramDiff": 0.0, "hashDiff": 0.0, "edgeDiff": 0.0},
            {"timeMs": 1000, "path": "f1.jpg", "visualDiff": 0.08, "histogramDiff": 0.05, "hashDiff": 0.04, "edgeDiff": 0.05},
            {"timeMs": 2000, "path": "f2.jpg", "visualDiff": 0.35, "histogramDiff": 0.08, "hashDiff": 0.05, "edgeDiff": 0.06},
            {"timeMs": 3000, "path": "f3.jpg", "visualDiff": 0.07, "histogramDiff": 0.04, "hashDiff": 0.03, "edgeDiff": 0.04},
        ]

        scored = module.score_cut_confidence(frames)
        shots = module.shots_from_scored_frames(scored, end_ms=4000, threshold=0.42, min_duration_ms=500)

        self.assertLess(scored[2]["cutConfidence"], 0.55)
        self.assertEqual(shots, [
            {"id": "shot-0001", "startMs": 0, "endMs": 4000, "frameCount": 4},
        ])

    def test_extract_frames_honors_requested_max_frames_for_shot_sampling(self):
        module = load_script("wowclip-extract-frames.py")

        times = module.default_times(0, 23000, 24)

        self.assertEqual(len(times), 24)
        self.assertEqual(times[0], 0)
        self.assertEqual(times[-1], 23000)

    def test_plan_portrait_splits_clip_ranges_by_shots(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detections_path = tmp_path / "detections.json"
            tracks_path = tmp_path / "tracks.json"
            shots_path = tmp_path / "shots.json"
            output_path = tmp_path / "plan.json"
            frame_path = str(tmp_path / "frame.jpg")
            detections_path.write_text(json.dumps({"detections": []}), encoding="utf-8")
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 1000, "box": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.2}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 2000, "box": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.2}, "score": 0.9, "framePath": frame_path},
                        ],
                    },
                    {
                        "label": "P2",
                        "detections": [
                            {"timeMs": 6000, "box": {"x": 0.75, "y": 0.2, "width": 0.1, "height": 0.2}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 7000, "box": {"x": 0.75, "y": 0.2, "width": 0.1, "height": 0.2}, "score": 0.9, "framePath": frame_path},
                        ],
                    },
                ]
            }), encoding="utf-8")
            shots_path.write_text(json.dumps({
                "shots": [
                    {"id": "shot-0001", "startMs": 0, "endMs": 5000},
                    {"id": "shot-0002", "startMs": 5000, "endMs": 10000},
                ]
            }), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-plan-portrait.py"),
                json.dumps({
                    "detectionsPath": str(detections_path),
                    "tracksPath": str(tracks_path),
                    "shotsPath": str(shots_path),
                    "ranges": [{"startMs": 0, "endMs": 10000}],
                    "outputPath": str(output_path),
                    "portraitMode": "speaker_crop",
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            ranges = plan["ranges"]
            self.assertEqual([(item["startMs"], item["endMs"], item["selectedPersonLabel"]) for item in ranges], [
                (1000, 5000, "P1"),
                (6000, 10000, "P2"),
            ])
            self.assertTrue(all(item["shotId"] for item in ranges))

    def test_plan_portrait_ignores_embedded_portrait_and_centers_tracked_face(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detections_path = tmp_path / "detections.json"
            tracks_path = tmp_path / "tracks.json"
            embedded_path = tmp_path / "embedded.json"
            output_path = tmp_path / "plan.json"
            frame_path = str(tmp_path / "frame.jpg")
            detections_path.write_text(json.dumps({"detections": []}), encoding="utf-8")
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 1000, "box": {"x": 0.70, "y": 0.18, "width": 0.10, "height": 0.22}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 2000, "box": {"x": 0.72, "y": 0.18, "width": 0.10, "height": 0.22}, "score": 0.9, "framePath": frame_path},
                        ],
                    }
                ]
            }), encoding="utf-8")
            embedded_path.write_text(json.dumps({
                "embeddedPortrait": {
                    "detected": True,
                    "confidence": 0.88,
                    "cropRect": {"x": 0.34, "y": 0.0, "width": 0.32, "height": 1.0},
                }
            }), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-plan-portrait.py"),
                json.dumps({
                    "detectionsPath": str(detections_path),
                    "tracksPath": str(tracks_path),
                    "embeddedPortraitPath": str(embedded_path),
                    "ranges": [{"startMs": 0, "endMs": 5000}],
                    "outputPath": str(output_path),
                    "portraitMode": "auto",
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            planned = plan["ranges"][0]
            self.assertEqual(planned["portraitMode"], "speaker_crop")
            self.assertEqual(planned["reason"], "tracked_face_hold_crop")
            self.assertEqual(planned["selectedPersonLabel"], "P1")
            self.assertNotEqual(planned["cropRect"], {"x": 0.34, "y": 0.0, "width": 0.32, "height": 1.0})
            self.assertAlmostEqual(planned["cropRect"]["width"], 0.31640625)
            self.assertAlmostEqual(planned["cropRect"]["height"], 1.0)
            face_center_x = 0.70 + 0.10 / 2
            crop_center_x = planned["cropRect"]["x"] + planned["cropRect"]["width"] / 2
            self.assertAlmostEqual(crop_center_x, face_center_x, places=6)
            self.assertFalse(plan["analysis"]["embeddedPortraitUsed"])

    def test_plan_portrait_holds_moving_face_until_interval_check_requires_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detections_path = tmp_path / "detections.json"
            tracks_path = tmp_path / "tracks.json"
            output_path = tmp_path / "plan.json"
            frame_path = str(tmp_path / "frame.jpg")
            detections_path.write_text(json.dumps({"detections": []}), encoding="utf-8")
            boxes = [
                {"x": 0.20, "y": 0.20, "width": 0.10, "height": 0.20},
                {"x": 0.45, "y": 0.20, "width": 0.10, "height": 0.20},
                {"x": 0.65, "y": 0.20, "width": 0.10, "height": 0.20},
            ]
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 1000, "box": boxes[0], "score": 0.9, "framePath": frame_path},
                            {"timeMs": 2000, "box": boxes[1], "score": 0.9, "framePath": frame_path},
                            {"timeMs": 3000, "box": boxes[2], "score": 0.9, "framePath": frame_path},
                        ],
                    }
                ]
            }), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-plan-portrait.py"),
                json.dumps({
                    "detectionsPath": str(detections_path),
                    "tracksPath": str(tracks_path),
                    "ranges": [{"startMs": 0, "endMs": 4000}],
                    "outputPath": str(output_path),
                    "portraitMode": "auto",
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            ranges = plan["ranges"]
            self.assertEqual([(item["startMs"], item["endMs"]) for item in ranges], [
                (1000, 2000),
            ])
            self.assertIn("face_left_crop:P1:2000", plan["warnings"])
            crop = ranges[0]["cropRect"]
            first_face_center_x = boxes[0]["x"] + boxes[0]["width"] / 2
            crop_center_x = crop["x"] + crop["width"] / 2
            self.assertAlmostEqual(crop_center_x, first_face_center_x, places=6)

    def test_plan_portrait_holds_one_crop_within_shot_when_face_remains_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detections_path = tmp_path / "detections.json"
            tracks_path = tmp_path / "tracks.json"
            shots_path = tmp_path / "shots.json"
            output_path = tmp_path / "plan.json"
            frame_path = str(tmp_path / "frame.jpg")
            detections_path.write_text(json.dumps({"detections": []}), encoding="utf-8")
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 0, "box": {"x": 0.35, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 3000, "box": {"x": 0.38, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 6000, "box": {"x": 0.41, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                        ],
                    }
                ]
            }), encoding="utf-8")
            shots_path.write_text(json.dumps({"shots": [{"id": "shot-0001", "startMs": 0, "endMs": 9000}]}), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-plan-portrait.py"),
                json.dumps({
                    "detectionsPath": str(detections_path),
                    "tracksPath": str(tracks_path),
                    "shotsPath": str(shots_path),
                    "ranges": [{"startMs": 0, "endMs": 9000}],
                    "outputPath": str(output_path),
                    "portraitMode": "auto",
                    "faceVisibilityThreshold": 0.80,
                    "cropCheckIntervalMs": 3000,
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([(item["startMs"], item["endMs"], item["selectedPersonLabel"]) for item in plan["ranges"]], [(0, 9000, "P1")])
            self.assertEqual(plan["ranges"][0]["reason"], "tracked_face_hold_crop")

    def test_plan_portrait_merges_adjacent_ranges_inside_same_shot_before_holding_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detections_path = tmp_path / "detections.json"
            tracks_path = tmp_path / "tracks.json"
            shots_path = tmp_path / "shots.json"
            output_path = tmp_path / "plan.json"
            frame_path = str(tmp_path / "frame.jpg")
            detections_path.write_text(json.dumps({"detections": []}), encoding="utf-8")
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 0, "box": {"x": 0.35, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 3000, "box": {"x": 0.37, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 6000, "box": {"x": 0.39, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                        ],
                    }
                ]
            }), encoding="utf-8")
            shots_path.write_text(json.dumps({"shots": [{"id": "shot-0001", "startMs": 0, "endMs": 9000}]}), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-plan-portrait.py"),
                json.dumps({
                    "detectionsPath": str(detections_path),
                    "tracksPath": str(tracks_path),
                    "shotsPath": str(shots_path),
                    "ranges": [{"startMs": 0, "endMs": 3000}, {"startMs": 3000, "endMs": 9000}],
                    "outputPath": str(output_path),
                    "portraitMode": "auto",
                    "faceVisibilityThreshold": 0.80,
                    "cropCheckIntervalMs": 3000,
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([(item["startMs"], item["endMs"], item["selectedPersonLabel"]) for item in plan["ranges"]], [(0, 9000, "P1")])

    def test_plan_portrait_truncates_shot_when_face_fails_interval_visibility_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detections_path = tmp_path / "detections.json"
            tracks_path = tmp_path / "tracks.json"
            shots_path = tmp_path / "shots.json"
            output_path = tmp_path / "plan.json"
            frame_path = str(tmp_path / "frame.jpg")
            detections_path.write_text(json.dumps({"detections": []}), encoding="utf-8")
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 0, "box": {"x": 0.35, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 3000, "box": {"x": 0.38, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 6000, "box": {"x": 0.80, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 9000, "box": {"x": 0.42, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                        ],
                    }
                ]
            }), encoding="utf-8")
            shots_path.write_text(json.dumps({"shots": [{"id": "shot-0001", "startMs": 0, "endMs": 12000}]}), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-plan-portrait.py"),
                json.dumps({
                    "detectionsPath": str(detections_path),
                    "tracksPath": str(tracks_path),
                    "shotsPath": str(shots_path),
                    "ranges": [{"startMs": 0, "endMs": 12000}],
                    "outputPath": str(output_path),
                    "portraitMode": "auto",
                    "faceVisibilityThreshold": 0.80,
                    "cropCheckIntervalMs": 3000,
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([(item["startMs"], item["endMs"], item["selectedPersonLabel"]) for item in plan["ranges"]], [(0, 6000, "P1")])
            self.assertIn("face_left_crop:P1:6000", plan["warnings"])

    def test_plan_portrait_truncates_when_final_sample_fails_after_last_interval_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detections_path = tmp_path / "detections.json"
            tracks_path = tmp_path / "tracks.json"
            shots_path = tmp_path / "shots.json"
            output_path = tmp_path / "plan.json"
            frame_path = str(tmp_path / "frame.jpg")
            detections_path.write_text(json.dumps({"detections": []}), encoding="utf-8")
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 0, "box": {"x": 0.35, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 3000, "box": {"x": 0.37, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 6000, "box": {"x": 0.39, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 7600, "box": {"x": 0.80, "y": 0.20, "width": 0.12, "height": 0.24}, "score": 0.9, "framePath": frame_path},
                        ],
                    }
                ]
            }), encoding="utf-8")
            shots_path.write_text(json.dumps({"shots": [{"id": "shot-0001", "startMs": 0, "endMs": 8000}]}), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-plan-portrait.py"),
                json.dumps({
                    "detectionsPath": str(detections_path),
                    "tracksPath": str(tracks_path),
                    "shotsPath": str(shots_path),
                    "ranges": [{"startMs": 0, "endMs": 8000}],
                    "outputPath": str(output_path),
                    "portraitMode": "auto",
                    "faceVisibilityThreshold": 0.80,
                    "cropCheckIntervalMs": 3000,
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([(item["startMs"], item["endMs"], item["selectedPersonLabel"]) for item in plan["ranges"]], [(0, 7600, "P1")])
            self.assertIn("face_left_crop:P1:7600", plan["warnings"])

    def test_plan_portrait_omits_ranges_without_faces_instead_of_center_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detections_path = tmp_path / "detections.json"
            tracks_path = tmp_path / "tracks.json"
            output_path = tmp_path / "plan.json"
            detections_path.write_text(json.dumps({"detections": []}), encoding="utf-8")
            tracks_path.write_text(json.dumps({"tracks": []}), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-plan-portrait.py"),
                json.dumps({
                    "detectionsPath": str(detections_path),
                    "tracksPath": str(tracks_path),
                    "ranges": [{"startMs": 0, "endMs": 5000}],
                    "outputPath": str(output_path),
                    "portraitMode": "auto",
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plan = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["ranges"], [])
            self.assertIn("no_face_material:0-5000", plan["warnings"])

    def test_crop_for_face_maximizes_9x16_and_places_face_upper_center_when_possible(self):
        module = load_script("wowclip-plan-portrait.py")

        crop = module.crop_for_face({"x": 0.35, "y": 0.25, "width": 0.10, "height": 0.20}, source_aspect=0.45)

        self.assertEqual(crop["x"], 0.0)
        self.assertEqual(crop["width"], 1.0)
        self.assertAlmostEqual(crop["height"], 0.8)
        face_anchor_y = 0.25 + 0.20 * 0.38
        output_face_y = (face_anchor_y - crop["y"]) / crop["height"]
        self.assertAlmostEqual(output_face_y, 0.33)

    def test_clip_check_returns_clip_and_subtitle_evidence_without_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = tmp_path / "plan.json"
            tracks_path = tmp_path / "tracks.json"
            transcript_path = tmp_path / "transcript.json"
            output_path = tmp_path / "clip_check.json"
            plan_path.write_text(json.dumps({
                "schema": "wowclip.portrait-plan.v1",
                "assetId": "A001",
                "ranges": [
                    {
                        "startMs": 1000,
                        "endMs": 4000,
                        "portraitMode": "speaker_crop",
                        "selectedPersonLabel": "",
                        "reason": "center_crop_fallback",
                        "cropRect": {"x": 0.34, "y": 0.0, "width": 0.32, "height": 1.0},
                    }
                ],
            }), encoding="utf-8")
            tracks_path.write_text(json.dumps({"tracks": []}), encoding="utf-8")
            transcript_path.write_text(json.dumps({
                "segments": [
                    {
                        "id": "seg-0001",
                        "startMs": 1200,
                        "endMs": 2500,
                        "text": "时间是在飞翔",
                        "words": [
                            {"id": "w1", "startMs": 1200, "endMs": 1500, "word": "时间"},
                            {"id": "w2", "startMs": 1500, "endMs": 1800, "word": "是"},
                            {"id": "w3", "startMs": 1800, "endMs": 2100, "word": "在"},
                            {"id": "w4", "startMs": 2100, "endMs": 2500, "word": "飞翔"},
                        ],
                    }
                ],
            }), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-clip-check.py"),
                json.dumps({
                    "portraitPlanPath": str(plan_path),
                    "tracksPath": str(tracks_path),
                    "transcriptPath": str(transcript_path),
                    "outputPath": str(output_path),
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            doc = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], "wowclip.clip-check.v2")
            self.assertNotIn("score", doc)
            self.assertNotIn("rangeChecks", doc)
            self.assertEqual(len(doc["clips"]), 1)
            clip = doc["clips"][0]
            self.assertEqual(clip["subtitle"]["text"], "时间是在飞翔")
            self.assertNotIn("visualScore", clip)
            self.assertNotIn("faceSampleCount", clip)
            self.assertNotIn("ok", clip)

    def test_crop_inspection_returns_geometry_evidence_without_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = tmp_path / "plan.json"
            tracks_path = tmp_path / "tracks.json"
            plan_path.write_text(json.dumps({
                "schema": "wowclip.portrait-plan.v1",
                "assetId": "A001",
                "ranges": [
                    {
                        "startMs": 1000,
                        "endMs": 3000,
                        "portraitMode": "speaker_crop",
                        "selectedPersonLabel": "P1",
                        "reason": "tracked_face_center_crop",
                        "cropRect": {"x": 0.20, "y": 0.0, "width": 0.32, "height": 1.0},
                    }
                ],
            }), encoding="utf-8")
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 1000, "box": {"x": 0.30, "y": 0.20, "width": 0.10, "height": 0.20}},
                            {"timeMs": 2000, "box": {"x": 0.31, "y": 0.20, "width": 0.10, "height": 0.20}},
                        ],
                    }
                ]
            }), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-score-crop.py"),
                json.dumps({
                    "portraitPlanPath": str(plan_path),
                    "tracksPath": str(tracks_path),
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            doc = json.loads(result.stdout)
            self.assertEqual(doc["schema"], "wowclip.crop-inspection.v1")
            self.assertNotIn("score", doc)
            self.assertNotIn("rangeScores", doc)
            self.assertEqual(len(doc["ranges"]), 1)
            inspected = doc["ranges"][0]
            self.assertNotIn("visibleFaceScore", inspected)
            self.assertEqual(inspected["faceSampleCount"], 2)
            self.assertTrue(all("insideRatio" in item for item in inspected["faceSamples"]))

    def test_portrait_materials_generates_face_materials_bound_to_subtitles_without_center_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tracks_path = tmp_path / "tracks.json"
            transcript_path = tmp_path / "transcript.json"
            output_path = tmp_path / "materials.json"
            frame_path = str(tmp_path / "frame.jpg")
            tracks_path.write_text(json.dumps({
                "tracks": [
                    {
                        "label": "P1",
                        "detections": [
                            {"timeMs": 1000, "box": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.2}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 2000, "box": {"x": 0.12, "y": 0.2, "width": 0.1, "height": 0.2}, "score": 0.9, "framePath": frame_path},
                        ],
                    },
                    {
                        "label": "P2",
                        "detections": [
                            {"timeMs": 1000, "box": {"x": 0.7, "y": 0.2, "width": 0.1, "height": 0.2}, "score": 0.9, "framePath": frame_path},
                            {"timeMs": 2000, "box": {"x": 0.72, "y": 0.2, "width": 0.1, "height": 0.2}, "score": 0.9, "framePath": frame_path},
                        ],
                    },
                ]
            }), encoding="utf-8")
            transcript_path.write_text(json.dumps({
                "segments": [
                    {"id": "seg-0001", "startMs": 1000, "endMs": 3000, "text": "我的生活是在步行", "words": []}
                ]
            }), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-portrait-materials.py"),
                json.dumps({
                    "tracksPath": str(tracks_path),
                    "transcriptPath": str(transcript_path),
                    "ranges": [{"startMs": 1000, "endMs": 3000}],
                    "outputPath": str(output_path),
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            doc = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], "wowclip.portrait-materials.v1")
            kinds_and_labels = {(item["kind"], item.get("trackLabel", "")) for item in doc["materials"]}
            self.assertIn(("face_crop", "P1"), kinds_and_labels)
            self.assertIn(("face_crop", "P2"), kinds_and_labels)
            self.assertNotIn(("center_crop", ""), kinds_and_labels)
            self.assertEqual(doc["materialCount"], 2)
            self.assertTrue(all(item["subtitle"]["text"] == "我的生活是在步行" for item in doc["materials"]))

    def test_build_timeline_splits_segments_by_portrait_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.mp4"
            plan_path = tmp_path / "plan.json"
            highlight_path = tmp_path / "highlight.json"
            transcript_path = tmp_path / "transcript.json"
            output_path = tmp_path / "edl.json"
            source_path.write_bytes(b"")
            plan_path.write_text(json.dumps({
                "schema": "wowclip.portrait-plan.v1",
                "assetId": "A001",
                "target": {"width": 1080, "height": 1920, "aspectRatio": "9:16"},
                "ranges": [
                    {
                        "startMs": 0,
                        "endMs": 1500,
                        "portraitMode": "speaker_crop",
                        "selectedPersonLabel": "P1",
                        "reason": "tracked_face_center_crop",
                        "cropRect": {"x": 0.10, "y": 0.0, "width": 0.31640625, "height": 1.0},
                    },
                    {
                        "startMs": 1500,
                        "endMs": 3000,
                        "portraitMode": "speaker_crop",
                        "selectedPersonLabel": "P1",
                        "reason": "tracked_face_center_crop",
                        "cropRect": {"x": 0.35, "y": 0.0, "width": 0.31640625, "height": 1.0},
                    },
                ],
            }), encoding="utf-8")
            highlight_path.write_text(json.dumps({
                "sourceAssetId": "A001",
                "clipPlans": [
                    {
                        "id": "CP001",
                        "segments": [
                            {"startMs": 0, "endMs": 3000, "role": "body", "actions": ["keep_context"], "highlightId": "H001"}
                        ],
                    }
                ],
            }), encoding="utf-8")
            transcript_path.write_text(json.dumps({"engineeredSubtitles": []}), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-build-timeline.py"),
                json.dumps({
                    "sourcePath": str(source_path),
                    "portraitPlanPath": str(plan_path),
                    "highlightPlanPath": str(highlight_path),
                    "selectedClipPlanId": "CP001",
                    "transcriptPath": str(transcript_path),
                    "projectRootDir": str(tmp_path),
                    "outputPath": str(output_path),
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            edl = json.loads(output_path.read_text(encoding="utf-8"))
            video_clips = edl["timeline"]["tracks"][0]["clips"]
            audio_clips = edl["timeline"]["tracks"][1]["clips"]
            self.assertEqual([(clip["srcIn"], clip["srcOut"], clip["dstStart"], clip["dstEnd"]) for clip in video_clips], [
                (0, 1500, 0, 1500),
                (1500, 3000, 1500, 3000),
            ])
            self.assertEqual([clip["placement"]["cropRect"]["x"] for clip in video_clips], [0.10, 0.35])
            self.assertEqual([(clip["srcIn"], clip["srcOut"], clip["dstStart"], clip["dstEnd"]) for clip in audio_clips], [
                (0, 1500, 0, 1500),
                (1500, 3000, 1500, 3000),
            ])

    def test_build_timeline_skips_segment_parts_without_portrait_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.mp4"
            plan_path = tmp_path / "plan.json"
            highlight_path = tmp_path / "highlight.json"
            transcript_path = tmp_path / "transcript.json"
            output_path = tmp_path / "edl.json"
            source_path.write_bytes(b"")
            plan_path.write_text(json.dumps({
                "schema": "wowclip.portrait-plan.v1",
                "assetId": "A001",
                "target": {"width": 1080, "height": 1920, "aspectRatio": "9:16"},
                "ranges": [
                    {
                        "startMs": 3000,
                        "endMs": 9000,
                        "portraitMode": "speaker_crop",
                        "selectedPersonLabel": "P1",
                        "reason": "tracked_face_hold_crop",
                        "cropRect": {"x": 0.35, "y": 0.0, "width": 0.31640625, "height": 1.0},
                    },
                ],
            }), encoding="utf-8")
            highlight_path.write_text(json.dumps({
                "sourceAssetId": "A001",
                "clipPlans": [
                    {
                        "id": "CP001",
                        "segments": [
                            {"startMs": 0, "endMs": 3000, "role": "hook", "actions": ["keep_context"], "highlightId": "H001"},
                            {"startMs": 3000, "endMs": 9000, "role": "body", "actions": ["keep_context"], "highlightId": "H001"},
                        ],
                    }
                ],
            }), encoding="utf-8")
            transcript_path.write_text(json.dumps({"engineeredSubtitles": []}), encoding="utf-8")

            result = subprocess.run([
                "python3",
                str(ROOT / "scripts" / "wowclip-build-timeline.py"),
                json.dumps({
                    "sourcePath": str(source_path),
                    "portraitPlanPath": str(plan_path),
                    "highlightPlanPath": str(highlight_path),
                    "selectedClipPlanId": "CP001",
                    "transcriptPath": str(transcript_path),
                    "projectRootDir": str(tmp_path),
                    "outputPath": str(output_path),
                }),
            ], text=True, capture_output=True)

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            edl = json.loads(output_path.read_text(encoding="utf-8"))
            video_clips = edl["timeline"]["tracks"][0]["clips"]
            audio_clips = edl["timeline"]["tracks"][1]["clips"]
            self.assertEqual([(clip["srcIn"], clip["srcOut"], clip["dstStart"], clip["dstEnd"]) for clip in video_clips], [(3000, 9000, 0, 6000)])
            self.assertEqual(video_clips[0]["placement"]["reason"], "tracked_face_hold_crop")
            self.assertEqual([(clip["srcIn"], clip["srcOut"], clip["dstStart"], clip["dstEnd"]) for clip in audio_clips], [(3000, 9000, 0, 6000)])


if __name__ == "__main__":
    unittest.main()
