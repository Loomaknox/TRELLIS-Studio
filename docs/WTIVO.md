# WTiVo reconstruction

Studio can use a separately installed WTiVo runtime to reconstruct a cached
decoded mesh. A 1024-or-higher saved source is required. Enable **WTiVo
Reconstruction (1024)** in **Remesh** or in one **Finishing Board** recipe. The
board can queue WTiVo and **HD Reconstruction (768)** together at the same
triangle and texture budget for comparison.

WTiVo reconstructs the geometry at grid 1024. Studio then reduces and unwraps
that result and bakes the original decoded material volume onto its new UVs.
The original model and source cache remain available. The triangle budget is a
ceiling. Inspect intentional openings, fingers, accessories and texture seams.
The WTiVo audit describes geometry **before** simplification. A reduced or
multi-component result may still report open edges or multiple shells.

## HD Master Finishing

The **Prepare → HD Master Finishing** workflow adapts the dense part of
[PixelArtistry workflow 02](https://github.com/pixelartistry/PixelArtistry-Watertight-Meshes/blob/main/workflows/PixelArtistry_02_Image_to_GameReady_Asset.json).
It uses WTiVo grid 1024 with all output components, followed by Blender's
[Decimate Collapse](https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/decimate.html)
to trim oversized surfaces, then Studio UV unwrapping and PBR baking from the
original sparse material volume. The saved inference resolution defines available
source detail. The reconstruction grid defines the intermediate surface.

The master uses a 3M triangle ceiling and defaults to a 4K atlas on hosts with
4K enabled. Studio uses its own Blender bridge and UV/PBR exporter. The source
can be a saved 1024 or 1536 generation. The workflow preserves indexed
connectivity after the trim, removes tiny isolated shells and reports indexed
and exact-position edge incidence before UV splitting. Compare these diagnostics
before deciding whether the model meets a print or game topology requirement.
The built-in alternative uses Studio's 768 reconstruction and CuMesh cleanup.

The bake samples the nearest point on the decoded surface and blends occupied
material voxels. It records coverage and inpainted texels. Pixel Match remains
available on compatible Pixal3D models with verified saved views. The Game Copy
from HD tool can use the finished master as a donor for reduced geometry and
normal baking.

## Provision the external runtime

On a Windows x64 host with an NVIDIA GPU, provide a private Python 3.12 x64
virtual environment with PyTorch `2.8.0+cu128`, NumPy, SciPy and Trimesh. Keep it
separate from Studio's Python. Obtain the [verified WTiVo revision](https://github.com/Mstafa-awad/WTiVo-WatertightVoxel-ComfyuiNode/tree/fb9e9ea6a7deec965d3a4bf43ba7a4a9ff3856f3)
and unpack its `ForNonBlackwellgpu(rtx50 and below).rar` native package into the
revision's `build` directory so `wtivo.py` can load it. Use the pinned contents
without mixing builds. Retain the upstream notices and [licensing information](https://github.com/Mstafa-awad/WTiVo-WatertightVoxel-ComfyuiNode/blob/fb9e9ea6a7deec965d3a4bf43ba7a4a9ff3856f3/LICENSING.md).

The host operator creates a private `config/wtivo-runtime.json` with two
absolute paths. Use folders controlled by the operator and inaccessible for
modification by other Studio users.

```json
{
  "python": "C:/Tools/WTiVo/runtime/Scripts/python.exe",
  "source": "C:/Tools/WTiVo/source"
}
```

`source` contains `wtivo.py` and its `build` directory. Studio checks the
runtime metadata and the fingerprints of the external script and native
binaries before use. Installation, configuration and binaries stay on the
operator's machine. The public Studio Setup ships the geometry bridge only.

## REST and MCP

`GET /api/v1/models/{id}/finishing-board` returns `wtivo_reconstruction` and
`wtivo_reason`. If supported, use `{"wtivo_reconstruction": true}` with the
normal refinish request or as one of the board variants. `triangles` defaults
to 1,200,000 and `texture_size` defaults to the selected model's atlas size.
An optional normal bake uses the same settings as other finishing recipes.
The MCP `get_finishing_options` and `queue_refinish` tools expose the same
capability and single-recipe fields.

WTiVo, Studio 768, hole repair and adaptive finishing are separate choices.
WTiVo fixes the reconstruction grid, initial hole handling and pre-decimation.
If the runtime is unavailable the existing Studio methods are available.
The completed result records the WTiVo grid and audit in
`result.finishing.wtivo_reconstruction`.
