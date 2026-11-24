# TRELLIS Studio 3.15.1 · Windows Preview qualification

English · [Français](README.fr.md)

The Preview built from `da4d367` passed 22 regression suites. It includes seven batches of changes since `f45fe3a`. The tests ran on Windows with a GeForce RTX 5070 Ti (16 GB), Ubuntu 22.04 under WSL2, Docker Linux and Unity 6000.6.6f1. The findings below distinguish what was measured locally from what still needs a different machine, asset or reviewer.

## Character results

**Aélis** was generated in Create from a T-pose with High Detail GGUF, native PBR and seed 42. The run took 5 min 40 s and produced 2,007,941 triangles and two 4096 × 4096 textures. The FBX kept its 1.72 m height, 52 bones and idle, walk and run clips. The video shows three repeats of the walk cycle in Unity Play Mode. The armour patterns are clearer, while the fingers look thick and the palms turn upward during the walk. The Dense Master comparison also uses TOPOS, so the images compare two complete workflows. [Face, hands and armour](aelis-detail.png) · [Unity walk video](aelis-unity.mp4?raw=true) · [Hair before and after URP reimport](aelis-urp.jpg)

**Elias** was generated at 1024 with the same seed and a 2K atlas, once with the full-body reference and once with an additional portrait. The portrait brought out stubble and eyebrows. The eyes still look wide, the hair has holes, and the mouth and face outline moved farther from their reference landmarks. This test supports keeping the portrait optional. [Portrait comparison](elias-portrait.jpg)

## Audit findings

Six baseline fixes were retested. The other 27 findings span Desktop dependencies (1), character quality (2), exports (3), storage and performance (4), interface and translation (5), Server (6) and distribution (7).

