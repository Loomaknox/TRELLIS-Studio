"""Exercise the actual motion-edit worker and reread its published animation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from glb_data import read
from target_export import conversion_glb


def edit_vault(folder, start=0., end=1., mode='root_motion', distance=0., sibling=False, source=None, blend=0.):
    folder.mkdir()
    source = source or ROOT/'web/side-vault-preview.glb'
    shutil.copy2(source, folder/'model.glb')
    document, binary = read(source)
    original = next(clip for clip in document['animations'] if 'trellis_contact' in clip.get('extras', {}))
    if sibling:
        document['animations'].append({**original,'name':'Unchanged vault'})
        conversion_glb(document, binary, folder/'model.glb')
    clip = original['name']
    hints = original['extras']
    recipe = dict(id='side_vault', clip=clip, duration_s=3,
                  obstacle=hints['trellis_obstacle'], contact=hints['trellis_contact'])
    options = dict(clip=clip,start=start,end=end,duration=2.,mode=mode,distance=distance,loop=bool(blend),blend=blend)
    settings = dict(name='Vault regression',animation_clips=[dict(id='side_vault',duration=3.)])
    request = dict(operation='motion', options=options, settings=settings, result=dict(animation_set=[recipe]))
    for name, value in [('work-request',request),('settings',settings)]:
        (folder/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
    run = subprocess.run([sys.executable,'-B',str(ROOT/'asset_work.py'),str(folder)],
                         capture_output=True,text=True,errors='replace',timeout=180)
    status = json.loads((folder/'status.json').read_text())
    assert run.returncode == 0 and not status.get('operation_error') and status['state']=='done', (status,run.stdout[-2500:])
    result = json.loads((folder/'result.json').read_text())
    report = json.loads((folder/'motion-report.json').read_text())
    assert result['motion_report'] == report
    recipe = result['animation_set'][0]
    doc = read(folder/'model.glb')[0]
    extras = next(a for a in doc['animations'] if a['name']==recipe['clip']).get('extras', {})
    for field in ('contact','obstacle'):
        assert extras.get('trellis_'+field) == recipe.get(field)
    if sibling:
        assert next(a for a in doc['animations'] if a['name']=='Unchanged vault')['extras']==hints
    return report['obstacle_contact_status'], recipe


if __name__ == '__main__':
    with TemporaryDirectory(prefix='trellis-edit-vault-') as scratch:
        tests = [
            ({'sibling':True}, 'verified', [.864,1.110]),
            ({'start':.47,'end':.54}, 'verified', [0.,2.]),
            ({'start':.5,'end':.75}, 'verified', [0.,.44]),
            ({'start':.1,'end':.55,'blend':.4}, 'unverified', None),
            ({'end':.30}, 'trimmed', None),
            ({'start':.65}, 'trimmed', None),
            ({'mode':'in_place'}, 'root_changed', None),
            ({'distance':.7}, 'root_changed', None),
        ]
        for index,(options,expected,times) in enumerate(tests):
            status,item = edit_vault(Path(scratch)/str(index), **options)
            assert status == expected, (options,status)
            if times is None:
                assert 'contact' not in item and 'obstacle' not in item
            else:
                assert np.allclose(item['contact']['interval_s'],times,atol=1e-5), item['contact']
                assert item['contact']['max_sample_error_m'] < .045
            if index == 0 and (ROOT/'node_modules/three').is_dir() and shutil.which('node'):
                subprocess.run(['node','--test',str(ROOT/'tests/motion_obstacle.mjs')],check=True,
                               env={**os.environ,'TRELLIS_EDITED_VAULT':str(Path(scratch)/str(index)/'model.glb')})
            print(options,status,flush=True)
