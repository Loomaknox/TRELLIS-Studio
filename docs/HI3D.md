# Hi3D detail refinement

[Powered by Hi3D 1.0](http://hi3d.ai/).

Detail Refinement rebuilds the decoded surface of a single-image TRELLIS.2
generation from its reference cutout. The 512 and 1024 labels describe the Hi3D
refinement resolution. Both methods start from a native 512 TRELLIS.2 source.

## Studio workflow

- In **Create**, choose **HD Master** and **TRELLIS.2 · Single image**, then
  choose **Detail Refinement (512)** or **Detail Refinement (1024)** under
  **Master finishing**. Studio uses a 512 source and keeps its decoded cache.
- In **Prepare → Finishing board**, choose a detail refinement on a compatible
  model with a saved native 512 source and its cutout. Each result is a linked
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

## Configure the optional runtime

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
