"""Isolated MediaPipe and TOPOS-DiT inference. Only the installer provisions weights."""
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageOps


def _detect(detector, mp, pixels, box):
    x, y, right, bottom = box
    tile = pixels.crop(box)
    tile.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    frame = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(tile).copy())
    faces = detector.detect(frame).face_landmarks
    if len(faces) > 1:
        raise ValueError("More than one face was detected. Use a single front-facing character.")
    if not faces:
        return None
    points = np.array([(x + p.x * (right - x), y + p.y * (bottom - y), p.z * (right - x))
                       for p in faces[0]], dtype=np.float64)
    if points.shape != (478, 3) or not np.isfinite(points).all():
        raise ValueError("The detector could not measure the face landmarks.")
    return points


def _landmarks(image, model):
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    w, h = image.size
    neutral = Image.new("RGB", image.size, (128, 128, 128))
    neutral.paste(image.convert("RGB"), mask=image.getchannel("A"))
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(model), delegate=python.BaseOptions.Delegate.CPU),
        num_faces=2, min_face_detection_confidence=.5, min_face_presence_confidence=.6)
    with vision.FaceLandmarker.create_from_options(options) as detector:
        points = _detect(detector, mp, neutral, (0, 0, w, h))
        if points is None:
            # On a full-body T-pose the face can be too small for MediaPipe's detection stage.
            foreground = image.getchannel("A").point(lambda a: 255 if a >= 128 else 0).getbbox()
            left, top, right, bottom = foreground or (0, 0, w, h)
            cx = (left + right) / 2
            radius = max(24, (bottom - top) * .22)
            box = (max(0, int(cx - radius)), max(0, int(top - radius * .1)),
                   min(w, math.ceil(cx + radius)), min(h, math.ceil(top + 1.9 * radius)))
            points = _detect(detector, mp, neutral, box)
    if points is None:
        raise ValueError("No clear face was found in the source. Use a front-facing T-pose or portrait.")
    left, right = sorted(points[[468, 473], :2], key=lambda p: p[0])
    eye_line = right - left
    eye_span = np.linalg.norm(eye_line)
    if eye_span < 9 or abs(eye_line[1]) > .42 * eye_span:
        raise ValueError("The face is too small or tilted for reliable reconstruction.")
    nose_offset = (points[1, :2] - (left + right) / 2) @ eye_line / eye_span**2
    if abs(nose_offset) > .36:
        raise ValueError("The face is turned too far to reconstruct the head from this view.")
    return points


def _portrait_box(points):
    x1, y1 = points[:, :2].min(axis=0)
    x2, y2 = points[:, :2].max(axis=0)
    size = int(math.ceil(max(x2 - x1, y2 - y1) * 1.65))
    x = round((x1 + x2 - size) / 2)
    y = round((y1 + y2 - size) / 2 - .03 * size)
    return x, y, x + size, y + size


def _iris_colors(image, points):
    # Sample the annulus away from the pupil, eyelids and sclera using original pixels.
    colors, sources = [], []
    for center in sorted((468, 473), key=lambda i: points[i, 0]):
        cx, cy = points[center, :2]
        contour = points[center + 1:center + 5, :2]
        rx, ry = np.max(np.abs(contour - [cx, cy]), axis=0)
        pixels = []
        if min(rx, ry) >= 2:
            for y in range(max(0, int(cy - ry)), min(image.height, math.ceil(cy + ry))):
                for x in range(max(0, int(cx - rx)), min(image.width, math.ceil(cx + rx))):
                    dx, dy = (x + .5 - cx) / rx, (y + .5 - cy) / ry
                    if .25 <= dx * dx + dy * dy <= .70 and abs(dy) <= .55:
                        r, g, b, alpha = image.getpixel((x, y))
                        if alpha >= 224 and 13 < max(r, g, b) < 236:
                            pixels.append((r, g, b))
        if len(pixels) >= 5:
            colors.append(np.median(pixels, axis=0).round().astype(int).tolist())
            sources.append("reference")
        else:
            colors.append([88, 67, 47])
            sources.append("default")
    return colors, sources


def _generate(repo, portrait, stage, seed):
    # Keep the upstream solver and its native UV/vertex order. Each worker has its own cwd and flags.
    import torch
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    from thsolver.config import parse_args
    from train_dit import TOPOSDiTSolver

    if not torch.cuda.is_available():
        raise RuntimeError("The isolated TOPOS runtime cannot access its CUDA GPU.")
    sys.argv = ["train_dit.py", "--config", "configs/dit_test.yaml",
                "DATA.test.test_image_path", str(portrait), "DATA.test.seeds", f"[{seed}]",
                "SOLVER.logdir", str(stage), "MODEL.compile", "False"]
    flags = parse_args(backup=False)
    torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        TOPOSDiTSolver.worker(0, flags)
    pred = stage / "results" / "pred_mesh" / f"portrait_seed{seed}_pred.obj"
    vertices = 0
    faces = 0
    with pred.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("v "):
                values = line.split()[1:4]
                if len(values) != 3 or not all(math.isfinite(float(v)) for v in values):
                    raise ValueError("TOPOS produced a non-finite head vertex.")
                vertices += 1
            elif line.startswith("f "):
                faces += 1
    if vertices != 24049 or not faces:
        raise ValueError("TOPOS returned an unexpected head topology.")
    pred.replace(stage / "head.obj")
    return vertices, torch.cuda.get_device_name(), round(torch.cuda.max_memory_allocated() / 2**20)


def run(component, source, stage, seed):
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    points = _landmarks(image, component / "face_landmarker.task")
    box = _portrait_box(points)
    portrait = stage / "portrait.png"
    image.crop(box).save(portrait)
    colors, sources = _iris_colors(image, points)
    vertices, gpu, peak = _generate(component / "TOPOS", portrait, stage, seed)
    w, h = image.size
    report = {"image_size": [w, h], "crop_box": list(box), "landmarks": (points / [w, h, w]).tolist(),
              "iris_rgb": colors, "iris_color_source": sources, "vertices": vertices,
              "gpu": gpu, "peak_cuda_mib": peak}
    (stage / "landmarks.json").write_text(json.dumps(report, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    component, source, stage = (Path(value).resolve() for value in sys.argv[1:4])
    try:
        run(component, source, stage, int(sys.argv[4]))
    except Exception as error:
        (stage / "error.json").write_text(json.dumps({"message": str(error)[:2048]}), encoding="utf-8")
        raise
