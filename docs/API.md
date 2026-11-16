# TRELLIS Studio REST API v1

| Edition | Base URL |
| --- | --- |
| Desktop from source | `http://127.0.0.1:7860/api/v1` |
| Desktop from Windows Setup | `http://127.0.0.1:7870/api/v1` |
| Server | Your configured HTTPS origin followed by `/api/v1`. On the server PC with the default loopback configuration, use `http://127.0.0.1:7862/api/v1`. |

Start **Open TRELLIS.cmd** for Desktop or **Open TRELLIS Server.cmd** for Server.
Open `/developers` in the browser for the developer workspace, `/api/docs` for the
reference and `/api/openapi.json` for the OpenAPI contract. On Server, sign in to
view these pages. The reference lists the v1 routes for the running edition.

For Server scripts, create a personal key in **Security → API keys**, then send
`Authorization: Bearer <key>` to `/api/v1`. Every operation uses the key owner's
library, disk quota and generation credits. One credit is reserved per new
generation or generation retry and spent on success. Failed and cancelled jobs
release their reservations. Finishing a saved model uses disk quota and costs zero
generation credits. Administrator accounts have unlimited disk quota and credits.
Account management, activation, quotas and key creation are managed through the
browser session and require the appropriate role. [Server setup](SERVER.md)

## Request lifecycle

1. Upload a source with multipart `POST /uploads`, field `file`.
2. Optionally call `/references/preview`. Submit JSON to `/generations` or
   `/imports`, using the returned `id` as `upload_id`.
3. Read `/jobs/{id}` until `state` is `done`, `error` or `cancelled`.
4. Inspect diagnostics, refinish a saved master, or prepare a linked game, print,
   LOD or rig copy.
5. `POST /exports`, poll `/exports/{id}`, then download `/exports/{id}/download`.

Operations returning HTTP 202 are asynchronous. Generation and finishing variants
are queued. On Desktop, rigging and other preparation require an idle compute slot
and can return 409. On Server, compute jobs go through the scheduler. Export has a
separate task lock. Use the retry route to start a fresh attempt from the saved
recipe. After a timed-out POST, inspect the queue or library before retrying to
avoid duplicate requests.

## Python example

```python
import os
import requests

base = "http://127.0.0.1:7862/api/v1"
session = requests.Session()
session.headers["Authorization"] = f"Bearer {os.environ['TRELLIS_API_TOKEN']}"
with open("reference.png", "rb") as image:
    response = session.post(base + "/uploads", files={"file": image})
response.raise_for_status()
source = response.json()["id"]

response = session.post(base + "/generations", json={
    "upload_id": source, "name": "Harbour prop", "profile_id": "game_d",
    "height_m": 1.2, "seed": 42, "priority": 1
})
response.raise_for_status()
job = response.json()["id"]
print(session.get(base + "/jobs/" + job).json())
```

`game_d` is **Game - Default**, the protected D recipe. `high_detail` is the
high-poly alternative. Read `/profiles` for the exact recipes and custom IDs.
Object height and seed belong to the job, not the saved profile. Supported JSON
overrides are documented in the `Generation` schema; unknown fields are rejected.

## Routes

| Group | Operations |
| --- | --- |
| Studio | `GET /status`, `/profiles`, `/taxonomy`, `/animations`. Desktop also provides `/client-config`. |
| Sources | `POST /uploads`, `/imports`, `/references/preview`, `/generations` |
| Pixal3D multi-view | `POST /generations/multiview` with uploaded front and supplemental image IDs |
| Library | `GET /models`, `GET /jobs/{id}`, `PATCH /models/{id}/metadata`, `GET /models/{id}/files/{filename}`, `/models/{id}/presentation/{filename}` |
| Queue | `GET/PATCH /queue`, `PATCH /queue/{id}`, `POST /queue/{id}/retry`, `POST /jobs/{id}/cancel` |
| Preparation | `GET /models/{id}/diagnostics`, `/models/{id}/diagnostics/report`. `POST /models/{id}/lods`, `/game-copy`, `/print-copy`, `/refinish`. `GET/POST/PATCH /models/{id}/finishing-board`. |
| Animation | `POST /models/{id}/rig`. `GET`, `POST` and `DELETE /models/{id}/animations` list, add or remove clips on the selected model. Desktop provides `/motion-edits`. |
| My animations | `GET/POST /my-animations`, `GET /my-animations/{id}`, `POST /my-animations/{id}/cancel`, `GET /my-animations/{id}/files/{filename}`. `POST /models/{id}/my-animations` appends a saved motion to the selected rigged model, keeping its ID. |
| History | `GET /models/{id}/history`, `POST /models/{id}/versions`, `/checkpoints`, `/restore-version` |
| Collections | `GET /workspace`, `POST /folders`, `/folders/assign`, `/views` |
| Export | `POST /exports`, `GET /exports/{id}`, `GET /exports/{id}/download`, `POST /exports/{id}/cancel` |
| Transfer | On Desktop, upload a collection ZIP, then `POST /transfers/{id}/restore`. |
| Trash | `GET /trash`, `DELETE /models/{id}`, `POST /trash/{id}/restore` |

