"""Generate synchronized texture views with the optional local MV-Adapter runtime."""

import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import sys
import time

VIEW_COUNT = 6
VIEW_SIZE = 512
SEED = 42
STEPS = 35
GUIDANCE = 3.0
PROMPT = "high quality"
ADAPTER_FILE = "mvadapter_ig2mv_sd21.safetensors"
SOURCE_REVISION = "4277e0018232bac82bb2c103caf0893cedb711be"
ADAPTER_REVISION = "6de4033df6b53366f3c009d22f5ec434bb55e59f"
BASE_REVISION = "4e63672c03103b6c636b8fb4119ba982469b2955"
DEPENDENCIES = {"diffusers": "0.35.2", "einops": "0.8.1", "peft": "0.17.1"}

# These are the original SD 2.1 base FP16 shards from the public archive and
# the MV-Adapter image+geometry adapter. No other checkpoints are required.
WEIGHTS = {
    "weights/base/text_encoder/model.fp16.safetensors": (
        680821096, "681c555376658c81dc273f2d737a2aeb23ddb6d1d8e5b3a7064636d359a22668",
    ),
    "weights/base/unet/diffusion_pytorch_model.fp16.safetensors": (
        1731904736, "28ec9cf3b239c0751c201b1f6fb46b551df5862731b30a37aa1360101cb3fbab",
    ),
    "weights/base/vae/diffusion_pytorch_model.fp16.safetensors": (
        167335342, "3e4c08995484ee61270175e9e7a072b66a6e4eeb5f0c266667fe1f45b90daf9a",
    ),
    f"weights/adapter/{ADAPTER_FILE}": (
        708310064, "7940d6197be614fc6a3483ece1ed37cac850f94375d127ada6ae6464ce9252c3",
    ),
}
REQUIRED_FILES = (
    "source/mvadapter/pipelines/pipeline_mvadapter_i2mv_sd.py",
    "weights/base/model_index.json",
    "weights/base/feature_extractor/preprocessor_config.json",
    "weights/base/scheduler/scheduler_config.json",
    "weights/base/text_encoder/config.json",
    "weights/base/tokenizer/merges.txt",
    "weights/base/tokenizer/special_tokens_map.json",
    "weights/base/tokenizer/tokenizer_config.json",
    "weights/base/tokenizer/vocab.json",
    "weights/base/unet/config.json",
    "weights/base/vae/config.json",
    *(f"dependencies/{name}/__init__.py" for name in DEPENDENCIES),
    *(f"dependencies/{name}-{version}.dist-info/METADATA"
      for name, version in DEPENDENCIES.items()),
)
RUNTIME_VERSION = {
    "format": 1,
    "source_revision": SOURCE_REVISION,
    "adapter_revision": ADAPTER_REVISION,
    "base_revision": BASE_REVISION,
    "dependencies": DEPENDENCIES,
}


