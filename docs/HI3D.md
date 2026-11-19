# Hi3D detail refinement

[Powered by Hi3D 1.0](http://hi3d.ai/).

Detail Refinement rebuilds the decoded surface of a single-image TRELLIS.2
generation from its reference cutout. The 512 and 1024 labels describe the Hi3D
refinement resolution. The generation profile controls the TRELLIS.2 source
resolution independently. Hi3D accepts the native single-image resolutions
available on the host.

## Studio workflow

- In **Create**, choose **HD Master** and **TRELLIS.2 · Single image**, then
  choose **Detail Refinement (512)** or **Detail Refinement (1024)** under
  **Master finishing**. Studio keeps the selected 3D resolution and its
  decoded cache.
- In **Prepare → Finishing board**, choose a detail refinement on a compatible
  model with a saved native TRELLIS.2 source and its cutout. Each result is a linked
  model with its own job. Use the board to compare it with the original.
- Open the finished master for **Texture Projection** or use
  **Game Copy from HD** to reduce it and bake a game copy.

Hi3D runs 25 Heun steps per pass. The 512 method runs one pass and the 1024
method runs two. The adapter closes boundary loops before simplifying and
filters small disconnected fragments. The refined surface has a limit of one
million triangles and follows any lower job ceiling. Studio unwraps the refined surface and
samples the cached TRELLIS.2 PBR material volume. Detail, silhouette, intentional
openings, and texture alignment can change. Inspect them before choosing a
master. The finer option can take substantially longer and use more GPU memory.

## Install with Windows Setup

On the optional **Hi3D Detail Refinement** page, select **Install Hi3D Detail
Refinement** and review the Hi3D, DINOv2 and CLIP model terms. This option is
off for a fresh installation and is available in Desktop and Server.
Selecting it also prepares TRELLIS.2 generation with its own DINOv3 license;
Pixal3D, UniRig and Kimodo remain independent choices.

Setup uses the selected NVIDIA GPU and driver from **Check this PC**. It
currently supports the Windows CUDA 12.8 package plan for compute capabilities
8.6 and 8.9 (RTX 30 and 40 series) with NVIDIA driver 570.65 or later. Cards
outside those profiles and cards below 8,000 MiB of detected VRAM are deferred
for this component. The rest of Studio remains available.

For 8,000–11,999 MiB of detected VRAM, prefer **Detail Refinement (512)**.
At least 12,000 MiB is recommended for **1024**. These recommendations allow
room for the driver and application. The mesh, other GPU activity, and
available memory affect the result. On a 12 GB RTX 4070 Ti, the checked meshes
peaked at 4.01 GiB of PyTorch allocation in 512 and 9.85 GiB in 1024.

Setup verifies a sparse convolution and a mesh voxelization on the GPU before
downloading roughly 10.7 GB of pinned weights. New installations store the
model files in `models/hi3d` and the source and Python packages in
`.tools/hi3d`. Both refinement resolutions use the same installation.
Use **Repair or resume components**
from the Start menu for an interrupted installation. Setup reuses verified
files and preserves an existing configured Hi3D runtime. Clearing the Hi3D
option in Setup leaves its files installed and removes any pending Hi3D
request from the Repair list.

### Move an existing default weight store

Stop Studio or Server and exit any running component installers. From the
installation folder, run:

```powershell
.\.venv\Scripts\python.exe -B installer\install_hi3d.py --migrate-weights
```

The command verifies the local files against the pinned manifest, then moves
`.tools/hi3d/weights` to `models/hi3d` on the same volume. It updates the
weight path in `config/hi3d-runtime.json`. The operation uses the existing
files without downloading them again or starting the GPU. Restart Studio or
Server after verification succeeds.

Setup repair continues to use any existing configured weight path. Finish an
interrupted legacy installation before moving its store. Custom weight paths
remain supported. If both default directories already exist, review their files
before running the migration.

## Configure a separate runtime manually

The Studio distribution includes the bridge. Run the refinement with a
host-provisioned Windows CUDA runtime and local model files. The studio worker loads
the engine in a separate process and uses the installed model files offline.

1. Provision a compatible Python environment with NVIDIA CUDA support, PyTorch,
   Transformers, NumPy, Trimesh, the matching spconv CUDA wheel, Triton and
   pyfqmr. The Windows validation used the Studio Python with compatible local
   dependencies, including spconv-cu124 2.3.8.
2. Obtain the pinned [ComfyUI-Hi3D source](https://github.com/visualbruno/ComfyUI-Hi3D/tree/03dea7e366ba951d7475f3f1c8a71596a87f913c).
   Keep the bundled `Hi3D-1.0` subtree and upstream license and notice files.
3. Place the [Hi3D checkpoint](https://huggingface.co/hi3d-official/Hi3Dv1.0/tree/23d1bace196f618265b4b0b9c90d95fa9a9b1df5),
   [DINOv2 Large](https://huggingface.co/facebook/dinov2-large), and
   [CLIP ViT-L/14](https://huggingface.co/openai/clip-vit-large-patch14)
   into folders named `Hi3Dv1.0`, `dinov2-large`, and
   `clip-vit-large-patch14` within the weight directory. Follow the adapter's
   file layout and retain the pinned checkpoint configuration files.
4. Create `config/hi3d-runtime.json` in the Studio installation. Provide
   absolute paths to the interpreter, adapter, and weights. Use
   `dependencies` for verified package directories outside that interpreter's
   normal import path.

   ```json
   {
     "python": "C:/Tools/Hi3D/runtime/Scripts/python.exe",
     "source": "C:/Tools/Hi3D/source",
     "weights": "C:/Tools/Hi3D/weights",
     "dependencies": []
   }
   ```

   Keep the interpreter, configuration, model weights, and source directories
   under the host operator's control. Restart Studio or Server after setup.

Both resolutions share one configuration. The Hi3D checkpoint files occupy
about 7.73 GB. DINOv2 and CLIP bring the combined weights to about 10.66 GB.
Memory needed during generation also depends on the input geometry and
refinement resolution.

## REST and MCP

Both interfaces use `hi3d_512` and `hi3d_1024` in `master_finishing`.
Check `create_master_finishing` for new generation and
`master_finishing.methods` from the model's finishing board for cached
refinement. See the [REST API](API.md#generation-methods-and-master-finishing)
and [MCP tools](MCP.md#other-tools-and-resources).

Hi3D is licensed under the [Hi3D Open License Agreement Version 1.0](https://github.com/hi3d-official/Hi3Dv1.0/blob/main/LICENSE).
Copyright © 2026 OCEANO HK HOLDING LIMITED. All rights not expressly granted
are reserved. The Hi3D trademarks are owned by OCEANO HK HOLDING LIMITED
or its applicable affiliate(s).
