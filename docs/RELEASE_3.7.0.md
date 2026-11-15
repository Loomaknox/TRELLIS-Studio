# TRELLIS Studio 3.7.0

## Auto Align

Open **Prepare → Texture Projection**, load a transparent cutout, and choose
**Auto Align** in the camera menu. Studio estimates the camera angle, framing
and overlay placement. Review the overlay and refine it using the existing
orbit, placement and guide controls. **Undo** restores the previous alignment.

## Two-view texture projection

- Use **Add second view** to project a complementary reference, such as the
  rear of a character or another side of an object. Each view keeps its own
  reference, camera, selection and alignment settings.
- **Blend views and create copy** combines visible contributions in one linked
  GLB. The transition weights consider viewing angle and distance from the
  projection boundary.
- The copy updates base-color RGB and preserves geometry, UVs, transparency
  and other material maps. Texture Projection supports compatible static,
  single-primitive GLBs with embedded textures and readable UVs.
- The [REST API](API.md#texture-projection-and-baked-game-copies) and [MCP](MCP.md)
  accept a two-view recipe. Existing single-view requests remain compatible.

## Windows x64 Setup

The [Windows installer](WINDOWS_SETUP.md) includes Desktop and Server editions
with Workshop only and Full Studio options. The installer is unsigned.
Verify the download against `SHA256SUMS.txt`.
