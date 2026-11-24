"""Exercise archive manifests against their actual materials and STL bytes."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import numpy as np
from PIL import Image, ImageDraw
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from asset_provenance import capture_generation, export_provenance
from export_preflight import asset_report, options
from glb_data import read
from print_prepare import verify_stl
from studio_transfer import export_lineage, snapshot_export
from studio_workspace import write
from target_export import conversion_glb


def asset(library, letter, **settings):
    folder = library / (letter * 32)
    folder.mkdir(parents=True)
    write(folder/'settings.json', dict(name='Calibration '+letter, **settings))
    write(folder/'metadata.json', {})
    return folder


def package(work, target, members, preflight=None):
    task = work / target
    task.mkdir()
    records = [(p, dict(settings=json.loads((p/'settings.json').read_text()), metadata={})) for p in members]
    snapshot_export(records, task, target, False)
    write(task/'request.json', dict(target=target, ids=[p.name for p in members], preflight=preflight))
    subprocess.run([sys.executable, str(ROOT/'export_worker.py'), str(task)], check=True, timeout=480)
    assert json.loads((task/'status.json').read_text())['state'] == 'done'
    return zipfile.ZipFile(task/'package.zip')


def surface(path):
    sphere = trimesh.creation.uv_sphere(radius=.5,count=[20, 24])
    n = sphere.vertex_normals
    uv = np.column_stack([np.arctan2(n[:,2],n[:,0])/(2*np.pi)+.5, np.arcsin(np.clip(n[:,1],-1,1))/np.pi+.5])
    paint = Image.new('RGB', (2048,2048), '#57788e')
    draw = ImageDraw.Draw(paint)
    draw.rectangle((0,900,2047,1100), fill='#dc824d')
    material = trimesh.visual.material.PBRMaterial(baseColorTexture=paint, roughnessFactor=.6)
    sphere.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    path.write_bytes(sphere.export(file_type='glb'))
    doc, buf = read(path)
    for node in doc['nodes']:
        if 'matrix' in node and np.allclose(np.reshape(node['matrix'], (4,4)), np.eye(4)):
            del node['matrix']
    conversion_glb(doc, buf, path)


def materials(work, library, live):
    original = asset(library,'a',texture_method='trellis',engine='trellis2')
    derived = asset(library,'b',source_kind='multiview_texture_refinement',parent_id=original.name)
    settings = json.loads((original/'settings.json').read_text())
    capture_generation(settings, 'multiview', dict(reason_code='not_installed',reason='Runtime absent'))
    write(original/'settings.json', settings)
    write(original/'result.json', dict(engine='TRELLIS.2',texture_method='trellis'))
    surface(original/'model.glb')
    (derived/'model.glb').write_bytes((original/'model.glb').read_bytes())
    if live:
        from ultratex_runtime import refine
        reference = Image.new('RGBA',(512,512))
        drawing = ImageDraw.Draw(reference)
        drawing.ellipse((32,32,479,479),fill='#57788e')
        drawing.rectangle((34,236,477,277),fill='#dc824d')
        reference.save(derived/'reference.png')
        receipt = refine(ROOT, derived/'model.glb', derived/'reference.png', 2048, 42,
                         progress=lambda stage,percent: print(stage,flush=True))
        assert receipt['state']=='applied', receipt
    else:
        receipt = dict(state='applied',revisions={'runtime':'recorded-fixture'})
    write(derived/'result.json', dict(multiview_texture_refinement=dict(receipt, texture_method='ultratex')))
    with package(work,'unity',[original,derived]) as archive:
        assert archive.testzip() is None
        for row in json.loads(archive.read('export-manifest.json'))['models']:
            prefix = row['file']+'/'
            manifest = json.loads(archive.read(prefix+'studio-export.json'))
            provenance = manifest['provenance']
            assert archive.read(prefix+'model.fbx').startswith(b'Kaydara FBX Binary')
            assert hashlib.sha256(archive.read(prefix+'model.glb')).hexdigest() == manifest['source_glb_sha256']
            for entry in provenance['component_conditions']:
                if document := entry.get('document'):
                    assert hashlib.sha256(archive.read(prefix+'Licenses/'+document)).hexdigest() == entry['sha256']
            maps = manifest['materials'][0]['maps']
            assert Image.open(io.BytesIO(archive.read(prefix+maps['BaseColor']))).size == (2048,2048)
            assert provenance['fallbacks'][0]['stage']=='before_generation'
            assert provenance['submission_pins']['engine_source']
            assert provenance['used_engine']=='TRELLIS.2'
            if row['id'] == derived.name:
                assert provenance['lineage']==[original.name] and provenance['used_texture']=='ultratex'
                assert 'FLUX.2 Klein Base 9B' in [e['component'] for e in provenance['component_conditions']]
                if live:
                    assert manifest['source_glb_sha256'] == receipt['output_sha256'] and receipt['geometry_uv_equal']
                    assert Image.open(io.BytesIO(archive.read(prefix+maps['MetallicRoughness']))).size == (2048,2048)
            else:
                assert provenance['requested_texture']=='multiview' and provenance['used_texture']=='trellis'
            print('PACKAGE',provenance['used_texture'],manifest['source_glb_sha256'],sorted(maps),flush=True)
    if live:
        print('LIVE ULTRATEX',json.dumps(receipt,ensure_ascii=True),flush=True)


def print_batch(work, library):
    budget = options({'usage':'print'}, 'print')
    assets = []
    hashes = {}
    statuses = []
    for index, letter in enumerate(['c','d']):
        folder = asset(library,letter)
        mesh = trimesh.creation.box(extents=(20,40,4))
        if index:
            mesh.update_faces(np.arange(len(mesh.faces)-2))
        (folder/'model.stl').write_bytes(mesh.export(file_type='stl'))
        mesh.apply_scale(.001)
        (folder/'model.glb').write_bytes(mesh.export(file_type='glb'))
        report = verify_stl(folder/'model.stl',dict(boundary_edges=int((np.bincount(mesh.edges_unique_inverse)==1).sum()),
                            nonmanifold_edges=0,nonmanifold_vertices=0,warnings=[]))
        write(folder/'print-report.json',report)
        preflight = asset_report(folder, 'print', budget)
        row = next(r for r in preflight['checks'] if r['label']=='Delivered STL')
        statuses.append(row['status'])
        hashes[folder.name] = preflight['source_glb_sha256']
        assets.append(folder)
    assert statuses==['checked','attention']
    with package(work,'print',assets,dict(budget=budget,source_hashes=hashes)) as archive:
        rows = json.loads(archive.read('export-manifest.json'))['models']
        assert [r['verdict'] for r in rows]==['closed','needs_repair']
        for row, status in zip(rows,statuses):
            prefix = row['file']+'/'
            manifest = json.loads(archive.read(prefix+'studio-export.json'))
            report = json.loads(archive.read(prefix+'print-report.json'))
            assert row['closed_surface'] == report['closed_surface']
            assert row['delivered_stl_sha256']==report['stl_sha256']==hashlib.sha256(archive.read(prefix+'model.stl')).hexdigest()
            assert next(r['status'] for r in manifest['preflight']['checks'] if r['label']=='Delivered STL')==status
            print('STL',row['verdict'],row['delivered_stl_sha256'],status)


def legacy(library):
    data = export_provenance({}, dict(workflow='legacy',finishing=[]))
    assert data['missing_evidence']==['engine','texture','runtime_revision'] and not data['submission_pins']
    folder = asset(library,'e',source_kind='rig',parent_id='../other-account')
    assert export_lineage(folder,json.loads((folder/'settings.json').read_text()))['status']=='invalid_or_cyclic'
    pinned = export_provenance({}, dict(finishing=dict(multiview_texture_refinement=dict(state='applied',
                              view_generation=dict(adapter_revision='historical-pin')))))
    assert 'historical-pin' in pinned['recorded_revisions'].values()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--live-ultratex', action='store_true')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='trellis-export-receipts-') as temp:
        work=Path(temp)
        legacy(work/'library')
        print_batch(work,work/'library')
        materials(work,work/'library',args.live_ultratex)