| ID | Batch | Finding | Result and remaining scope |
|---|---|---|---|
| D1 | Baseline | Queued jobs could disappear | Passed. Pending jobs survived queue compaction and restart. |
| D2 | Baseline | Archive and restore limits | Passed. A test collection was exported and restored into an empty library. |
| D3 | Baseline | Interrupted jobs | Passed. Recovery preserved the previous result and allowed work to resume. |
| D4 | 4 | Leftover export copies | Verified on disposable copies. Cleanup checks the preserved file or ZIP before removal. |
| D5 | 4 | HD finishing after restore | Passed with and without cache. Restoring a verified cache produced a new 26,014-triangle finish. |
| S1 | 1 | Dependency advisories | Partial. Isolated CPU rembg 2.0.88 reproduced the original alpha mask. PyTorch and Transformers still have open advisories. |
| S2 | Baseline | Two-factor authentication secrets | Passed. Enrolment, migration and sign-in after restore were tested using a separately backed up key. |
| S3 | 6 | Resource use by converters | Verified locally. Cancelling a conversion released its quota and the next GLB completed. Two accounts remained isolated through REST and MCP. |
| S4 | 6 | API key permissions and expiry | Passed locally. Read-only access, expiry, revocation and the migration window for existing keys were exercised. |
| S5 | 7 | Offline install and package integrity | Partial. Modified media were rejected. Workshop, MCP and the standard animations installed offline on the existing Windows host. Fresh Windows and signing remain open. |
| S6 | 3 | Materials and engine provenance | Verified on native PBR, six-view UltraTex 2K and multiview fallback. The export records an unknown engine when an old asset only records the requested option. |
| G1 | 2 | Cropped fingers or limbs | Passed locally. Warnings use the original mask before reframing. |
| G2 | 2 | Face likeness | Partial. Three faces occupied about 39 × 52–53 px at the first native pass. See the Elias comparison above. Stylised faces still need review. |
| G3 | 2 | Clothing intersections | Verified on eight fixtures. Four intersecting and four separated pairs were identified. Intentional eye contacts and layered clothing require visual judgement. |
| G4 | 2 | Knee and ankle depth | Verified at rest on Aélis and RIFT. Simple and Expressive with rigid hands retained all four joint centres within the mesh on reimport. |
| G5 | Baseline | Palm contact after editing a vault | Passed the timing and trimming regression. Maximum palm error on the Unity fixture was 14.85 mm. |
| G6 | 2 | Motion diagnostics across clip types | Partial. Four characters were sampled at 240 Hz. The worst sampled palm-surface contact error on Aélis was 17.31 mm at 1.604 s. |
| U1 | Baseline | Unity terrain reimport | Passed. Importing another terrain preserved local sculpting and painting. |
| U2 | 3 | URP materials and hair | Partial. Matte crown silhouettes overlapped by 99.60% head-on and 99.74% at three quarters. The opaque hair rendered darker in URP. Transparent hair needs a separate asset. |
| U3 | 3 | Bones on lower LODs | Passed on fixtures. Matching uses hierarchy and bind pose. Ambiguous or missing bones were rejected. Two LODs were rendered in URP. |
| U4 | 3 | Delivered FBX in a game engine | Partial. Seven joints on three reimported Unity poses differed by at most 0.38 mm from the GLB. Unreal and additional Unity versions remain open. |
| U5 | 3 | Terrain paint and printable wall precision | Verified on calibration pieces. Measured walls were 2.000 and 4.000 mm. Studio displays the terrain paint resolution. |
| E1 | 4 | Large collection startup | Partial. At 5,000 synthetic records, two Edge tabs took 24.0 and 26.7 s to show their first cards. Cold startup remains slow. |
| E2 | 4 | Dense mesh memory use | Passed on Aélis. Peak process memory for bounds fell from 879.1 to 261.6 MiB with identical bounds. |
| E3 | 4 | Orphaned preview browsers | Passed locally. Tests covered 20 Edge renders, cancellation, timeout, shutdown and cleanup of orphaned profiles. |
| E4 | 4 | Partial downloads and WSL timeouts | Verified on partial files, bad checksums, HTTP 416 and a simulated unresponsive WSL client. |
| E5 | 6 | Scaling across workspaces | Partial. At 50 empty Windows workspaces the 95th percentile model-list latency was 3.97 ms. Populated, active libraries still need load testing. |
| E6 | 7 | Identifying an installed build | Partial. The upstream version and fork commit are recorded separately. A fresh Windows installation still needs verification. |
| E7 | 7 | Release checks | Partial. Quick checks and tagged hardware workflows are configured. Remote CI execution and the complete engine matrix remain open. |
| I1 | 5 | Untranslated UI text | Passed on the tested French and English paths and dynamic messages at 200% zoom. |
| I2 | 5 | Keyboard and screen reader access | Partial. Dialog names, 3D keyboard controls and focus return passed in Edge. NVDA speech still needs a listening test. |
| I3 | 5 | Generation settings across entry points | Passed. The same image, seed 84 and Pixal3D face settings produced identical stored recipes from Create, Queue and REST. |
| I4 | 3 | STL verdicts in batch exports | Passed on a mixed ZIP. Both the printable STL and the STL needing repair retained their own verdict and hash. |

## Delivery and rollback

The qualified unsigned Windows Preview is 19,569,805 bytes with SHA-256 `b3bbdedb58be8ac8481d1a97409404eb64dee471d7747bd7a8dadd3d08979e2f`. All 1,518 extracted payload files matched the package manifest. Offline testing covered the Workshop, MCP and standard animation libraries on an existing Windows installation. GPU engines and WSL require separate provisioning. [Windows Setup](../WINDOWS_SETUP.md) · [Native High Detail](../NATIVE_PROFILES.md#windows-setup) · [Dependency advisories and controls](../../SECURITY.md)

In a disposable checkout, reversing each batch reproduced the preceding Git tree exactly through `f45fe3a`. Both versions read collection archives created by the other. Two independent Server restores on the same Windows host preserved account isolation, model hashes, TOTP and quotas. Restoring Server on another host and signing a release with the maintainer’s identity remain outstanding. [Server backup and recovery](../SERVER.md)
