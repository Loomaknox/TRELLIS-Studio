# Generated motions and My animations

Studio keeps generated humanoid motions in **My animations**, separately from the standard animation catalogue. Generate a motion once, inspect its preview, then use **Add to model** on compatible rigged characters. Each application appends the motion to the selected model, keeping the same ID and collection card. It does not run the generator again. The saved motion remains reusable on other characters.

This is an optional, experimental local component. **Windows Setup can download, build, verify and configure the CPU runtime when you select Kimodo and accept its separate model licences.** The option is off by default and is available with Workshop or Full Studio, in both Desktop and Server. No hosted inference service is used. Existing saved motions can still be reused when generation is disabled.

## Optional automatic installation on Windows

1. Prepare an initialized **WSL2 Linux x64** distribution with Python 3.10 or newer and glibc 2.35 or newer; Ubuntu 22.04 or newer is the reference. Your CPU needs AVX2, FMA and F16C. Allow at least **12 GiB free inside WSL**. This motion engine does not need an NVIDIA GPU or CUDA.
2. In Setup, select **Install Kimodo text-to-motion (optional)**. Read the linked NVIDIA Open Model License and Meta Llama 3 Community License, then select the separate acceptance checkbox if you agree.
3. Leave the installation console open while the pinned source, portable build tools and approximately **9.3 GB of model weights** are downloaded. Setup builds the CPU engine and runs a short test before writing its private runtime configuration.
4. Start or restart Studio, open **Animate → My animations**, and describe a movement. CPU generation can take several minutes, depending on the processor and requested duration.

To add or resume this component later, use **Install Kimodo motion generation** in the Start menu, or double-click **Install Kimodo.cmd** in a source installation. Close Studio and its tray/controller before installing components. Both entry points preserve your library and accounts.

For a source installation, the equivalent command is:

```powershell
.\Install-Studio.ps1 -WorkshopOnly -WithKimodo -NoLaunch
```

Use `-KimodoDistribution Ubuntu-22.04` to select an existing distribution. Without this option, the Windows helper tries the configured distribution and compatible registered WSL2 distributions. `-AcceptKimodoModelLicenses` is available only when you have already read and accepted both model licences; otherwise the console asks for acceptance. It is separate from DINOv3 consent.

