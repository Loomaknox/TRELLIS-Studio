"""Check the exported vault, including poses between Blender's 24 Hz bake keys.

Run without arguments to bake the installed Quaternius mannequin, or pass the
output directory of standard_animations.py to inspect another fitted humanoid.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import struct
import subprocess
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from glb_data import read
from animation_diagnostics import read_tracks, world_positions
from retarget_catalogue import ROOT, BY_ID
from studio_import import find_blender


def inspect(job):
    doc,binary = read(job/'model.glb')
    result = json.loads((job/'result.json').read_text(encoding='utf-8'))
    mapping=result['humanoid_mapping']
    item=next(a for a in result['animation_set'] if a['id']=='side_vault')
    clip=next(c for c in doc['animations'] if c['name']==item['clip'])
    extras=clip['extras']
    box,contact=extras['trellis_obstacle'],extras['trellis_contact']
    assert box==item['obstacle'] and contact==item['contact']
    lookup={n.get('name'):i for i,n in enumerate(doc['nodes'])}
    tracks,_,errors=read_tracks(doc,binary,clip)
    assert not errors, errors
    times=np.linspace(0,item['duration_s'],round(item['duration_s']*192)+1)
    t=times/item['duration_s']
    ids={r:lookup[mapping[r]] for r in ('root','left_foot','right_foot','left_shin','right_shin',
            'left_forearm','left_hand','right_hand','left_toe','right_toe') if r in mapping}
    ids['palm']=lookup[contact['bone']]
    pts=world_positions(doc['nodes'],tracks,ids,times,{'palm':contact['palm_offset']})
    height=result['height_m']
    target=np.array(contact['palm_target'])
    b=np.asarray(box['center']); size=np.asarray(box['size'])
    top=b[1]+size[1]/2
    forward=np.asarray(box['travel'])
    forward=forward/np.linalg.norm(forward)
    side=np.cross([0.,1.,0.],forward)
    interval=np.array(contact['interval_s'])
    # Blender's forced LINEAR export stores samples at 24 Hz; inside this
    # conservative interval both ends of each interpolation segment are planted.
    held=(times>=interval[0]+1/24)&(times<=interval[1]-1/24)
    assert held.any() and interval[1]-interval[0] >= .10*item['duration_s']
    err=np.linalg.norm(pts['palm'][held]-target,axis=1)
    assert abs(target[1]-top)<1e-4
    margins={}
    for key in ('left_foot','right_foot','left_toe','right_toe','left_shin','right_shin'):
        if key not in pts: continue
        p=pts[key]
        crossing=(np.abs((p-b)@forward)<=size[2]/2)&(np.abs((p-b)@side)<=size[0]/2)
        if crossing.any():
            margins[key]=float(p[crossing,1].min()-top)
    travel=pts['root'][-1]-pts['root'][0]
    # Forward progress, visible sideways leg sweep and measurable hull clearance.
    lateral=float(np.max((pts['left_foot']-pts['root'])[(t>.43)&(t<.62)]@side))
    traverse=(t[:-1]>.33)&(t[:-1]<.77)
    normalized_speed={key:float(np.max(np.linalg.norm(np.diff(pts[key],axis=0),axis=1)[traverse]/
                                       np.diff(t)[traverse])/height)
                      for key in ('left_forearm','left_hand','right_hand','left_shin','right_shin')}
    metrics={'palm_max_m':float(err.max()),'margins_m':margins,'lateral_sweep_m':lateral,
             'travel_m':travel.tolist(),'peak_joint_speeds_in_heights_per_clip':normalized_speed}
    print(item['clip'],json.dumps(metrics,indent=2),flush=True)
    assert np.linalg.norm(travel-np.asarray(box['travel'])) < height*.02
    assert err.max()<height*.011, metrics
    assert margins and min(margins.values())>.025*height, metrics
    assert lateral>height*.10, metrics
    # Catches the historical elbow/knee plane flips (0.25 m in one 60 Hz frame).
    assert max(normalized_speed.values())<13, metrics
    return metrics


def run_reference(duration=3.):
    blender=find_blender()
    if not blender:
        raise RuntimeError('Install Blender or set TRELLIS_BLENDER for this integration test.')
    donor=ROOT/BY_ID['side_vault']['source_model'].replace('\\','/')
    raw=donor.read_bytes()
    length=struct.unpack_from('<I',raw,12)[0]
    data=json.loads(raw[20:20+length])
    data.pop('animations',None)
    desc=json.dumps(data,separators=(',',':')).encode()
    desc+=b' '*(-len(desc)%4)
    tail=raw[20+length:]
    with TemporaryDirectory(prefix='trellis-side-vault-') as scratch:
        job=Path(scratch)
        (job/'rig-work').mkdir()
        (job/'rig-work'/'rigged.glb').write_bytes(
            struct.pack('<4sIIII',b'glTF',2,20+len(desc)+len(tail),len(desc),0x4e4f534a)+desc+tail)
        settings={'animation_clips':[{'id':'side_vault','duration':duration}]}
        (job/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
        subprocess.run([str(blender),'-b','-t','4','--factory-startup','--disable-autoexec',
                        '--python-exit-code','1','-P',str(ROOT/'standard_animations.py'),'--',str(job)],check=True)
        inspect(job)


if __name__=='__main__':
    if len(sys.argv)==1:
        run_reference()
    elif sys.argv[1]=='--duration':
        run_reference(float(sys.argv[2]))
    else:
        inspect(Path(sys.argv[1]))
