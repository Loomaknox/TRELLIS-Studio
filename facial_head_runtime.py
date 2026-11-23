"""Desktop bridge to the optional TOPOS geometry installation (stdlib only)."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


_INSTALL = "Install the optional face reconstruction component."
_REPAIR = "Repair the optional face reconstruction component."


def _component(root):
    return Path(root).resolve() / ".tools" / "facial-head"


def _python(component):
    return component / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _missing(component):
    code = component / "TOPOS"
    weights = code / "pretrained_ckpt"
    files = [
        _python(component), component / "face_landmarker.task",
        code / "train_dit.py", code / "configs/dit_test.yaml", code / "configs/dit.yaml",
        code / "data/template.obj", code / "data/template_vertices.npz",
        code / "data/edges.npy", code / "data/cluster.npz",
        weights / "facebookresearch_dinov2_main/hubconf.py",
    ]
    missing = [p.relative_to(component).as_posix() for p in files if not p.is_file() or not p.stat().st_size]
    # The installer hashes each pinned download. Detect a truncated weight without re-reading gigabytes here.
    manifest = Path(__file__).with_name("installer") / "facial-head-manifest.json"
    for asset in json.loads(manifest.read_text(encoding="utf-8"))["assets"]:
        if asset.get("archive"):
            continue
        item = component / asset["destination"]
        if not item.is_file() or item.stat().st_size != asset["bytes"]:
            missing.append(asset["destination"])
    return missing


def readiness(root):
    component = _component(root)
    if not component.is_dir():
        return {"ready": False, "reason": _INSTALL}
    try:
        missing = _missing(component)
        receipt = json.loads((component / "installed.json").read_text(encoding="utf-8"))
        valid = isinstance(receipt, dict) and receipt.get("schema") == 1 and receipt.get("validated") is True
    except (ValueError, OSError):
        return {"ready": False, "reason": _REPAIR}
    if not valid or missing:
        return {"ready": False, "reason": _REPAIR, "missing": missing}
    return {"ready": True, "reason": ""}


def _infer(root, image, output_dir, seed):
    component = _component(root)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name("facial_head_infer.py")
    cache = component / "cache"
    env = dict(os.environ, PYTHONUTF8="1", ATTN_BACKEND="sdpa", HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", TORCH_FORCE_WEIGHTS_ONLY_LOAD="1", XFORMERS_DISABLED="1",
               TORCH_HOME=str(cache / "torch"), HF_HOME=str(cache / "huggingface"),
               TORCHINDUCTOR_CACHE_DIR=str(cache / "inductor"), MPLCONFIGDIR=str(cache / "mpl"),
               CUDA_CACHE_PATH=str(cache / "cuda"))
    with TemporaryDirectory(prefix="topos-", dir=output) as stage_dir:
        stage = Path(stage_dir)
        scratch = stage / "tmp"
        scratch.mkdir()
        env.update(TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch))
        argv = [str(_python(component)), "-I", "-B", "-u", str(script), str(component),
                str(Path(image).resolve(strict=True)), str(stage), str(int(seed))]
        result = subprocess.run(argv, cwd=stage, env=env, stdin=subprocess.DEVNULL,
                                timeout=1200, check=False)
        if result.returncode:
            error = stage / "error.json"
            reason = json.loads(error.read_text(encoding="utf-8")) if error.is_file() else {}
            print(f"Face reconstruction worker exited with code {result.returncode}.", flush=True)
            raise RuntimeError(reason.get("message") or
                               "Face reconstruction stopped before returning a result. Check the generation log.")
        paths = {"head_obj": "head.obj", "landmarks_json": "landmarks.json", "portrait": "portrait.png"}
        if any(not (stage / name).is_file() for name in paths.values()):
            raise RuntimeError("Face reconstruction returned incomplete geometry or landmarks.")
        for name in paths.values():
            (stage / name).replace(output / name)
    return {key: str(output / name) for key, name in paths.items()}


def infer_head(root, image, output_dir, seed):
    from installer.facial_head_lock import component_lock
    with component_lock(root):
        state = readiness(root)
        if not state["ready"]:
            raise RuntimeError(state["reason"])
        return _infer(root, image, output_dir, seed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the installed face model on a portrait and GPU.")
    parser.add_argument("--self-test", dest="root", required=True, type=Path)
    parser.add_argument("--image", type=Path)
    args = parser.parse_args()
    component = _component(args.root)
    missing = _missing(component)
    if missing:
        parser.exit(1, "Incomplete face runtime: " + ", ".join(missing) + "\n")
    portrait = args.image or component / "TOPOS/examples/face.png"
    with TemporaryDirectory(prefix="face-validation-", dir=component) as target:
        result = _infer(args.root, portrait, target, 42)
        report = json.loads(Path(result["landmarks_json"]).read_text(encoding="utf-8"))
        print(json.dumps({"validated": True, "gpu": report["gpu"], "landmarks": len(report["landmarks"]),
                          "vertices": report["vertices"], "peak_cuda_mib": report["peak_cuda_mib"]}))