`GET /models` supports `query`, `state`, `folder_id`, `animated`, `offset` and
`limit` (1–100). Folder filtering includes descendants. Identifiers are 32-character
lowercase hexadecimal strings. Timestamps are Unix seconds; dimensions and offsets
are metres unless a field explicitly says millimetres. Rotation is degrees, Y up.
LOD ratios are distinct decreasing fractions between .02 and .99.

To add multiple authored motions, send library IDs from `/animations` in a single request,
for example `{"clips":[{"clip":"idle","duration":3},{"clip":"walk","duration":2.5}]}`.
The single-clip form is `{"clip":"walk","duration":2.5}`. Both editions update the
selected model ID and keep the other clips. In Server, animation work uses the account's
disk quota and requires zero generation credits.

List the clips with `GET /models/{id}/animations`. To remove one, send its exact
embedded name to `DELETE /models/{id}/animations` with `{"clip":"TS_walk_2.5s"}`.
For duplicate or unnamed clips, send the returned `index` with the expected `clip`
name or `null`. Pass the list's `revision` to reject a selection from an earlier
version of the GLB. Poll `status_url` from either write response until the update finishes.
On Desktop, a failed or cancelled animation update can return `state: "done"`
with `operation_error`: the model remains usable, but the requested update did
not succeed. Check this field as well as `state`.

To edit an embedded motion on Desktop, pass its actual stored clip name from the
model record. Motion edits create a checkpoint and update the prepared LODs.
`distance` adds forward travel to the source motion. Use zero to keep authored travel.

`POST /models/{id}/rig` accepts `rotation`, `height_m`, `offset_m` and an optional
`landmarks` object for an unrigged humanoid in an A-pose or T-pose. The complete
set is required: `chin`, `groin`, `left_shoulder`, `right_shoulder`, `left_elbow`,
`right_elbow`, `left_wrist`, `right_wrist`, `left_knee`, `right_knee`, `left_ankle`
and `right_ankle`. Each value is `[x, y]` normalized by `height_m`, with origin at
the horizontal centre and ground **before** `offset_m`; +X is anatomical left
(right on a front-facing screen). UniRig predicts joint depth. The supplied
frontal positions adjust the skeleton before skin weights are calculated, and
the final rig is checked against them. These are joint placement hints, not mesh
deformations. Existing skinned models reject manual landmarks with HTTP 409;
omitting `landmarks` preserves the previous rig workflow. Check the
`rig_landmarks` feature in `/status` before submitting points to a running server.

Generation, LOD, game preparation, print preparation and rigging create linked
versions as described in the reference. Metadata, standard animation updates and
generated-motion application operate on the selected record. Model deletion moves
the record to restorable trash. The explicitly named `/animation-copy` endpoint
remains available for clients that deliberately request a separate version.

`POST /models/{id}/versions` duplicates imported, rigged and printing models.
For a generated variant, reuse its source image and stored recipe in `/generations`,
with `overrides.parent_id` set to the original ID. This schedules a new computation.

## Reusable generated animations

**My animations** stores generated humanoid body motions independently of any
character. It is separate from the standard catalogue returned by `/animations`.
Saved motions persist across restarts and remain available when another model is
selected. On Server, the library, its status and downloadable files belong to the
authenticated account's private workspace; another account cannot access them by
knowing an animation ID. These files count toward the owner's disk quota.

Read `GET /my-animations` first. Its `GeneratedAnimationLibrary` response contains
`animations`, `engine` and the duration limits `min_duration`, `max_duration`,
`step`. The engine fields are `ready`, `label`, `backend`, `experimental` and
`message`. Generation requires an administrator-configured optional local CPU
runtime. An unconfigured installation returns HTTP 503 for a generation request;
listing and applying already completed motions remain available. Readiness reports
the configuration, not a guarantee that a subsequent calculation will succeed.

