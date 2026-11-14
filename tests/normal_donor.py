"""CPU contract checks for exact, collection-scoped HD normal donors."""
from pathlib import Path
import hashlib
import json
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import trimesh

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from api_contract import Refinish
from normal_bake import (checked_normalization, has_parent_normal_provenance,
                         inspect_parent_normal_source, prepare_parent_normal_source)


def refuses(function, *args, contains=None, **kwargs):
    try:
        function(*args, **kwargs)
    except ValueError as error:
        if contains:assert contains in str(error), str(error)
    else:
        raise AssertionError('An invalid donor was accepted.')


with TemporaryDirectory(prefix='trellis-normal-donor-') as temporary:
    root=Path(temporary)
    identifier='a'*32
    source_id='b'*32
    folder=root/identifier;folder.mkdir()
    mesh=trimesh.creation.icosphere(subdivisions=1)
    mesh.visual=trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices),2)))
    (folder/'model.glb').write_bytes(mesh.export(file_type='glb',include_normals=True))
    (folder/'status.json').write_text(json.dumps({'state':'done'}))
    fingerprint=hashlib.sha256((folder/'model.glb').read_bytes()).hexdigest()
    parent=dict(scale=2.,translation=[3.,4.,5.],coordinate_system='y_up')
    target=dict(scale=5.,translation=[-1.,2.,-.5],coordinate_system='y_up')
    result=dict(finish_source_id=source_id,finishing=dict(normalization=parent,model_sha256=fingerprint))
    def write_result(value):
        (folder/'result.json').write_text(json.dumps(value))
    write_result(result)
    info=inspect_parent_normal_source(root,identifier,source_id)
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    donor,provenance=prepare_parent_normal_source(root,identifier,source_id,target,1/1024,fingerprint,parent)
    # Independently invert the parent transform and apply the target transform.
    expected=(np.asarray(mesh.vertices)-[3.,4.,5.])/2*5+[-1.,2.,-.5]
    assert np.allclose(donor['vertices'],expected,atol=2e-6)
    assert np.array_equal(donor['faces'],mesh.faces)
    assert np.allclose(donor['vertex_normals'],mesh.vertex_normals,atol=2e-6)
    assert donor['voxel_size']==5/1024 and donor['coordinate_system']=='y_up'
    assert provenance['alignment']=='exact saved export transforms'
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    assert has_parent_normal_provenance(result)
    assert not has_parent_normal_provenance({'finishing':[]})
    assert not has_parent_normal_provenance(None)
    for bad in ({},dict(parent,scale=0),dict(parent,scale=True),dict(parent,translation=[0,1]),
                dict(parent,translation=[0,False,1]),dict(parent,translation=[float('nan'),0,0])):
        refuses(checked_normalization,bad)
    for bad in ('../'+identifier,'c'*31,None):
        refuses(inspect_parent_normal_source,root,bad,source_id)
    refuses(inspect_parent_normal_source,root,identifier,'c'*32,contains='same decoded source')
    refuses(prepare_parent_normal_source,root,identifier,source_id,target,1/1024,'0'*64,parent,contains='changed after')
    refuses(prepare_parent_normal_source,root,identifier,source_id,target,1/1024,fingerprint,dict(parent,scale=3),contains='changed after')
    write_result(dict(finish_source_id=source_id,finishing={'normalization':parent}))
    refuses(inspect_parent_normal_source,root,identifier,source_id,contains='fingerprint')
    write_result(dict(finish_source_id=source_id,finishing={'model_sha256':fingerprint}))
    refuses(inspect_parent_normal_source,root,identifier,source_id,contains='normalization')
    write_result(result)
    (folder/'model.glb').write_bytes((folder/'model.glb').read_bytes()+b'changed')
    refuses(inspect_parent_normal_source,root,identifier,source_id,contains='changed after its normalization')
    # A resolved escape is rejected before any file is read, including junction-like paths.
    real_resolve=Path.resolve
    with patch.object(Path,'resolve',lambda self:root.parent/'outside'/identifier if self==folder else real_resolve(self)):
        refuses(inspect_parent_normal_source,root,identifier,source_id,contains='outside this collection')
    assert Refinish(normal_source='parent',bake_normals=True).normal_source=='parent'
    refuses(Refinish,normal_source='arbitrary-path')
print('PASS: exact donor remap, parent normals, immutable source, provenance/hash changes, legacy refusal, safe paths and API schema')
