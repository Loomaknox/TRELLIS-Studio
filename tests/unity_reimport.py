r"""Run the Unity reimport regression in a disposable project.

.venv\Scripts\python.exe tests\unity_reimport.py "C:\path\to\Unity.exe"
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image
import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glb_data import node_transforms, read
from target_export import conversion_glb, export_asset


def terrain_fixture(folder):
    folder.mkdir(parents=True)
    (folder / "terrain-manifest.json").write_text(json.dumps(dict(
        name=folder.name, raw="heightmap.raw", resolution=33, size_m=10, height_m=5
    )), encoding="utf-8")
    (folder / "heightmap.raw").write_bytes(bytes(33*33*2))
    for name in ("Soil", "Rock", "Grass", "SoilNormal", "RockNormal", "GrassNormal", "Splatmap"):
        Image.new("RGB", (4, 4), (255, 0, 0)).save(folder / (name + ".png"))


def make_package(work, name, identifier, parent, *, width, colour, node_name):
    source = work / "sources" / name / identifier
    source.mkdir(parents=True)
    mesh = trimesh.creation.box(extents=(width, 1, 1))
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)),
        material=trimesh.visual.material.PBRMaterial(
            name="Paint", baseColorTexture=Image.new("RGBA", (4, 4), colour),
            alphaMode="MASK", alphaCutoff=.2, occlusionTexture=Image.new("RGB", (4, 4), (39, 211, 87)),
        ),
    )
    scene = trimesh.Scene()
    scene.add_geometry(mesh, node_name=node_name, geom_name=node_name + "Mesh")
    (source / "model.glb").write_bytes(scene.export(file_type="glb"))
    (source / "LODs").mkdir()
    document, binary = read(source / "model.glb")
    document["materials"][0]["occlusionTexture"]["strength"] = .34
    conversion_glb(document, binary, source / "model.glb")
    document["materials"][0]["alphaCutoff"] = .8
    conversion_glb(document, binary, source / "LODs/LOD1.glb")
    (source / "lod-manifest.json").write_text(
        json.dumps(dict(levels=[dict(level=0), dict(level=1, file="LOD1.glb")],
                        screen_heights=[0.6, 0.2])), encoding="utf-8"
    )
    (source / "settings.json").write_text(
        json.dumps(dict(name=name, height_m=1, parent_id=parent)), encoding="utf-8"
    )
    (source / "metadata.json").write_text("{}", encoding="utf-8")
    (source / "physics.json").write_text('{"kind":"box"}', encoding="utf-8")
    destination = work / "packages" / name
    manifest = export_asset(source, destination, "unity")
    assert manifest["unity_asset_id"] == identifier
    assert manifest["unity_parent_id"] == parent
    return destination


def run(editor, crouch_model=None, mapping_file=None, vault=False, vault_model=None):
    with tempfile.TemporaryDirectory(prefix="trellis-unity-reimport-") as temporary:
        work = Path(temporary)
        installed = make_package(work, "Initial", "a" * 32, "", width=1, colour="red", node_name="Body")
        make_package(work, "Updated", "b" * 32, "a" * 32, width=2, colour="blue", node_name="Body")
        make_package(work, "Incompatible", "c" * 32, "a" * 32, width=3, colour="green", node_name="Renamed")
        # A 3.1.0 package has the legacy id field and no Unity-specific identity.
        for package in installed.rglob("studio-export.json"):
            manifest = json.loads(package.read_text(encoding="utf-8"))
            for key in ("unity_asset_id", "unity_parent_id"):
                manifest.pop(key)
            package.write_text(json.dumps(manifest), encoding="utf-8")
        project = work / "project"
        editor_dir = project / "Assets" / "Editor"
        editor_dir.mkdir(parents=True)
        shutil.copy2(ROOT / "unity" / "TrellisPackageImporter.cs", editor_dir)
        shutil.copy2(ROOT / "unity" / "TrellisTerrainImporter.cs", editor_dir)
        for name in ("A", "B", "C"):
            terrain_fixture(project / "Assets" / "Terrains" / name)
        shutil.copy2(ROOT / "tests" / "unity_reimport_editor.cs", editor_dir)
        shutil.copytree(installed, project / "Assets" / "Installed")
        legacy = project / "Assets" / "LegacyFactors"
        shutil.copytree(work / "packages" / "Incompatible", legacy)
        for manifest_path in legacy.rglob("studio-export.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for surface in manifest["materials"]:
                for key in ("has_mask_occlusion_factors","occlusion_strength","alpha_cutoff"):
                    surface.pop(key)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        if vault:
            from motion_vault_edit import edit_vault
            source = work / "sources" / ("d" * 32)
            status, item = edit_vault(source, source=vault_model)
            assert status == 'verified'
            (source/"metadata.json").write_text("{}")
            exported = export_asset(source, work/"packages/Vault", "unity")
            shutil.copytree(work/"packages/Vault", project/"Assets/Vault")
            assert exported['motion_root'] and exported['unity_baked_contacts']
            from animation_diagnostics import read_tracks, world_positions
            document, binary = read(source / "model.glb")
            _, matrix = node_transforms(document)
            indices = {n.get("name"): i for i,n in enumerate(document["nodes"])}
            def xyz(value):
                return dict(zip(("x","y","z"),map(float,value)))
            mapping = json.loads((source/"result.json").read_text())["humanoid_mapping"]
            anchors = [dict(name=mapping[role], point=xyz(matrix(indices[mapping[role]])[:3,3]))
                       for role in ("right_hand","left_hand","head","right_toe")]
            contact = item["contact"]
            clip = next(clip for clip in document['animations'] if clip['name'] == item['clip'])
            tracks, partial, errors = read_tracks(document, binary, clip)
            assert not partial and not errors, (partial, errors)
            joints = {mapping[role]: indices[mapping[role]] for role in
                      ('head', 'left_hand', 'right_hand', 'left_shin', 'right_shin', 'left_foot', 'right_foot')}
            frames = [48, 192, 336]  # 0.25 s, 1 s, 1.75 s on the Unity evaluation clock.
            positions = world_positions(document['nodes'], tracks, joints, np.asarray(frames)/192)
            poses = [dict(frame=frame, joints=[dict(name=name, point=xyz(series[i]))
                                                for name, series in positions.items()]) for i, frame in enumerate(frames)]
            expected = dict(clip=item["clip"], bone=contact["bone"], anchors=anchors,
                            poses=poses, bind=xyz(contact["palm_bind"]), target=xyz(contact["palm_target"]),
                            interval=contact["interval_s"])
            (work/"vault.json").write_text(json.dumps(expected))
        if crouch_model:
            source = work / "sources" / ("f" * 32)
            source.mkdir()
            shutil.copyfile(crouch_model, source / "model.glb")
            (source / "settings.json").write_text('{"name":"Crouch QA"}')
            (source / "metadata.json").write_text("{}")
            package = project / "Assets/Crouch"
            exported = export_asset(source, package, "unity")
            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))["humanoid_mapping"]
            document, _ = read(source / "model.glb")
            joints = sorted({i for skin in document['skins'] for i in skin['joints']})
            expected = dict(bones=[document['nodes'][i]['name'] for i in joints],
                            clips=exported['animations'], height=exported['conversion']['height_m'],
                            surfaces=[dict(name=item['name'], albedo=item['maps'].get('BaseColor',''))
                                      for item in exported['materials']],
                            ankles=[mapping[side+'_foot'] for side in ('left','right')],
                            knees=[mapping[side+'_shin'] for side in ('left','right')],
                            hips=[mapping[side+'_leg'] for side in ('left','right')])
            (work / "crouch.json").write_text(json.dumps(expected), encoding="utf-8")
        (project / "Packages").mkdir()
        dependencies = {"com.unity.modules.terrain": "1.0.0", "com.unity.modules.terrainphysics": "1.0.0",
                        "com.unity.modules.animation": "1.0.0", "com.unity.modules.physics": "1.0.0",
                        "com.unity.modules.jsonserialize": "1.0.0", "com.unity.modules.imageconversion": "1.0.0"}
        urp = editor.parent / "Data/Resources/PackageManager/BuiltInPackages/com.unity.render-pipelines.universal/package.json"
        if urp.is_file():
            dependencies["com.unity.render-pipelines.universal"] = json.loads(urp.read_text())["version"]
        (project / "Packages" / "manifest.json").write_text(json.dumps({"dependencies": dependencies}), encoding="utf-8")
        log = work / "unity.log"
        result = subprocess.run(
            [str(editor), "-batchmode", "-nographics", *([] if vault else ["-quit"]), "-projectPath", str(project),
             "-logFile", str(log), "-executeMethod", "TrellisStudio.ReimportRegression.Run"],
            timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        report = log.read_text(encoding="utf-8", errors="replace")
        markers = ["TRELLIS REIMPORT PASS", "TRELLIS TERRAIN PASS", "TRELLIS MATERIAL PASS", "TRELLIS LOD BIND PASS"]
        if crouch_model:
            markers.append("TRELLIS CHARACTER PASS")
        if vault:
            markers += ["TRELLIS VAULT PASS", "TRELLIS FBX POSES PASS"]
        if result.returncode or any(marker not in report for marker in markers):
            errors = [line for line in report.splitlines() if "Exception:" in line or "error CS" in line or line.startswith("TRELLIS ")]
            print("\n".join(errors[-20:]) or report[-3000:])
            raise SystemExit("Unity reimport regression failed.")
        print("\n".join(next(line for line in report.splitlines() if marker in line) for marker in markers))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unity", type=Path)
    parser.add_argument("--crouch-model", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--vault", action="store_true")
    parser.add_argument("--vault-model", type=Path)
    args = parser.parse_args()
    if bool(args.crouch_model) != bool(args.mapping):
        parser.error("--crouch-model and --mapping must be supplied together")
    run(args.unity.resolve(strict=True), args.crouch_model, args.mapping, args.vault or args.vault_model, args.vault_model)