def sha256(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def validate_runtime(runtime, *, verify_weights=False):
    """Check an installation without importing CUDA or the optional packages."""
    runtime = Path(runtime).resolve()
    try:
        manifest = json.loads((runtime / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("The multi-view texturing runtime is not installed or is unreadable.") from error
    if not isinstance(manifest, dict) or any(
        manifest.get(name) != value for name, value in RUNTIME_VERSION.items()
    ):
        raise ValueError("The multi-view texturing runtime version does not match Studio.")
    for relative in REQUIRED_FILES:
        if not (runtime / relative).is_file():
            raise ValueError(f"Multi-view texturing runtime is missing {relative}.")
    for relative, (size, expected_hash) in WEIGHTS.items():
        weight = runtime / relative
        if not weight.is_file() or weight.stat().st_size != size:
            raise ValueError(f"Multi-view texturing checkpoint missing or incomplete: {relative}.")
        if verify_weights and sha256(weight) != expected_hash:
            raise ValueError(f"Multi-view texturing checkpoint failed integrity validation: {relative}.")
    return runtime


def condition_reference(path):
    from PIL import Image

    # Match the pilot: crop the existing alpha, center the subject at 90% fill,
    # and composite on grey without redrawing the source.
    with Image.open(path) as source:
        image = source.convert("RGBA")
    box = image.getchannel("A").getbbox()
    if box is None:
        raise ValueError("Reference alpha is empty.")
    left, top, right, bottom = box
    image = image.crop((max(0, left - 1), max(0, top - 1), right, bottom))
    scale = VIEW_SIZE * .9 / max(image.size)
    image = image.resize(tuple(max(1, int(scale * side)) for side in image.size))
    canvas = Image.new("RGB", (VIEW_SIZE, VIEW_SIZE), (127, 127, 127))
    canvas.paste(image, ((VIEW_SIZE - image.width) // 2, (VIEW_SIZE - image.height) // 2), image)
    return canvas


def load_pipeline(runtime):
    sys.path[:0] = [str(runtime / "dependencies"), str(runtime / "source")]
    import torch
    from diffusers import DDPMScheduler
    from mvadapter.models.attention_processor import DecoupledMVRowColSelfAttnProcessor2_0
    from mvadapter.pipelines.pipeline_mvadapter_i2mv_sd import MVAdapterI2MVSDPipeline
    from mvadapter.schedulers.scheduling_shift_snr import ShiftSNRScheduler

    pipeline = MVAdapterI2MVSDPipeline.from_pretrained(
        str(runtime / "weights" / "base"),
        variant="fp16",
        torch_dtype=torch.float16,
        local_files_only=True,
        use_safetensors=True,
    )
    pipeline.scheduler = ShiftSNRScheduler.from_scheduler(
        pipeline.scheduler,
        shift_mode="interpolated",
        shift_scale=8.0,
        scheduler_class=DDPMScheduler,
    )
    pipeline.init_custom_adapter(
        num_views=VIEW_COUNT, self_attn_processor=DecoupledMVRowColSelfAttnProcessor2_0
    )
    pipeline.load_custom_adapter(
        str(runtime / "weights" / "adapter"),
        weight_name=ADAPTER_FILE,
        local_files_only=True,
    )
    pipeline.vae.enable_slicing()
    return pipeline


def read_controls(path):
    import numpy as np

    with np.load(path, allow_pickle=False) as data:
        positions, normals, mask = (data[name] for name in ("positions", "normals", "mask"))
    shape = (VIEW_COUNT, VIEW_SIZE, VIEW_SIZE)
    if positions.shape != (*shape, 3) or normals.shape != positions.shape or mask.shape != shape:
        raise ValueError("Multi-view texturing requires six 512 × 512 geometry controls.")
    if not (np.isfinite(positions).all() and np.isfinite(normals).all() and np.isfinite(mask).all()):
        raise ValueError("Non-finite multi-view texturing controls.")
    mask = mask.astype(bool)
    if not mask.any(axis=(1, 2)).all():
        raise ValueError("A multi-view texturing camera has an empty geometry mask.")
    control = np.concatenate((positions + .5, normals * .5 + .5), axis=-1).clip(0, 1)
    control[~mask] = .5
    return control, mask


def read_cameras(path):
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    cameras = document.get("views") if isinstance(document, dict) else document
    if not isinstance(cameras, list) or len(cameras) != VIEW_COUNT:
        raise ValueError("Multi-view texturing requires six projection cameras.")
    if any(not isinstance(item, dict) for item in cameras):
        raise ValueError("Invalid multi-view texturing camera.")
    cameras = [item.get("camera", item) for item in cameras]
    for camera in cameras:
        if not isinstance(camera, dict) or camera.get("projection") != "orthographic":
            raise ValueError("Multi-view texturing requires orthographic cameras.")
    return cameras


def generate_views(runtime, reference_path, controls_path, cameras_path, output):
    import numpy as np
    import torch
    from PIL import Image

    start = time.monotonic()
    reference_hash = sha256(reference_path)
    reference = condition_reference(reference_path)
    control, mask = read_controls(controls_path)
    cameras = read_cameras(cameras_path)
    if not torch.cuda.is_available():
        raise ValueError("Multi-view texturing requires an NVIDIA CUDA GPU.")
    device = torch.device("cuda")
    torch.cuda.reset_peak_memory_stats()
    pipeline = load_pipeline(runtime)
    # Adapter modules are created on CPU above. Cast the attached weights in
    # this move too, including the separately held geometry encoder.
    pipeline.to(device=device, dtype=torch.float16)
    pipeline.cond_encoder.to(device=device, dtype=torch.float16)
    controls = torch.from_numpy(control).permute(0, 3, 1, 2).contiguous().float().to(device)
    images = pipeline(
        PROMPT,
        height=VIEW_SIZE,
        width=VIEW_SIZE,
        num_images_per_prompt=VIEW_COUNT,
        num_inference_steps=STEPS,
        guidance_scale=GUIDANCE,
        control_image=controls,
        control_conditioning_scale=1.0,
        reference_image=reference,
        reference_conditioning_scale=1.0,
        negative_prompt="watermark, ugly, deformed, noisy, blurry, low contrast",
        generator=torch.Generator(device=device).manual_seed(SEED),
    ).images
    if len(images) != VIEW_COUNT or any(image.size != (VIEW_SIZE, VIEW_SIZE) for image in images):
        raise ValueError("Generated views did not match the projection cameras.")
    output.mkdir(parents=True, exist_ok=True)
    views = []
    for index, (image, camera) in enumerate(zip(images, cameras, strict=True)):
        image = image.convert("RGBA")
        image.putalpha(Image.fromarray(mask[index].astype(np.uint8) * 255))
        path = output / f"view-{index:02}.png"
        image.save(path)
        views.append({"camera": camera, "image": path.name, "weight": 1})

    receipt = {
        "engine": "MV-Adapter image + geometry, SD2.1",
        "revision": SOURCE_REVISION,
        "adapter_revision": ADAPTER_REVISION,
        "base_revision": BASE_REVISION,
        "scheduler": "ShiftSNR DDPM",
        "seed": SEED,
        "steps": STEPS,
        "guidance": GUIDANCE,
        "prompt": PROMPT,
        "resolution": VIEW_SIZE,
        "reference_sha256": reference_hash,
        "elapsed_s": round(time.monotonic() - start, 2),
        "torch_peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 1048576, 2),
        "torch_peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 1048576, 2),
        "views": views,
    }
    manifest = output / "manifest.json"
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    temporary.replace(manifest)
    print(json.dumps({key: value for key, value in receipt.items() if key != "views"}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("reference", type=Path, nargs="?")
    parser.add_argument("controls", type=Path, nargs="?")
    parser.add_argument("cameras", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--check", action="store_true", help="Verify weights and load the runtime on CPU.")
    args = parser.parse_args()
    if not args.check and any(value is None for value in (
        args.reference, args.controls, args.cameras, args.output
    )):
        parser.error("reference, controls, cameras and output are required for inference.")
    os.environ["HF_HUB_OFFLINE"] = "1"
    runtime = validate_runtime(args.runtime, verify_weights=True)
    if args.check:
        load_pipeline(runtime)
        print("MV-Adapter runtime verified and loaded on CPU.", flush=True)
        return
    generate_views(runtime, args.reference, args.controls, args.cameras, args.output)


if __name__ == "__main__":
    main()
