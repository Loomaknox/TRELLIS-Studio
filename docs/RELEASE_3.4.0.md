# TRELLIS Studio 3.4.0

This release brings configurable Desktop and Server installation, a Windows tray
controller, optional Internet access through HTTPS, and a persistent library of
generated humanoid motions. It also adds experimental controls for HD-to-game
finishing and an animated hologram preview.

## Windows setup, Server and HTTPS

- Choose Desktop or multi-user Server, with Workshop or Full Studio components.
  Server setup offers this PC only, LAN with your own certificate, or Internet
  access with a configurable domain and Caddy-managed HTTPS. Advanced settings
  expose the ports, data location and optional firewall/startup integration.
- Start, stop and open the selected edition from the notification-area icon.
  Quit remains available during startup and closes the icon while leaving the
  services running. Stop refuses to interrupt active generation, exports or uploads.
- Upgrades preserve existing Server data, accounts, authentication settings and
  HTTPS configuration. Each installation generates its own domain configuration,
  certificates and logs; personal deployment settings are not shipped.
- Two-factor authentication is required for administrators and optional for
  other accounts. Existing enabled factors remain enabled. Promotion, reset and
  offline administrator recovery follow the same policy.
- The builder compiles the tray controller from source, verifies the pinned
  Caddy download and audits the public source and packaged file inventories.
- Desktop's local MCP bridge no longer inherits credentials or private
  certificate settings from a separately configured Server client. The caller's
  own environment settings are preserved.

The Internet wizard cannot register a domain, modify a router or bypass CGNAT.
Automatic certificate issuance and renewal require a working public DNS name and
an externally reachable TCP 443 route. A successful local health check is not an
Internet connectivity test. See [Server setup](SERVER.md).

## My animations

- The animation workspace separates **Standard**, **My animations** and **Added**.
  Existing standard animations remain available. Personal motion cards include
  actual animated 3D previews, generation state and clear availability messages.
- Describe a humanoid action and choose a duration from 2 to 10 seconds, in
  half-second increments. An optional seed makes experiments reproducible within
  the selected engine and settings. Generation runs asynchronously and can be cancelled.
- Generate once and retain the motion's canonical samples, skeleton, preview
  and provenance independently of any character. Server libraries and downloads
  are private to their owning account and survive application restarts.
- **Add to model** appends the saved motion to the selected rigged model, keeping
  its ID, collection card, name and organisation. Geometry, materials, skinning
  and existing clips are preserved. Standard additions also update the selected
  model. Already attached motions show **Added**. No second generation is required.
  Failed or cancelled transfers retain the previous model through transactional
  publication; successful additions do not create another card.
- REST API v1 and five MCP tools expose listing, generation, polling,
  cancellation and application. Source and preview downloads are also available
  through the authenticated REST API.
- On Server, a standard account reserves one generation credit for a new motion.
  It is spent on success and released on failure or cancellation. Applying a
  saved motion costs no credits. Administrators retain unlimited generation credits.
  Sources, previews, updated models and temporary transfer files count towards disk quotas.

The API's `in_place` option suppresses horizontal root travel; both values update
the selected model. It is not a copy-versus-update option and does not lock the
feet to the ground. See [motion generation](MOTION_GENERATION.md), [REST API](API.md)
and [MCP tools](MCP.md).

## Optional automatic Kimodo installation

Windows Setup can install the **kimodo.cpp CPU / SOMA-RP v1.1** engine for either
edition, including Workshop-only installations. It is unchecked by default and
requires separate acceptance of the NVIDIA Open Model License and Meta Llama 3
Community License. **Install Kimodo motion generation** in the Start menu adds
or resumes this component later.

The component requires an already initialized WSL2 Linux x64 distribution with
Python 3.10+, glibc 2.35+ and an AVX2/FMA/F16C CPU. Ubuntu 22.04 or newer is the
reference. Allow at least 12 GiB free inside WSL and approximately 9.4 GB of
downloads, including 9.28 GB of weights and tokenizer. This CPU engine does not
require NVIDIA CUDA or a system C++ compiler.

Setup retrieves pinned sources, weights and portable Zig/CMake/Ninja tools,
checks their sizes and SHA-256 hashes, builds privately, and runs a short motion
generation check before activating the configuration. Interrupted downloads can
be resumed; verified cache entries can be reused. Existing custom configurations
are preserved, invalid configurations are reported, and managed reinstallations
retain the user's enabled state and generation settings.

Setup does not enable WSL, create a Linux account, install drivers or run `apt`.
Downloaded runtime components and licences remain private to the installation;
model weights are not embedded in the public source or Setup executable. The
uninstaller retains downloaded runtimes and user data for reuse. Full model and
encoder terms remain applicable; Studio's MIT licence does not replace them.
See [requirements, locations and licences](MOTION_GENERATION.md).

## HD finishing and preview

- The finishing board offers separate HD, 14K and 10K comparison recipes,
  reconstruction ceilings of 512/768/1024 and material voxel interpolation.
  The protected **Game - Default** profile remains unchanged.
- Normal maps can use a newly exported HD parent as their detail source.
  Recorded transforms, source lineage and a verified file fingerprint protect
  alignment. Older or edited donors require a new finishing export.
- Hologram mode builds the visible model progressively with laser beams.
  Selecting it again replays the effect; reduced motion shows the complete model.
  Preview materials do not alter the geometry or exported textures.
- While generation runs, a laser projection can display the prepared reference
  image with its transparency and the actual job status. When existing geometry
  is available, a temporary hologram preview is restored to the previous viewing
  material afterwards. This is an activity visualization, not partial generated geometry.

These finishing controls are experimental. They do not guarantee watertight
topology, clean faces/hands, animation-ready edge flow or parity with commercial
generation services. Independent retexturing and quad-retopology investigations
are not included as product features in this release.

## Validation and known limits

Release preparation includes automated account/MFA, origin, queue, credit,
runtime, retargeting, MCP and Windows controller checks; isolated installation
and lifecycle checks; and actual authenticated UI playback at desktop and mobile
sizes. Real generated-motion tests preserve the selected characters' original
geometry, skinning, materials and clips. A private Server/Caddy lifecycle test
uses its own test certificate. These checks do not replace fresh-machine setup
or public ACME validation on a user's network.

The optional motion installer is checked separately for pinned downloads, retry,
guarded extraction, configuration preservation and activation after successful
validation. Its minimum glibc target is 2.35; the existing development host is
newer, so the minimum-version operating system is not claimed as fully tested.
The Windows binaries are unsigned; a published SHA-256 checksum verifies file
integrity and is not an Authenticode signature.

Generated motions remain experimental: foot sliding, imperfect stops, ground
penetration, prompt mismatch and rig-dependent deformation can occur. The
current bridge generates SOMA30 body motion; it does not provide detailed finger
animation or object/contact constraints. Inspect each result before game use.
CPU performance depends on the processor, duration and diffusion settings.
Saved motions can still be reused when the optional engine is disabled.

For installation and recovery, see [Windows setup](WINDOWS_SETUP.md) and
[source installation](../INSTALLATION.md).
