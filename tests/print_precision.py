"""Measure two calibration walls using the production Blender print worker."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_preflight import asset_report, options
from target_export import export_asset


def check(directory, thickness):
    job = directory / str(thickness)
    job.mkdir()
    box = trimesh.creation.box(extents=(.03, .04, thickness/1000))
    (job/'source.glb').write_bytes(box.export(file_type='glb'))
    (job/'metadata.json').write_text('{}')
    (job/'settings.json').write_text(json.dumps(dict(name='Wall',parent_id='fixture',
        print_options=dict(height_mm=40,voxel_mm=.20,measure_walls=True))))
    subprocess.run([sys.executable,str(ROOT/'print_worker.py'),str(job)],check=True,timeout=180)
    status = json.loads((job/'status.json').read_text(encoding='utf-8'))
    assert status['state']=='done', status
    report = status['result']['print_report']
    measurement = report['sampled_wall_mm']
    assert report['closed_surface'] and measurement['hits'] > 0
    print(f"wall {thickness} mm / sampled minimum {measurement['minimum']:.3f} mm", flush=True)
    budget = options({'usage':'print'},'print')
    preflight = asset_report(job,'print',budget)
    row = next(r for r in preflight['checks'] if r['label']=='Delivered STL')
    assert row['status']=='checked'
    manifest = export_asset(job,directory/f'export-{thickness}','print',preflight_budget=budget)
    assert manifest['print_report']['stl_sha256']==manifest['delivered_stl_sha256']
    assert row in manifest['preflight']['checks']
    return measurement['minimum']


if __name__=='__main__':
    with TemporaryDirectory(prefix='trellis-walls-') as name:
        thin, thick = [check(Path(name),mm) for mm in (2,4)]
        assert abs(thin-2)<.5 and abs(thick-4)<.5, (thin,thick)
