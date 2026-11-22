# TRELLIS Studio 3.14.0

## Rigging

- **Advanced humanoid** adds forearm twist bones and a choice of rigid hands or articulated fingers. It produces 24 or 54 joints, depending on the hand option. The **Auto** rig remains available.
- **Creature** predicts a skeleton from the mesh. Add or reposition joints and review the branches before calculating skin weights. **Predict skeleton** uses a branching skeleton icon in Creature mode.
- Improved humanoid handling includes narrow A-pose landmarks, scale rounding and clip names. Thanks to [Loomaknox](https://github.com/Loomaknox) for the rigging contributions that informed this release.

## Procedural creature animation

- Open **Animation → Creature** on a compatible rigged model, including imported GLBs. Create a deformation, quadruped stride, serpentine wave, wing flap or swim according to the chains Studio recognizes.
- **Creature swim** contracts and reopens the bell with a delayed wave along the trailing chains. Adjust the intensity, duration, cycles, wave delay and vertical travel.
- A new clip is added to **Added** on the same model. The existing clips, skin weights and mesh are retained. Generate a new clip to use the revised swim on a model with an older swim clip.
- Procedural animation runs locally on the CPU and uses the existing joints. Results depend on the rig and skin weights. The stride preview does not lock foot contacts. Blender is required to save the updated companion file.

## Reliability and Windows Setup

- Progress writes retry temporary Windows file locks so that a rejected status update does not immediately fail a generation.
- The Windows x64 installer keeps the GPU detection and optional component setup for Desktop and Server. UniRig skeleton and skin prediction require the installed UniRig component. See the [Windows Setup guide](WINDOWS_SETUP.md).
- Verify the unsigned Setup with `SHA256SUMS.txt`. Stop Studio or Server before installing into an existing folder.
