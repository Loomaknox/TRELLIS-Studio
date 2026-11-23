"""Run with the Studio Python; no optional downloads or GPU needed."""
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

import facial_head_runtime as runtime
from facial_head_infer import _detect, _iris_colors, _portrait_box


class RuntimeTests(unittest.TestCase):
    def test_absent_or_partial_install_does_not_enable_feature(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(runtime.readiness(root)["ready"])
            component = runtime._component(root)
            component.mkdir(parents=True)
            (component / "installed.json").write_text('{"schema":1,"validated":true}')
            self.assertFalse(runtime.readiness(root)["ready"])
            with self.assertRaisesRegex(RuntimeError, "Repair"):
                runtime.infer_head(root, root / "original.png", root / "job", 42)
            self.assertFalse((root / "job").exists())

    def test_solver_failure_keeps_existing_outputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "image.png"
            Image.new("RGB", (320, 240)).save(source)
            out = root / "job"
            out.mkdir()
            (out / "head.obj").write_text("previous", encoding="utf-8")

            def fail(command, *, cwd, **kwargs):
                self.assertEqual(kwargs['creationflags'], getattr(runtime.subprocess, 'CREATE_NO_WINDOW', 0))
                (Path(cwd) / "error.json").write_text(json.dumps({"message": "invalid portrait"}))
                return type("Result", (), {"returncode": 1})()

            with patch.object(runtime.subprocess, "run", side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, "invalid portrait"):
                    runtime._infer(root, source, out, 42)
            self.assertEqual([f.name for f in out.iterdir()], ["head.obj"])
            self.assertEqual((out / "head.obj").read_text(), "previous")

    def test_detect_restores_coordinates_of_original_image(self):
        from types import SimpleNamespace
        mp = SimpleNamespace(Image=lambda **kw: kw["data"], ImageFormat=SimpleNamespace(SRGB=1))
        point = SimpleNamespace(x=.25, y=.75, z=.5)
        detector = SimpleNamespace(detect=lambda _frame: SimpleNamespace(face_landmarks=[[point] * 478]))
        points = _detect(detector, mp, Image.new("RGB", (450, 250)), (20, 30, 220, 130))
        np.testing.assert_array_equal(points[0], [70, 105, 100])
        detector.detect = lambda _frame: SimpleNamespace(face_landmarks=[[point] * 478] * 2)
        with self.assertRaisesRegex(ValueError, "More than one"):
            _detect(detector, mp, Image.new("RGB", (400, 400)), (30, 30, 300, 300))

    def test_portrait_is_square_and_iris_samples_require_resolved_pixels(self):
        points = np.full((478, 3), [25., 25., 0])
        points[[12, 13]] = [[20, 8, 0], [39, 44, 0]]
        x, y, right, bottom = _portrait_box(points)
        self.assertEqual(right-x, bottom-y)
        self.assertLessEqual(y, 8)
        self.assertGreater(bottom, 44)
        points[468:473, :2] = [[15, 20], [22, 20], [15, 27], [8, 20], [15, 13]]
        points[473:478, :2] = [[35, 20]] * 5
        colors, sources = _iris_colors(Image.new("RGBA", (50, 50), (50, 70, 80, 255)), points)
        self.assertEqual(colors[0], [50, 70, 80])
        self.assertEqual(sources, ["reference", "default"])


if __name__ == "__main__":
    unittest.main()
