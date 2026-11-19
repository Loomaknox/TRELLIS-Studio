# TRELLIS Studio 3.11.0

## Studio workspace

- Refresh Create, Collection and Animation Studio with a consistent dark palette, compact controls and clearer selection states. Create groups the source image, generation settings, output quality and advanced controls into four steps.
- Add a lit 3D stage with a perspective floor, a glowing ring and rear lighting. Hologram and generation progress share the stage, and the workspace Grid control takes precedence over the decorative floor grid.
- Refresh the README with screenshots from this version, including Rook in Create and Animation Studio.

## Hi3D detail refinement

- Add **Detail Refinement (512)** and **Detail Refinement (1024)** to the master finishing choices for compatible single-image TRELLIS.2 jobs and the Finishing board for saved sources. The refinement resolution is independent of the selected TRELLIS.2 generation profile.
- Install Hi3D as an optional component in Windows Setup for Desktop or Server. Setup checks the NVIDIA GPU, driver and VRAM before offering the component and asks you to accept the Hi3D license before downloading the required files.
- GPU memory use varies with the asset. Start with 512 when Setup recommends it. The [Hi3D guide](HI3D.md) describes supported configurations, storage and the two refinement passes.

## Windows installation

Download the x64 Setup and verify it with `SHA256SUMS.txt`. To upgrade a packaged installation, stop Studio or Server, run Setup against the existing folder and reopen the application. See the [Windows Setup guide](WINDOWS_SETUP.md).
