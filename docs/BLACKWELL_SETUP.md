# Windows installation fixes and experimental Blackwell rigging

The compatibility branch fixes the WSL architecture probe used by Kimodo,
generates a Zig wrapper which filters CMake's unsupported `-Wl,-rpath-link,...`
hint, and discovers Blender on PATH or in standard folders on fixed local drives.
An explicit `TRELLIS_BLENDER` setting remains authoritative.

These are source changes. Running an old upstream Setup executable can overwrite
the scripts with its own payload. Use this fork's source scripts or build a new
Setup with `installer/windows/Build-Setup.ps1`. Do not expect the original
author's existing executable to contain these changes. Keep the original branch
separate when integrating future upstream changes.

## Status

The sm_120 UniRig profile is **experimental**. A successful torch matrix test does
not validate FlashAttention, torch-cluster, torch-scatter, sparse convolution, or
the whole rigging pipeline. Startup now executes small kernels from each of
these operators before declaring UniRig ready. Model weights are still loaded
only for a real job.

The original Torch 2.5/CUDA 12.4 profile remains available for older GPUs. The
installer auto-selects the new profile only for sm_120 devices. Mixed older/newer
GPU sets and other new architectures require explicit review.

## Blackwell prerequisites

Inside the selected WSL2 distribution, provide:

- Git and a working GNU C++ compiler (`g++`).
- **CUDA Toolkit 12.8**, with its `bin` directory on PATH, so `nvcc --version`
  reports release 12.8. The compiler is needed to build the CUDA extensions.
- Sufficient memory and disk for compilation, in addition to model downloads.

Use NVIDIA's [CUDA 12.8 Linux installation guide](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-installation-guide-linux/index.html)
for the toolkit. Under WSL, use the Windows NVIDIA driver; do not install a Linux
display driver. The helper checks prerequisites before modifying any environment
and does not run sudo, change drivers, or install a system toolkit itself.

## Stack and isolation

| Component | Experimental sm_120 profile |
| --- | --- |
| Python | Private CPython 3.11 |
| Torch / torchvision | 2.8.0+cu128 / 0.23.0+cu128, official PyTorch index |
| torch-scatter / torch-cluster | 2.1.2+pt28cu128 / 1.6.3+pt28cu128, official PyG index |
| cumm | Source tag v0.8.2 at `4c77b38d1ab57d5d1c157adddf67dad93f3a446b` |
| spconv | Source tag v2.3.8 at `263d6b47425ef843c82f997b12d8b714013d216c` |
| FlashAttention | Official v2.8.3 CPython 3.11 / torch 2.8 CXX11-ABI Linux wheel; SHA-256 `3d41b2fc55753faa7f45d6568ea73a96b96afb48b82994ab9b49bcbcb6c87588` |

cumm/spconv build against the installed Torch ABI, with native sm_120 code
and one compiler job/thread by default. `MAX_JOBS` and `NVCC_THREADS` can
increase parallelism when sufficient RAM is available. FlashAttention can
consume several GiB per compiler process, so a four-job build is unsafe on
a typical 16 GiB WSL VM. This avoids
mixing the old Torch 2.5 extension wheels with Torch 2.8. The old NVIDIA, sympy
and Triton pins are omitted for this profile so Torch supplies its matching
runtime dependencies. Other application pins remain unchanged.

FlashAttention uses the checksum-verified artifact from the official v2.8.3
release. Binary inspection confirmed native sm_120 kernels; real varlen attention
and full neural skin inference were tested. The helper refuses a different
Python/Torch/CXX11 ABI or a corrupted cache. Set `TRELLIS_UNIRIG_FLASH_SOURCE=1`
to compile the same pinned source revision instead. That opt-in build retains
its own cache and can be much slower and more memory intensive.

The upstream bpy 4.2.0 CPython 3.11 Linux wheel incorrectly labels its internal
WHEEL metadata as cp39, despite declaring `Requires-Python: ==3.11.*`. The helper
corrects only the exact known WHEEL content and its corresponding RECORD hash;
unknown metadata is preserved and rejected. No native code is changed. Full
`uv pip check` remains mandatory, alongside actual bpy and CUDA execution. The
legacy application pin is retained.

The spconv source metadata caps cumm below 0.8 although cumm 0.8.2 adds native
sm_120 build flags. The helper explicitly changes that bound to `>=0.8.2,<0.9.0`
in its private build checkout. **This override is not an upstream compatibility
guarantee.** The operator tests and a real inference job must validate it.
Unknown metadata and unrelated source checkouts are preserved and rejected.

Torch 2.8's protected checkpoint loader also rejects the `box.box.Box` metadata
in the pinned skin checkpoint. A small inference entry point allows only that
known type within a `torch.serialization.safe_globals` context. It keeps
weights-only loading and leaves upstream source unchanged.