Send `POST /my-animations` with a `GeneratedAnimationCreate` object:

| Field | Meaning |
| --- | --- |
| `prompt` | Required movement description, 3–1000 characters. Use English for the current engine. Whitespace is normalized. |
| `name` | Optional display name, 1–80 characters. If omitted, a name is derived from the prompt. |
| `duration` | Requested seconds, 2–10 in 0.5-second steps; default `5`. |
| `seed` | Integer from `0` to `2147483647`; default `42`. |

Unknown fields are rejected. HTTP 202 returns `GeneratedAnimationAccepted` with
`id`, `state` and `status_url`. Poll that URL, or `GET /my-animations/{id}`, until
`state` is `done`, `error` or `cancelled`; intermediate states are `queued` and
`running`. Use `stage` for the current operation and `progress` for reported
progress, without extrapolating an estimated completion percentage. The library
currently permits up to 500 entries and eight queued/running generations.

A `GeneratedAnimationItem` includes `id`, `name`, `prompt`, `duration`, `seed`,
`fps`, `frames`, `created`, `clip_name`, `provenance`, `state`, `stage`, `progress`,
optional `error`, `preview_root`, `preview_url` and `files`. Motions use 30 fps.
Completed entries expose a real animated `preview.glb`, canonical `motion.npz`
and `skeleton.json` through the `files` URLs. The preview clip name is
`clip_name`. Downloads require the same authentication as the library and are
available only after completion. Filesystem paths and runtime configuration are
not exposed by these routes.

Cancel only the requested generation with `POST /my-animations/{id}/cancel`.
The response is `{"ok":true}`; poll the item again to confirm its state. Cancelling
an already terminal item leaves it unchanged, including completed saved motions.
To generate a different attempt, submit a new creation request and retain its new
ID. Do not blindly repeat a timed-out POST: inspect the personal library first.

On **Server**, a new motion generation reserves **one generation credit** for a
non-administrator account. It is spent once on successful completion; failure or
cancellation releases the reservation. Applying a saved motion costs **zero
generation credits** and uses disk quota for the updated model and temporary
transfer files. Generation and application run through the workspace compute queue. Administrators have the
same unlimited-credit policy as other generation operations; Desktop has no
account credit accounting.

To reuse a completed motion, send `POST /models/{model_id}/my-animations` with a
`GeneratedAnimationApply` object:

```json
{
  "animation_id": "0123456789abcdef0123456789abcdef",
  "in_place": false
}
```

`in_place` defaults to `false`. Setting it to `true` suppresses horizontal root
travel. It is **not a copy-versus-update option**: both values append to the
selected model and keep its ID and collection card. Geometry, materials, skinning
and existing clips are retained, and the saved motion is reused without new
inference. The target must have a compatible humanoid rig. An unfinished motion,
unrigged target or duplicate clip returns HTTP 409; incompatible rigs can also
fail during the queued transfer. Failed or cancelled transfers preserve the
previous model. Temporary transaction backups are removed after a successful
commit; this does not automatically create a persistent history checkpoint.

Application returns HTTP 202 with an `AnimationAccepted` object. Its `id` is the
selected model ID. On Server it also includes `operation_id`, and `status_url`
points to `/api/v1/animation-operations/{operation_id}`. On Desktop, `status_url`
points to `/api/v1/jobs/{model_id}`. Poll the **returned status URL**, not the
saved motion or the Server model's existing `done` state. After completion,
refresh the same model to read its new revision and animation list. The model
retains the motion ID, readable name and embedded clip name under
`settings.generated_animation_clips`. Its display name, favourite state and
folder membership remain unchanged.

Treat `error`, `cancelled`, or a nonempty `operation_error` as an unsuccessful
update. In particular, Desktop preserves model availability by reporting a failed
or cancelled animation edit as `state: "done"` plus `operation_error`.

This example reuses the authenticated `session` from above:

