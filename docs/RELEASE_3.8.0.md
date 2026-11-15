# TRELLIS Studio 3.8.0

## HD Reconstruction (768)

- Enable **HD Reconstruction (768)** in **Dense Master** before generating. To
  try it on a compatible saved generation, open **Remesh** or add the recipe in
  the **Finishing board**. The saved source remains available for comparison.
- The recipe uses a 768 reconstruction grid, fills small holes and skips
  pre-decimation. It can improve surface continuity on cracked meshes. Compare
  fine edges and intentional openings with the original before choosing a master.

## Protected areas in Game Copy from HD

- Open **Prepare > Game Copy from HD** on a compatible static GLB. Use **Add
  zone** to mark areas on the 3D model, such as handles, cables or grilles.
  Adjust each zone's **Radius** and **Priority** to keep more detail there
  within the same triangle budget.
- **Humanoid** automatically gives the face and hands higher priority on
  upright, front-facing T-pose characters. You can add manual zones alongside
  those automatic priorities. Use **Object** for props or other poses.
- Studio creates a linked game copy with baked textures and optional tangent
  normals. Compare thin parts and silhouettes against the source at your
  target budget.

The [REST API](API.md#cached-finishing-and-retry) and [MCP](MCP.md) expose
HD reconstruction and protected regions for supported operations. See the
[game-copy recipe](API.md#texture-projection-and-baked-game-copies).

## Windows x64 Setup

The [Windows installer](WINDOWS_SETUP.md) includes Desktop and Server editions
with Workshop only and Full Studio options. The installer is unsigned.
Verify the download against `SHA256SUMS.txt`.
