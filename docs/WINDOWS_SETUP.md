# Windows x64 installer

`TRELLIS-Studio-3.7.0-Setup-x64.exe` is the per-user NSIS installer for Windows x64.
It copies the application and viewer, adds Start menu entries, and never installs
GPU drivers, Blender or WSL. The executable is unsigned. Do not
treat a SHA-256 checksum as an Authenticode signature.

## Install and open

1. Run Setup. The default folder is `%LOCALAPPDATA%\Programs\TRELLIS Studio`.
   First choose **TRELLIS Desktop (single user)** or **TRELLIS Server (multi-user)**.
   Then select **Workshop only** or **Full Studio** for either edition. Both
   Server options include first-time administrator setup and a choice of local,
   LAN with your own certificate, or Internet with automatically managed HTTPS.
   See [TRELLIS Server](SERVER.md) for domain, router and firewall settings.
   Full Studio installs TRELLIS.2,
   UniRig and Pixal3D during Setup. Allow around 29 GiB for model downloads plus
   dependencies and roughly 100 GiB of free space for installation and caches.
   Prepare a supported NVIDIA driver, Blender and Ubuntu 22.04 under WSL2 first.
   The console displays progress and asks for explicit acceptance of the
   DINOv3 terms. If a download or component fails, see `logs/full-setup.log`
   in the installation folder and rerun Setup with **Full Studio** selected.
   The separate **Optional motion generation** page offers Kimodo for either
   edition and component selection. It is unchecked by default. Selecting it
   requires explicit acceptance of the NVIDIA Open Model License and Meta Llama 3
   Community License. Setup then downloads, builds, tests and configures the CPU
   runtime automatically. Allow approximately 9.3 GB of additional weights and at
   least 12 GiB free inside an initialized WSL2 Linux x64 distribution. Python
   3.10+, glibc 2.35+ and an AVX2/FMA/F16C CPU are required. Ubuntu 22.04 or newer
   is the reference; this component needs neither NVIDIA CUDA nor a system C++
   compiler. Setup does not enable WSL, create a Linux user or restart Windows.
2. Open **TRELLIS Studio** or **TRELLIS Server** from the Start menu. Setup can
   also create a desktop shortcut. The workshop downloads the private Python
   runtime and libraries over HTTPS during Server setup or the first Desktop
   launch in older installers. Current Setup prepares Workshop during installation.
   The shortcut opens a tray controller with Start, Stop, Open and Quit actions.
   Quitting the icon leaves services running. It runs on the CPU with the bundled web viewer.
3. Import a GLB with embedded assets. The workshop supports viewing, inspection,
   library management, and GLB export without Blender. Blender is needed for
   importing other formats, some uncommon GLB extensions, and Blender-dependent
   preparation and export formats. Install Blender separately or set
   `TRELLIS_BLENDER` to its executable.

Workshop and Full Studio both install pinned **PyMeshLab 2025.7.post1** for
CPU-only HD-to-game reduction (about 55 MB downloaded from PyPI, not bundled in
the executable). Setup verifies its native reduction filter with a small mesh.
**Baked game copies** additionally need Blender 5.2 LTS for UVs and PBR/normal
transfer. Standard Blender installations are discovered automatically. Blender
is not installed by Setup, and Workshop still works when it is absent; the
setup diagnostic and the operation's availability message explain the missing
component. Texture projection needs neither Blender nor an NVIDIA GPU.

To update an existing installation, stop Studio/Server and rerun Setup into the
same folder. Changed dependency pins trigger a Workshop refresh without moving
the collection or resetting accounts and HTTPS settings. The Desktop launcher
also checks the saved dependency fingerprint before starting. See the
[CPU finishing setup guide](../INSTALLATION.md#cpu-texture-projection-and-baked-game-copies)
for source-installation commands and portable Blender configuration.

For local generation, stop the Studio with **Stop TRELLIS Studio** in the Start
menu. Choose **Install TRELLIS generation** for the NVIDIA build without WSL, or
**Install generation and UniRig** after setting up Ubuntu 22.04 in WSL. The
generation installer shows the DINOv3 terms before downloading the weights.
**Install Pixal3D** is available once standard generation is installed. The
[requirements and troubleshooting guide](../INSTALLATION.md) covers the driver,
disk space, optional WSL setup and verified downloads.

**Install Kimodo motion generation** adds or resumes the optional CPU engine
later, including on a Workshop-only installation. The helper selects a compatible
existing WSL2 distribution and presents the model licences if they have not been
accepted for this invocation. Pinned downloads and a private portable toolchain
are verified before use; the runtime configuration is activated after a short
generation check. Existing custom configuration is preserved. If WSL is missing,
complete its first-run setup and rerun this shortcut. See
[generated motions](MOTION_GENERATION.md) for exact versions, storage locations
and practical limits. Saved motions remain reusable when generation is disabled.

The packaged copy keeps a separate library from a source installation. The
default packaged ports are 7870 (Studio) and 7871 (MCP), separate from the
source installation's 7860/7861. Override them with `TRELLIS_PORT` and
`TRELLIS_MCP_PORT` if needed. Transfer a collection using the Studio ZIP backup/restore
workflow. The installer will not adopt or replace a source installation in place.

Close Studio and its component installer before running Setup again. If the
installed copy is open during uninstallation, the uninstaller offers to stop
it and its local MCP bridge. It waits for the user to finish any generation or
export before it will proceed; a separate MCP client may also need to be closed.
The uninstaller removes packaged program files and Start menu entries. Library,
profiles, runtime downloads and installed environments stay in the installation
directory, so reinstalling there can reuse them.
Server configuration and Caddy certificate storage are also retained. If you enabled
the optional elevated Windows Firewall rule, remove it separately in Windows Firewall
when permanently retiring that installation; the per-user uninstaller does not elevate.
The optional Kimodo engine and verified cache in the Linux user's home directory
are also retained; they are not embedded in the Setup executable or a collection ZIP.

## Build and qualify

From a TRELLIS Studio checkout, install Python 3.11 or newer, Node.js and obtain
[NSIS 3.13](https://nsis.sourceforge.io/Download). Then run:

```powershell
.\installer\windows\Build-Setup.ps1 -Compiler 'C:\path\to\makensis.exe'
```

The script compiles the tray using the Windows .NET Framework C# compiler,
verifies the pinned Caddy binary, and assembles the source allowlist and browser dependencies in
a separate staging directory, checks JavaScript syntax, and writes the
installer, its SHA-256, and the payload inventory under `Builds\Windows`.
No working library, model weights, caches, or personal configuration are copied.
Both source and payload inventories pass `installer/audit_public.py` before packaging.
The domain and certificates are created only on the user's own installation.
The [NSIS license](https://nsis.sourceforge.io/License) applies to the installer
engine; TRELLIS Studio retains its MIT license.

Before distributing a binary, test installation from a fresh Windows account
or VM, no-GPU workshop startup, self-contained GLB import/export, interruption
and recovery, reinstall with a collection, and removal with data retention.
Validate generation and rig on supported hardware separately. Publish the
signature, checksum and actual support matrix with the binary in GitHub Releases.

For public Authenticode signing, [SignPath Foundation](https://signpath.org/terms.html)
is free for accepted open source projects. The application must already exist
in the form to be signed; review the scope of downloaded model and GPU
dependencies with the foundation. [Azure Artifact Signing](https://learn.microsoft.com/windows/apps/package-and-deploy/smartscreen-reputation)
starts at USD 9.99/month; its [Public Trust eligibility](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart#prerequisites)
for individuals is limited to the US and Canada. Signing does not guarantee
that SmartScreen will immediately recognise a newly distributed binary.