```python
import time
from urllib.parse import urljoin

origin = base.removesuffix("/api/v1")
response = session.post(base + "/my-animations", json={
    "name": "Walk and stop",
    "prompt": "A person walks forward, slows down and stops.",
    "duration": 5,
    "seed": 42
})
response.raise_for_status()
accepted = response.json()

while True:
    response = session.get(urljoin(origin, accepted["status_url"]))
    response.raise_for_status()
    motion = response.json()
    if motion["state"] in {"done", "error", "cancelled"}:
        break
    time.sleep(2)
if motion["state"] != "done":
    raise RuntimeError(motion.get("error") or motion["stage"])

# rigged_model_id is an existing compatible model in this same workspace.
response = session.post(base + f"/models/{rigged_model_id}/my-animations", json={
    "animation_id": motion["id"], "in_place": False
})
response.raise_for_status()
update = response.json()
assert update["id"] == rigged_model_id
while True:
    response = session.get(urljoin(origin, update["status_url"]))
    response.raise_for_status()
    status = response.json()
    if status["state"] in {"done", "error", "cancelled"}:
        break
    time.sleep(2)
if status["state"] != "done" or status.get("operation_error"):
    raise RuntimeError(status.get("operation_error") or status.get("error") or status["stage"])
# Refresh rigged_model_id after success; there is no additional collection card.
```

Generated body motion does not rig an unrigged mesh or provide character-specific
foot locking, finger animation or non-humanoid motion. Review contacts, root
travel and skin deformation on each target character before using the result.

## Reference preview and corrections

`POST /references/preview` accepts `upload_id`, `engine` (`trellis2` or
`pixal3d`), `remove_bg` and optional `reference_edits`. For Pixal3D, include
any supplemental views as `left_upload_id`, `back_upload_id` and `right_upload_id`.
Each entry in `views` contains the role, source dimensions and three PNG data
URLs, `original`, `cutout` and `framed`, at up to 240 × 240 pixels each.

Pass the same `reference_edits` to `/generations` or
`/generations/multiview` to apply the corrections to the job. Edits are keyed
by view role, for example `{"front":{"crop":[0.05,0.05,0.95,0.95]}}`. A
crop is `[left, top, right, bottom]`. Optional `strokes` have a `mode`
(`keep` or `erase`), a normalized `radius` and a list of normalized `[x, y]`
points. For single-image generation, use `overrides.remove_bg` to match the
preview setting. Previewing uses zero generation credits.

## Cached finishing and retry

- Read `GET /models/{id}/finishing-board` to find the retained master, raw
  triangle count when available, valid texture sizes, budget presets and Blender
  availability for normal maps. A missing reusable cache returns 409.
- `POST /models/{id}/refinish` accepts one finishing recipe. Use
  `{"triangles":28000,"repair_surface":true}` for a linked hole-repair variant
  with a manual budget, or `{"budget_preset":"medium","adaptive_finishing":true}`
  for an adaptive budget. Add `"bake_normals":true` to bake a normal map with
  Blender. The master remains available and the new job has its own status URL.
- `{"hd_reconstruction":true}` creates a linked HD master from a compatible
  retained cache. It uses a 768 reconstruction grid, band 1, surface projection
  0, small-hole filling and no pre-decimation. The default triangle ceiling is
  1,200,000. A decoded resolution of at least 768 is required. For a new Dense
  Master generation, set `overrides.hd_reconstruction` in `/generations`, or
  `hd_reconstruction` on the top-level `/generations/multiview` recipe. This
  option and `repair_surface` are mutually exclusive. Reconstruction improves
  surface continuity on cracked meshes and can soften fine geometry.
- `{"wtivo_reconstruction":true}` uses the optional [external WTiVo runtime](WTIVO.md)
  to reconstruct a cached 1024-or-higher source. Availability and the reason for
  an unavailable option are in `wtivo_reconstruction` and `wtivo_reason` from
  the board. WTiVo uses grid 1024 and a fixed triangle ceiling (default 1.2M).
  It can be compared with Studio 768 in the same board batch. Each recipe
  chooses one method and WTiVo supports manual triangle budgets and normal baking.
- `POST /models/{id}/finishing-board` accepts `{"variants":[...]}` with one
  to three distinct recipes. Poll `GET /jobs/{id}` for each returned ID. Save a
  completed variant as the board's choice with
  `PATCH /models/{id}/finishing-board` and `{"selected_id":"<variant id>"}`.
  Use `{"selected_id":null}` to clear the choice.
- `POST /queue/{id}/retry` creates a new attempt for a failed or cancelled
  queued generation or finishing job. Pass `{}` to reuse the recipe or override
  allowed settings such as `triangles`, `texture_size`, `resolution` or
  `priority`. The response includes both the new ID and `retry_of`. Corrections
  depend on the job's engine, recipe and retained source. On Desktop,
  `PATCH /queue/{id}` also supports in-place retry.

## Pixal3D multi-view generation

Use `GET /status` to inspect `pixal3d.ready` and the optional character recipe. Upload the front and complementary images individually with `POST /uploads`, then submit their returned IDs with `POST /generations/multiview`.

