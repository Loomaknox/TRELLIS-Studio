"""Executed by Unreal Editor's Python plugin inside a disposable test project."""
import json
import os
from pathlib import Path
import unreal

source=Path(os.environ['TRELLIS_QA_FBX']).resolve(strict=True)
task=unreal.AssetImportTask()
task.filename=str(source)
task.destination_path='/Game/TrellisCandidate'
task.automated=True
task.save=True
options=unreal.FbxImportUI()
options.automated_import_should_detect_type=False
options.mesh_type_to_import=unreal.FBXImportType.FBXIT_SKELETAL_MESH
options.import_as_skeletal=True
options.import_mesh=True
options.import_animations=True
options.import_materials=True
task.options=options
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
assets=[unreal.load_asset(p) for p in task.imported_object_paths]
skeletal=[a for a in assets if isinstance(a,unreal.SkeletalMesh)]
clips=[a for a in assets if isinstance(a,unreal.AnimSequence)]
if not skeletal or not clips or not all(a.get_editor_property('skeleton') for a in skeletal):
    raise RuntimeError('The delivered FBX must import a skeletal mesh with a skeleton and animation.')
if not all(a.get_editor_property('materials') for a in skeletal):
    raise RuntimeError('No material slot in the imported skeletal mesh.')
Path(os.environ['TRELLIS_QA_UNREAL_REPORT']).write_text(json.dumps({
    'skeletal_meshes':[a.get_name() for a in skeletal], 'clips':[a.get_name() for a in clips],
    'engine':unreal.SystemLibrary.get_engine_version()},indent=2),encoding='utf-8')
