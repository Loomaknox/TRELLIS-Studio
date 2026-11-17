# TRELLIS Studio 3.10.0

## One Windows installer with hardware-aware components

- The x64 Setup identifies the NVIDIA GPU, driver and VRAM before optional
  engine downloads. It selects pinned Windows and WSL packages for that GPU.
- Review the detected Blender installation or browse to a different executable.
- Install the Workshop and standard animation library on their own, or add the
  supported TRELLIS.2, Pixal3D, UniRig and Kimodo components. The Workshop can
  animate compatible imported rigs without running UniRig.
- **Repair or resume components** in the Start menu verifies completed components
  and resumes the ones that need work. Generation and rigging run small CUDA
  smoke tests before their model downloads.
- Setup uses the TRELLIS Studio artwork and shows a VRAM advisory below the
  12 GB reference. TRELLIS.2 at 512 is a starting point for lower-memory GPUs.

## GPU coverage

- **RTX 30 / 40** use the pinned Windows CUDA 12.8 environment and the existing
  WSL CUDA 12.4 UniRig package profile.
- **RTX 50** use the Windows CUDA 12.8 environment with the Blackwell attention
  adjustment. UniRig selects a separate **experimental** WSL profile with
  PyTorch 2.8/CUDA 12.8, matching FlashAttention and sparse-convolution wheels.
  Validate a real skeleton, skin and export on the target RTX 50. Package
  and probe verification alone cannot establish full Blackwell support.
- **RTX 20** generation is experimental. UniRig is not offered on this profile.
- **GTX 10** can use the Workshop and CPU animation features where their own
  prerequisites are met. Local generation and UniRig are not offered on this
  profile.

## Studio features from main

- **Create** brings together Game Asset and HD Master. Choose TRELLIS.2 or
  Pixal3D from the same workflow, including Pixal3D single-image mode when its
  additional runtime and weights are installed.
- HD Master Finishing offers Studio 768 and the optional WTiVo 1024 pass.

The Setup is unsigned. Download it together with `SHA256SUMS.txt` and see the
[Windows Setup guide](WINDOWS_SETUP.md) for component requirements, updates and
repair.