- `upload_id` is the front image. Supply at least one of `left_upload_id`, `back_upload_id` and `right_upload_id`.
- `side_angle` is 40 for three-quarter views or 90 for profiles. Left is positive azimuth, right is negative azimuth and back is 180°. Use the same full-body pose and framing.
- Optional fields include `name`, `height_m`, `seed`, `triangles`, `texture_size` (1024 or 2048), `parent_id`, `keep_finishing_source` and queue `priority`. Defaults come from **Character · Pixal3D**.
- Set `reproject_face` to `true` to transfer the visible face from the original front photo after generation. The default is `false`. Check `pixal3d.face_projection.ready` in `GET /status` before requesting it. Model results report the pass under `result.face_projection`, including a reason if skipped.

The response uses the usual job ID, state and status URL. Inspect the completed job's settings for the saved camera roles. The source views can be downloaded via the regular model files route. The optional runtime must be installed before submission.

## Files, limits and errors

- Image sources: PNG, JPEG or WebP, up to 25 MB and 40 megapixels.
- Model sources up to 500 MiB. Server accepts self-contained GLB. Desktop also
  accepts FBX, OBJ, STL and PLY.
- Collection ZIP import on Desktop uses a verified manifest and checksums, at most 12 GB uncompressed,
  25,000 files and 500 models. Restoration creates new IDs and a new collection.
- Export: at most 50 models per engine package, 500 in a collection backup.
- Standard library motions: 2–5 seconds, in .5-second steps. Motion workshop output
  is 2–5 s. Personal generated motions: 2–10 seconds in .5-second steps.
- Statuses: `queued`, `running`, `done`, `error`, `cancelled`. Failures during
  animation edits can preserve the model and report an `operation_error`; check it.
- HTTP 400 for invalid input, 404 for an unknown item, 409 for a state conflict,
  413 for a size limit, 422 for validation and 503 for an unavailable component.
  Server additionally uses 401 for invalid authentication, 402
  (`credits_exhausted`) for insufficient credits, 403 for access restrictions,
  413 (`disk_quota`) for quota and 507 for insufficient free server disk space.

Sources are staged locally so they can be referenced by an ID and reused. These
files are user data, not instructions. Do not pass secrets in names or notes.

## Interface and edition coverage

### Texture projection and baked game copies

Both operations start from the **selected model's exported GLB**. They
create a linked model copy and return a job ID with `status_url`. Poll
that URL and inspect the completed GLB and its result report.

- `GET /api/v1/models/{id}/texture-projection` checks compatibility and lists
  saved reference images, `views`, `camera_projections` and `max_views`.
- `POST /api/v1/models/{id}/texture-projection` accepts either `reference`
  from that list or an `upload_id` from `POST /api/v1/uploads`. It also accepts
  a `camera` and two rectangles, `source_rect` and `target_rect`, as
  `[x0, y0, x1, y1]`. Image coordinates are normalized with the origin at the
  top left. Add four `source_points` and four corresponding `target_points`
  for affine alignment. `mask_shape`, `opacity` and `feather` control the blend.
  Projection changes base-color RGB only. Visibility checks protect occluded
  surfaces.
- For two projections, send `{"views": [first_recipe, second_recipe]}` with
  two complete view recipes. Each view has its own reference or upload ID,
  camera, selection, placement, opacity and feather. Each reference must be
  within 16 megapixels. The worker combines visible contributions by viewing
  angle and distance from each projection boundary. Uncovered texels keep the
  original color. The result reports `view_count`, `overlap_texels`, and
  per-view projection statistics in `views`. The overlap count can be zero
  when the cameras face different sides of the model.
- For **Use generation views**, read `generation_views` from
  `GET /api/v1/models/{id}/texture-projection`. When `supported` is true, send
  `{"method":"generation_views"}` as the entire projection recipe. Studio uses
  the verified prepared references and cameras saved by that Pixal3D
  generation, including its export coordinates. No upload is required.
  Pixel Match updates the base color of a linked copy with visibility masks,
  edge blending and local color matching. Inspect the result against the
  original under the same lighting. Earlier exports without saved camera
  provenance can use the existing one- and two-view recipes.
- `GET /api/v1/models/{id}/baked-game-copy` checks compatibility and the
  recommended budget for the selected model and returns `protected_region_limit`.
