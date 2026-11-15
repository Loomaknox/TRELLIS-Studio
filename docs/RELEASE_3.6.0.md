# TRELLIS Studio 3.6.0

## Texture Projection

- Use six preset views, including **Back** for a rear reference. Use **Orbit** to match an angled photograph with an orthographic or perspective camera. Adjust yaw, pitch, roll and field of view in the camera controls.
- The camera shown in the preview determines the visible surfaces that receive the projected color. Align the reference manually using the overlay or four paired points.
- The compact toolbar gives quick access to selection shapes, camera controls and projection settings. Zoom controls are aligned across both panes, and slider tracks stay visible between adjustments.
- Texture Projection creates a linked copy with updated base-color RGB. It preserves geometry, UVs, alpha and the other material maps. It supports compatible static, single-primitive GLBs with embedded materials and readable UVs.
- The [REST API](API.md#texture-projection-and-baked-game-copies) and [MCP](MCP.md) accept custom projection cameras. Existing orthographic recipes remain compatible.

## Server generation preview

Studio shows **Finalizing model** while Server makes a generated GLB available. The viewer opens the model automatically when the file is ready. This fixes the brief HTTP 409 banner at the end of a successful generation.

## Windows x64 Setup

The [Windows installer](WINDOWS_SETUP.md) includes Desktop and Server editions, with Workshop only and Full Studio options. The installer is unsigned. Verify the file against `SHA256SUMS.txt`.