The default Blackwell environment is a sibling of the legacy environment, with
the suffix `-blackwell`. The old venv is retained. A small `blackwell-ready`
marker in the legacy base selects the new runtime only after installation,
CUDA operator checks, model files, and configuration checks succeed. Interrupted
compilation does not activate the new environment. An explicit
`TRELLIS_UNIRIG_ENV` uses exactly the specified directory instead.

To force a profile for diagnosis, set `TRELLIS_UNIRIG_PROFILE` to `legacy` or
`blackwell` in the Linux environment. The default is `auto`. A future invocation
with the same choice resumes the private source/build caches.

## Running the corrected scripts

Once the corrected source scripts and required model files are present in the
installation being tested, run its `installer/install_unirig.sh` through the
selected WSL distribution. For example, with a source checkout on D:

```powershell
wsl -d Ubuntu-22.04 -- bash "/mnt/d/AI/TRELLIS-Studio/installer/install_unirig.sh"
wsl -d Ubuntu-22.04 -- bash "/mnt/d/AI/TRELLIS-Studio/UniRig/check-runtime.sh"
```

Replace the example path with the installation under test. A fresh Git clone
contains neither engine source/model downloads nor Python environments. Do not
run a fresh Full Setup just to test the scripts if you intend to reuse an existing
installation's models. Preserve and review that installation before applying
source updates.

UniRig's startup report is written to `logs/components.json`. It now preserves
other component entries and uses an atomic file replacement. CUDA detection
without working kernels cannot produce `ready: true`. Startup retains the
detailed reason when a probe fails.

## Validation and remaining acceptance

Local/offline checks:

```powershell
python -B -m unittest discover -s tests -p installation_compatibility.py -v
python -B tests/kimodo_installer.py
python -B tests/game_copy_installer.py
powershell -NoProfile -ExecutionPolicy Bypass -File tests/kimodo_probe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tests/kimodo_windows.ps1
```

The execution-policy option applies only to each test process. Linux also runs
the real compiler-wrapper argument test and Bash syntax checks in the
`Installation compatibility` GitHub Actions workflow. These checks do not build
the GPU stack or download model weights.

For each target machine, the acceptance checklist is:

1. Build the private Blackwell environment under WSL and pass its CUDA operators.
2. Run a complete skeleton and skin-weight job with the pinned UniRig checkpoints.
3. Review the generated rig visually and export it to the desired application.
4. Generate an animation from Kimodo's My animations interface and test the result.
5. Test TRELLIS and Pixal3D generation and MCP separately.

Successful unit checks alone do not establish full studio functionality.

## Windows xformers attention

The pinned xformers dispatcher can select its Hopper FlashAttention 3 kernel on
Blackwell. A real generation on sm_120 aborted with an invalid CUDA argument in
that kernel even though a matrix calculation succeeded. Both image and Pixal3D
workers now disable FA3 on compute capability >= 10, retaining the normal
xformers operator selection for the remaining kernels. Ada and Hopper retain
their default dispatch. This uses the private switch in the pinned xformers
version; review it when updating that dependency.

Target-machine tests on RTX 5070 Ti / Windows / CUDA 12.8 completed a textured
image-to-3D job (9,589 triangles, 53.7 s) and a three-view Pixal3D job (9,736
triangles, 59.9 s). Synthetic character images were used. Kimodo CPU inference
also generated a valid 60-frame animation, and Blender/UniRig landmark and skin
transfer adapters passed with non-unit nested transforms. The full neural skeleton/skin job also completed on the generated model,
producing a 28-bone skinned GLB opened in Blender. Its geometry did not pass the
conservative humanoid mapping, so no humanoid motions were attached. A separate
Unity 6000.6.6f1 project passed the repository's import/update/rollback regression
(`TRELLIS REIMPORT PASS`). These are functional tests, not an artistic quality
guarantee for arbitrary characters.

A separate CC0 reference mannequin was stripped of its original rig and passed
full neural inference: 52 predicted bones, normalized skin weights, and automatic
humanoid mapping. The authored Idle/Walk clips and a real 60-frame Kimodo motion
were transferred and exported together as an animated Unity FBX. Original GLB
geometry, materials and pre-existing clips passed preservation checks. The
validated runtime was activated in the installed Studio after explicit kernel
checks; the previous environment and changed Windows scripts were backed up.

## Primary references

- [PyTorch Blackwell/CUDA 12.8 support](https://pytorch.org/blog/pytorch-2-7/).
- [Official Torch 2.8/CUDA 12.8 PyG wheels](https://data.pyg.org/whl/torch-2.8.0+cu128.html).
- [FlashAttention v2.8.3 build targets](https://github.com/Dao-AILab/flash-attention/blob/v2.8.3/setup.py).
- [cumm v0.8.2 architecture flags](https://github.com/FindDefinition/cumm/blob/v0.8.2/cumm/common.py).
- [spconv v2.3.8 dependency metadata](https://github.com/traveller59/spconv/blob/v2.3.8/setup.py).
