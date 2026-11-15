# TRELLIS Studio 3.5.0

Project a reference onto part of an existing model, then use that model as the material source for a lighter game copy. Both tools are available in **Prepare** on Desktop and Server.

## Texture Projection

- Draw one mask on the reference using a freehand lasso, a point-by-point polygon, a rectangle or an ellipse. Its outline follows the same placement as the color overlay on the model.
- Move or scale the placement directly. Use paired face guides for fine alignment and place them around the selected region when working on a small area such as an eye.
- Use a saved reference or upload a PNG, JPEG or WebP. The new copy preserves geometry, UVs, alpha and other material maps.

## Game Copy from HD

- Reduce the selected master to a configurable triangle budget and unwrap new UVs. The default targets are 28,000 triangles for objects and 14,000 for frontal T-pose humanoids.
- Bake base color, roughness, metallic and optional tangent-space normals at 1K, 2K or 4K with Blender. The selected master's current material is used, including prior Texture Projection edits.
- Both operations create linked copies for comparison and are available through the [REST API](API.md) and [MCP](MCP.md).

## Windows x64 Setup

Choose Desktop or Server, then Workshop only or Full Studio. Texture Projection runs on the CPU. Game Copy from HD requires Blender, and Setup downloads its pinned PyMeshLab dependency. Existing users can run Setup against their installation to refresh dependencies. The installer is unsigned. Verify the download with `SHA256SUMS.txt`.

These tools currently support static, single-primitive GLBs with embedded materials and readable UVs. Review fine geometry and material transfer before using a derivative in a project.
