import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class WowClipRemoveOverlaysTests(unittest.TestCase):
    def test_write_mask_uses_normalized_rectangles(self):
        module = load_script("wowclip-remove-overlays.py")
        with tempfile.TemporaryDirectory() as tmp:
            mask_path = Path(tmp) / "mask.png"

            module.write_mask(mask_path, 100, 50, [(0.0, 0.8, 1.0, 1.0)])

            mask = Image.open(mask_path).convert("L")
            self.assertEqual(mask.getpixel((50, 39)), 0)
            self.assertEqual(mask.getpixel((50, 40)), 255)
            self.assertEqual(mask.getpixel((99, 49)), 255)

    def test_default_mask_rect_targets_bottom_subtitle_band(self):
        module = load_script("wowclip-remove-overlays.py")

        rects = module.mask_rects({})

        self.assertEqual(rects, [(0.0, 0.8, 1.0, 0.99)])

    def test_propainter_command_includes_processing_and_inference_controls(self):
        module = load_script("wowclip-remove-overlays.py")

        command = module.propainter_command(
            "python3",
            Path("/propainter"),
            Path("/input.mp4"),
            Path("/mask.png"),
            Path("/output"),
            {
                "processingWidth": 432,
                "processingHeight": 240,
                "saveFps": 6,
                "raftIter": 2,
                "subvideoLength": 24,
                "neighborLength": 6,
                "refStride": 6,
                "maskDilation": 2,
            },
        )

        self.assertIn("--width", command)
        self.assertIn("432", command)
        self.assertIn("--height", command)
        self.assertIn("240", command)
        self.assertIn("--save_fps", command)
        self.assertIn("6", command)
        self.assertIn("--raft_iter", command)
        self.assertIn("2", command)

    def test_link_weights_rejects_missing_weight_files(self):
        module = load_script("wowclip-remove-overlays.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            propainter_dir = root / "ProPainter"
            weights_dir = root / "weights-src"
            (propainter_dir / "weights").mkdir(parents=True)
            weights_dir.mkdir()
            (weights_dir / "ProPainter.pth").write_bytes(b"x")

            with self.assertRaisesRegex(ValueError, "recurrent_flow_completion"):
                module.link_weights(propainter_dir, weights_dir)


if __name__ == "__main__":
    unittest.main()
