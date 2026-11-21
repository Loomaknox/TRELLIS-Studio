# TRELLIS Studio 3.13.0

## Figure Master

- **Figure Master** is a TRELLIS.2 single-image profile for characters, creatures and statues. It uses the 1024 cascade with 30 structure steps, 35 shape steps, 12 material steps, a target of 800,000 triangles and a 2K texture atlas. It keeps the decoded source for later finishing.
- The Windows package uses Studio's native dual contouring. The separately provisioned QuadDC and MeshLib integration remains available to existing installations with the required licensed components.

## Texture methods

- In **Create → Output Quality**, choose **Native PBR**, **Multiview refinement** or **UltraTex** where the input and installed runtime support it. Figure Master selects Multiview refinement when available.
- **UltraTex · 2K** is an optional local evaluation component. It bakes six color views and six metallic/roughness views onto the existing 2K UV atlas. Use **Prepare → Finishing board** to queue a linked texture copy of a compatible model with its saved reference cutout. The pass preserves the mesh and UVs.
- **Texture Projection** now handles zero-length vertex normals in its projection calculations, including when coincident faces cancel out. The texture copy preserves the original geometry and UVs.

## Collection

- Move the pointer across a card to compare the textured and clay renders from the same angle. With the card focused, use the left and right arrow keys.
- Studio saves two small WebP images per model revision. It builds missing pairs from existing models while the host is idle. The Collection loads those images, and the 3D viewer loads the GLB when the model is opened.

## Windows Setup

- The x64 Setup supports Desktop and Server, with NVIDIA GPU, driver and VRAM detection. UltraTex is off by default on a fresh installation. Its dependencies and weights are downloaded separately after accepting the applicable terms. The FLUX.2 Klein 9B weights in this recipe are for non-commercial, non-production use. See [UltraTex setup and hardware guidance](ULTRATEX.md).
- Stop Studio or Server before running Setup in the existing installation folder. Verify the unsigned executable using `SHA256SUMS.txt`. See the [Windows Setup guide](WINDOWS_SETUP.md).
