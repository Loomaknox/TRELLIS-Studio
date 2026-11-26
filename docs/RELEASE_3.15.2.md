# TRELLIS Studio 3.15.2

## Windows Setup

- Fix WSL2 detection for UniRig and Kimodo in Windows Setup and **Repair or resume components**. The preflight now passes WSL switches correctly and reads the exit status of the Linux architecture check.
- Reuse verified local checkpoints and Python dependencies across compatible native and standalone components. Windows component installers use canonical runtime paths and install dependencies without creating NTFS hard links.
- Apply the upstream FlexGEMM address calculation fix when preparing or repairing the High Detail runtime. It prevents integer overflow in the CUDA kernels used to decode large meshes.

## Generation

- Game Asset keeps the baked mesh, UVs and maps when vertex welding would remove valid triangles. The worker records triangle counts through reduction, UV unwrapping, baking and welding.
- Game Asset reports progress during QuadDC filtering and shows the current WTiVo operation with its elapsed time and 40-minute limit. Windows can display the specific timeout error when that limit expires.
- Save a custom copy of Game Asset or High Detail from their native workflow settings. Saved profiles are scoped to the account and can be selected from Create and Queue.

Run the Windows Setup in your existing installation folder to update. Use **Repair or resume components** to retry optional components that stopped during setup. See [Windows Setup](WINDOWS_SETUP.md) for WSL2, Blender and GPU requirements.
