# TRELLIS Studio 3.12.0

## Texture refinement

- Harmonize the color palette with the reference image and selectively blend six generated views into the baked color map. **High Detail** enables **Multiview texture refinement** by default for compatible TRELLIS.2 and Pixal3D single-image jobs when the optional runtime is ready. Other profiles can opt in.
- In **Prepare → Finishing board**, choose **Queue texture refinement** to create a linked copy of a completed, compatible GLB with a saved reference cutout. The copy keeps the exact mesh, UVs, atlas size and other PBR maps. Compare it with the original directly from the board.
- Windows Setup offers the multiview texture component as an optional download of approximately 3.3 GB. It requires an eligible NVIDIA GPU with at least 8 GB VRAM and recommends 12 GB.

## Profiles and finishing

- **High Detail** is the starting profile in Create. It uses the TRELLIS.2 1024 cascade, 12 / 25 / 12 steps, a 300,000-triangle target and 2K textures. It keeps the decoded source for later variants. The API still defaults to **Game Asset**.
- **Detail Study** combines single-image TRELLIS.2, Hi3D 1024 and a 4K material pass on the refined surface. **Retexture after Hi3D** and advanced Hi3D settings are also available in the Finishing board.
- **None** under **Master finishing** exports the decoded TRELLIS.2 surface with its native materials and saves the source for later variants.
- Edit advanced generation settings with field-level help. Use master finishing with compatible custom profiles and delete custom profiles directly from Create. Historical Humanoid Experimental recipes remain readable.
- Fix a stall in Hi3D material voxelization and correct stale Studio scripts after an update.

## Windows installation

- Download the x64 Setup and verify it with `SHA256SUMS.txt`. Upgrade by stopping Studio or Server and running Setup in the existing installation folder.
- Setup uses the detected NVIDIA GPU, driver and VRAM to guide optional component selection. Hi3D remains optional. Setup can move verified legacy default Hi3D weights to `models/hi3d` without downloading them again.
- Installing or updating TRELLIS.2 also provisions the approximately 709 MB encoder used by **Retexture after Hi3D**.
- See the [Windows Setup guide](WINDOWS_SETUP.md) and the [Hi3D guide](HI3D.md) for installation, model terms and hardware details.
