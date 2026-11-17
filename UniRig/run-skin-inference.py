"""Run the pinned UniRig skin inference checkpoint with restricted loading."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

import yaml


ROOT = Path(__file__).resolve().parent


def verified_skin_task(task_path):
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    checkpoint = ROOT / "models" / "skin.ckpt"
    if (
        task.get("mode") != "predict"
        or Path(task["resume_from_checkpoint"]).resolve() != checkpoint.resolve()
    ):
        raise ValueError("Restricted UniRig loading is only enabled for its pinned skin checkpoint.")
    manifest = json.loads((ROOT.parent / "installer" / "manifest.json").read_text(encoding="utf-8"))
    pin = next(asset for asset in manifest["assets"] if asset["path"] == "UniRig/models/skin.ckpt")
    if checkpoint.stat().st_size != pin["bytes"]:
        raise ValueError("The UniRig skin checkpoint has the wrong size. Run component repair.")
    with checkpoint.open("rb") as model:
        if hashlib.file_digest(model, "sha256").hexdigest() != pin["sha256"]:
            raise ValueError("The UniRig skin checkpoint failed SHA-256 verification. Run component repair.")


def main():
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--task", type=Path, required=True)
    args, _ = parser.parse_known_args()
    verified_skin_task(args.task)

    # Only the skin process needs Box. All of its loads still use weights-only
    # unpickling, even if a library passes a different torch.load default.
    os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"
    from box import Box
    from torch.serialization import safe_globals

    entrypoint = ROOT / "source" / "run.py"
    sys.path.insert(0, str(entrypoint.parent))
    sys.argv[0] = str(entrypoint)
    with safe_globals([Box]):
        runpy.run_path(str(entrypoint), run_name="__main__")


if __name__ == "__main__":
    main()