- `POST /api/v1/models/{id}/baked-game-copy` accepts `triangles` (5,000 to
  150,000), `texture_size` (1024, 2048 or 4096), `profile` (`object` or
  `humanoid`), `bake_normals`, and optionally `protected_regions`. The humanoid
  profile gives extra priority to the face and hands of an upright, frontal
  T-pose. Use Object and pick zones for other poses or shapes. Each region
  contains a `center` of three coordinates in the source GLB's Y-up coordinate
  system, a positive `radius` in the same units, and `strength` from 0 to 1.
  An example is `{"center":[0,1.55,0.09],"radius":0.12,"strength":0.8}`.
  Regions give the enclosed geometry soft priority within the requested budget.
  The CPU worker makes new UVs and bakes the selected donor's color, roughness,
  metallic and optional tangent normals. The result reports actual triangle
  counts and affected vertices. The worker requires Blender and PyMeshLab.

The Studio browser can estimate each camera with **Auto Align**, using a
transparent cutout and rendered model previews. Review each placement before
creating the texture copy. Slight differences between the source images can
soften fine features in overlapping areas.

A projection camera uses one of six preset views or `view: "custom"`. Front
looks along −Z with +X to the right and +Y up. A custom view supplies `basis`
as three right-handed orthonormal vectors in world coordinates, ordered right,
up, then toward the camera. In both modes `frame` is
`[left, bottom, right, top]`.

- **Orthographic** is the default. Frame coordinates are world positions
  projected onto the right and up vectors. Existing recipes with only
  `view` and `frame` still work.
- **Perspective** uses `projection: "perspective"` and `origin: [x, y, z]`
  in world coordinates. Compute camera coordinates by subtracting the origin
  and projecting onto each basis vector. A model point at camera coordinates
  `(x, y, z)` maps to `(x / -z, y / -z)` in the frame at one unit of forward
  distance. Keep the model in front of the camera.

Set `linked_selection: true` to keep the selected reference region attached to
its placement. The same target-to-source affine transform determines both the
sampled color and the source-domain mask. A rectangle or ellipse uses
`source_rect`; a polygon uses `mask_shape: "polygon"` and `source_polygon`, a
list of 3 to 128 normalized `[x, y]` vertices. Polygon masks are always linked,
even when `linked_selection` is omitted. Clockwise, counterclockwise and concave
simple polygons are accepted. A final repeated first vertex is removed;
zero-area, crossing or self-touching outlines are rejected. This field supports
both a freehand lasso and a click-to-close outline.

With linked selection, alignment landmarks can lie outside the selected region,
but every landmark must remain within its image's normalized 0-to-1 coordinates.
The fit is conditioned using the landmark spans, so selecting a smaller region
does not invalidate surrounding guides. The worker derives a conservative
processing rectangle by inverse-transforming the source mask's bounding box;
`target_rect` does not add a second clipping mask. That processing rectangle is
reported as `effective_target_rect` and is limited to the visible camera frame.
Changing a source selection must not change the supplied alignment guides.
When no landmarks are supplied, the existing `source_rect` to `target_rect`
scale-and-translation mapping is used. Supply four corresponding points for
rotation or general affine placement; do not clamp displaced guides to an image
edge, because that changes the fit.

Linked feathering extends inward only. Its width is `feather` times the shorter
side of the source selection's bounding box, measured in source-image pixels.
Polygon edges use Euclidean distance; an ellipse uses its normalized radial
distance scaled by the shorter side. `opacity` and reference alpha multiply
that mask. No pixel outside the polygon is selected; texture-island padding can
still copy painted boundary colors into unused UV gutter pixels. Overlapping
UV samples that address distinct surfaces are excluded. Requests for rectangle
or ellipse masks without `linked_selection` retain the original source-rectangle
and target-mask behavior.

The initial scope is a static, single-primitive GLB with an embedded material
and readable UV0. Check each operation's support response before submitting.
Review the projected color from several angles. Review small features, bake
coverage and deformation separately before using a game copy in production.

Desktop binds to loopback. Server supports authenticated LAN access and HTTPS.
Use the Server deployment instructions for the configured address and certificate.
[Server setup](SERVER.md)

The browser handles the 3D viewer, comparison, camera capture and recording,
library turntable editing, interactive rig markers and account administration.
Saved presentation files can be downloaded through v1. The current public API
also leaves terrain creation, profile editing, collection folder and saved-view
management beyond creation and assignment, batch library edits and interactive
export preflight to Studio. Server offers library export, while collection ZIP
restore and in-place motion editing are Desktop operations. See the running
edition's OpenAPI contract for the full list of exposed v1 operations.

Review printability, deformation and game readiness in the target tools.
