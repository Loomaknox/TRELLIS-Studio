# TRELLIS Studio 3.9.0

## Texture Projection

- **Use generation views** reprojects two to four prepared images on
  compatible Pixal3D models with verified saved cameras. Pixel Match blends
  contributions using visibility, viewing angle and local color matching.
- **Saved generation image** uses Auto Align to estimate the projection
  camera and placement from the saved TRELLIS.2 cutout and the model.
  Inspect the fit around silhouettes, repeated features and thin details.
- The manual projection editor lets you move the overlay and scale its
  width and height together or independently. Use these controls to refine
  Auto Align or fit a custom image.
  Projection creates a linked texture copy with the original mesh and other
  material maps.

## HD Master Finishing

- Open **Prepare → HD Master Finishing** on a model with a compatible cached
  1024 or 1536 source. Choose **Studio Reconstruction (768)** or **WTiVo
  Reconstruction (1024)** and create a linked PBR master without rerunning image-to-3D
  inference. The finishing recipe uses a ceiling of three million triangles
  and defaults to 4K textures on hosts that allow them.
- The optional WTiVo integration is available in **Remesh** and **Finishing
  Board** too. Compare fine edges, openings and seams before choosing the
  master for your game copy. [WTiVo configuration guide](WTIVO.md)
- Game-copy baking replaces invalid and inverted tangent-space normal texels
  with the target shading normal. This improves shading where a bake ray hits
  the opposite wall of a thin shell.

## Version and Windows Setup

- The Studio header displays the installed version and offers a dismissible
  link to the release notes when a newer stable version is available.
- Windows x64 Setup offers Desktop and Server with
  Workshop only or Full Studio components. Verify the unsigned installer
  download against `SHA256SUMS.txt`. [Windows setup guide](WINDOWS_SETUP.md)

Finishing and texture projection are also available through the developer
tools. [REST API](API.md) · [MCP](MCP.md)