Setup does **not** install or enable WSL, create a Linux user, reboot Windows, install a GPU driver, or run `apt`. If WSL is absent or incomplete, it explains how to prepare it and retry. Portable Zig, CMake and Ninja are provisioned privately; a system C++ compiler is not required. See [Windows prerequisites](../INSTALLATION.md#prepare-wsl-for-rigging).

Downloads are pinned by revision, size and SHA-256 and support retry after interruption. A short 60-frame, 10-step installation test is distinct from the normal 100-step generation setting. Configuration is activated only after the runtime, weights and test output have been verified. Existing custom configurations are preserved; invalid or unavailable configurations require review instead of silent replacement. License notices stay with the installed components.

The managed engine is stored under the selected Linux user's `~/.local/share/trellis-studio/kimodo/<installation-id>/<manifest-id>/`, with a verified shared download cache under `~/.cache/trellis-studio/kimodo/`. Studio writes the runtime pointer, skeleton and installation receipt under its private `config/` directory. These files and model weights are not bundled in the public installer or source repository. The uninstaller retains these downloaded components and your data for later reuse.

## Runtime and versions

The supported bridge uses the community [kimodo.cpp CPU runtime](https://github.com/localai-org/kimodo.cpp/tree/75ed52d2d3ec767a9bac79d11060b65d99f61a89), with:

| Component | Pinned revision / variant |
| --- | --- |
| kimodo.cpp | `75ed52d2d3ec767a9bac79d11060b65d99f61a89` |
| GGML | `8c63e70982c95ceb862e3a1073a2c1beef75d60a` |
| [SOMA-RP motion weights](https://huggingface.co/LocalAI-io/Kimodo-SOMA-RP-v1.1-GGML) | Revision `65f8b8ab34ee7524161cc87b20ae4cb4f5d3a12d`, `models/kimodo-soma-rp-v1.1-f32.gguf` |
| [Text encoder](https://huggingface.co/LocalAI-io/Llama-3-Kimodo-GGML) | Revision `f583f3ee2b093f6d9ec524463b4152622abf11a6`, `Llama-3-Kimodo-Q8_0.gguf` and its adjacent `tokenizer.gguf` |
| Portable build tools | Zig 0.14.1, CMake 3.31.8 and Ninja 1.13.2 |

This combination runs **SOMA-RP v1.1**, not NVIDIA's separate official v1.2 implementation. The bridge explicitly selects CPU execution. These tests do not establish CUDA/Vulkan performance or VRAM requirements.

The exact download hashes are in [the Kimodo installer manifest](../installer/kimodo-manifest.json). For an advanced manual installation, provision those sources and weight files separately, retaining their notices. Use a C++23-capable toolchain and the matching GGML source. A CPU build can use the upstream CMake project:

```sh
cmake -S /opt/kimodo/source -B /opt/kimodo/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DKIMODO_GGML_SOURCE_DIR=/opt/kimodo/ggml-source \
  -DKIMODO_ENABLE_VULKAN=OFF \
  -DKIMODO_BUILD_TESTS=OFF -DBUILD_TESTING=OFF
cmake --build /opt/kimodo/build --target kmd-generate
```

These are example paths, not an installer command. Keep the build's required shared libraries available; copying only `kmd-generate` may be insufficient. Verify each downloaded weight against the distribution's `MANIFEST.json` or `SHA256SUMS` before enabling generation. In particular, keep `tokenizer.gguf` beside the selected text GGUF.

## Advanced manual configuration

The automatic installer creates `config/generated-animation-runtime.json`; there is no need to edit JSON for a normal installation. For a manually provisioned runtime, create this file in the Studio installation. It is private and must not be included in a source commit, release package or model export. The example starts disabled:

```json
{
  "enabled": false,
  "backend": "wsl_cpu",
  "distribution": "Ubuntu",
  "executable": "/opt/kimodo/build/kmd-generate",
  "motion_model": "/opt/kimodo/models/kimodo-soma-rp-v1.1-f32.gguf",
  "text_model": "/opt/kimodo/models/Llama-3-Kimodo-Q8_0.gguf",
  "skeleton": "C:/Applications/TRELLIS-Studio/config/soma30.json",
  "model": "SOMA-RP v1.1",
  "runtime": "kimodo.cpp",
  "source_revision": "75ed52d2d3ec767a9bac79d11060b65d99f61a89",
  "model_sha256": "3bf1229f4c1eff1d28f5196a854113da2df9a11a5e21c60694630903bf948ee4",
  "text_encoder_sha256": "b26d0e74b115b33a7f2df5aca04426548365e99217cd590986f8abc4172e4c5c",
  "threads": 8,
  "steps": 100,
  "timeout_seconds": 1200
}
```

Set `enabled` to `true` only after adapting and checking the paths. The recorded hashes document the verified installation; Studio does not rehash all multi-gigabyte weights before each inference.

| Field | Meaning |
| --- | --- |
| `backend` | `wsl_cpu` for Windows with WSL, or `native_cpu` for a Linux-hosted Studio process. |
| `distribution` | Installed WSL distribution name. Required only for `wsl_cpu`; no shell command is accepted. |
| `executable`, `motion_model`, `text_model` | Absolute Linux paths as seen by the runtime. |
| `library_directory` | Optional absolute Linux directory containing the runtime's shared libraries. Overrides `LD_LIBRARY_PATH` for the child process only; useful when deploying a build outside its original build directory. |
| `skeleton` | Absolute path readable by the Studio process: a Windows path when Studio runs on Windows, or a Linux path for native Linux. |
| `threads` | CPU worker threads, integer 1–64; default 8. |
| `steps` | Diffusion steps, integer 10–200; default 100. This is an administrator setting, not a per-target regeneration option. |
| `timeout_seconds` | Runtime limit, integer 60–3600; default 1200. |
| Model/version/hash fields | Portable provenance saved with each generated motion. Do not put local paths or credentials in these descriptions. |

The WSL bridge invokes `python3` and the configured binary with argument arrays, without constructing a shell command from the prompt. Studio's installation and workspace must be on normal local drive paths that WSL can read through `/mnt/<drive>/`. Network/UNC installation paths are not supported by this bridge. The native Linux bridge is available in code; it is not a claim that the full Windows installer or every other Studio component has been validated on Linux.

The skeleton JSON must contain the ordered SOMA30 `names`, `parents` and local `offsets`, with a neutral root, identity local rest rotations, metres, Y-up, +Z-forward and 30 fps. It must match the selected motion model. The pinned port's `scripts/export_bvh.py` contains the reference arrays. They can be extracted without executing that source file:

```python
import ast
import json
from pathlib import Path

source = Path("/path/to/kimodo.cpp/scripts/export_bvh.py")
values = {}
for node in ast.parse(source.read_text(encoding="utf-8")).body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in {
            "SOMA30_NAMES", "SOMA30_PARENTS", "SOMA30_OFFSETS"
        }:
            values[target.id] = ast.literal_eval(node.value)
skeleton = {
    "names": values["SOMA30_NAMES"],
    "parents": values["SOMA30_PARENTS"],
    "offsets": values["SOMA30_OFFSETS"],
    "fps": 30, "units": "metres", "up": "Y", "forward": "+Z",
    "quaternion_order": "xyzw"
}
Path("config/soma30.json").write_text(json.dumps(skeleton, indent=2), encoding="utf-8")
```

Run this from the Studio installation after creating `config/` and adapting the source path. Retain the source revision and its licence when distributing derived installation data.

## Library, queue and preservation

Prompts accept 3–1000 characters, a duration of **2–10 seconds in 0.5-second steps**, and a seed from 0 to 2,147,483,647. Line breaks and tabs in prompts are normalized to spaces. The saved name is optional; it otherwise comes from the prompt. Outputs use 30 fps: a five-second request contains 150 samples, spanning 4.9667 seconds between the first and final keys.

Each workspace stores its entries under its state directory's `generated-animations/<id>/`. A finished entry contains `motion.npz`, `skeleton.json`, `manifest.json` and `preview.glb`. The NPZ stores world hip positions and local XYZW quaternions; it is independent of any target model. File hashes and portable generation provenance are retained. Source NPZ loading disables pickle and limits expanded archive size, frame counts and numeric values.

Generation joins Studio's existing compute queue. It waits for active work instead of interrupting it, and Server uses the same global scheduling and admission controls. Cancellation stops only the selected runtime process group. Pending or failed entries remain identifiable; the interface does not silently substitute a lower step count or a different model.

On Server, each account sees only its own motion library and source files. A new generated motion reserves **one generation credit**, spends it on success, and releases the reservation on failure or cancellation. Applying an already saved motion costs **zero generation credits**. Administrator accounts retain their existing unlimited-credit policy. Canonical sources, previews, updated models and temporary transfer files count towards the account's disk quota.

**Add to model updates the selected rigged model.** It appends the saved clip while preserving its geometry, skinning, materials and other clips. The ID, collection card, name, favourite state and folder membership remain unchanged. A failed or cancelled transfer preserves the previous model; temporary transaction backups are removed after a successful commit, rather than creating a permanent history checkpoint. An already attached clip is rejected instead of silently duplicated. Prepared LODs receive the same transfer and need their own deformation review.

The `in_place` option controls only horizontal root travel. Both values update the same model; neither creates a new card. Standard animation additions follow the same selected-model workflow. Poll the operation's returned `status_url` until it finishes, then refresh the selected model. On Server the status URL identifies an animation operation; on Desktop it identifies the model's job. API clients must check `operation_error` as well as `state`: Desktop can keep a preserved model available as `done` after an unsuccessful animation update.

The REST API exposes list, generation, status, cancellation, file-download and application routes under `/api/v1/my-animations` and `/api/v1/models/{id}/my-animations`; see [API.md](API.md). Matching MCP tools are documented in [MCP.md](MCP.md). A trusted local administrator can seed existing canonical motions through `generated_animations.import_source`; no HTTP route accepts arbitrary filesystem import paths.

## Storage and practical limits

The F32 motion model, Q8 text encoder and tokenizer occupy approximately **9.28 GB / 8.65 GiB** before build files and caches. The automatic installer keeps them on WSL's Linux filesystem and uses hard links from its verified cache where supported. A separate Windows reuse cache or copies on another filesystem need additional storage. Linux-side storage avoids repeatedly streaming the encoder through a mounted Windows drive. Weights are shared by the installation; they are not copied into every user's motion library.

This generates humanoid body movement, not a new rig or skin weights. It does not provide detailed finger articulation, object-aware collisions, guaranteed hand contacts, weapon mechanisms, cloth simulation or arbitrary non-humanoid motion. Check feet, floor penetration, root movement, hands, clothing and extra appendages on every character. The source contact logits are not exposed by this decoder, so Studio does not label inferred contacts as network predictions. Unsupported or ambiguous rigs and incompatible transforms are refused instead of silently changing the mesh.

The preview uses an installed Quaternius CC0 mannequin or a procedural preview. A successful technical transfer is not an artistic or gameplay acceptance test.

## Licences

The optional components have separate terms: kimodo.cpp code is Apache-2.0; GGML is MIT; SOMA model weights retain the [NVIDIA Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/). The [public GGUF encoder distribution](https://huggingface.co/LocalAI-io/Llama-3-Kimodo-GGML) retains the [Meta Llama 3 Community License and Acceptable Use Policy](https://github.com/meta-llama/llama3/blob/main/LICENSE), with MIT-licensed LLM2Vec adapters. **Built with Meta Llama 3.** Retain the supplied licences and attributions. Studio's MIT licence does not replace these terms. The optional installer downloads components only after consent; no Kimodo or Llama weights are embedded in Studio's public source or Setup executable. See [third-party notices](../THIRD_PARTY_NOTICES.md).
