"""Persistent, workspace-scoped canonical motions; independent of target characters."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib, json, re, shutil, time, uuid, zipfile
import numpy as np
from api_contract import GeneratedAnimationCreate
from studio_workspace import ID, job_status, read, write

SOURCE_FILES = ('motion.npz', 'skeleton.json', 'preview.glb')
PROVENANCE_FIELDS = {'engine','model','runtime','model_sha256','text_encoder_sha256','source_revision',
                     'seed','prompt','duration','fps','steps','guidance','animation_id'}
MAX_ENTRIES = 500
MAX_PENDING = 8

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):value.update(block)
    return value.hexdigest()

def library_path(root, identifier):
    root=Path(root).resolve()
    if not isinstance(identifier,str) or not ID.fullmatch(identifier):raise ValueError('Animation not found.')
    folder=root/identifier
    if folder.resolve()!=folder or not folder.is_dir():raise ValueError('Animation not found.')
    return folder

def validate_skeleton(value):
    if not isinstance(value,dict):raise ValueError('Invalid motion skeleton.')
    if (value.get('fps',30)!=30 or value.get('units','metres') not in ('metres','meters')
        or value.get('up','Y')!='Y' or value.get('forward','+Z')!='+Z'
        or value.get('quaternion_order','xyzw')!='xyzw'
        or 'Y-up' not in str(value.get('coordinate_system','Y-up'))):
        raise ValueError('Motion sources must use metres, Y-up, XYZW rotations and 30 fps.')
    for key in ('rest_local_quaternions_xyzw','rest_local_rotations_xyzw'):
        if key in value:
            rest=np.asarray(value[key],dtype=np.float64)
            if rest.shape!=(30,4) or not np.isfinite(rest).all() or np.max(abs(rest-[0,0,0,1]))>1e-6:
                raise ValueError('A standard T-pose source skeleton is required.')
    names=value.get('names');parents=value.get('parents');offsets=np.asarray(value.get('offsets'),dtype=np.float64)
    if (not isinstance(names,list) or len(names)!=30 or len(set(names))!=30
        or any(not isinstance(n,str) or not n or len(n)>80 for n in names)
        or not isinstance(parents,list) or len(parents)!=30
        or parents[0]!=-1 or any(type(p) is not int or not 0<=p<j for j,p in enumerate(parents[1:],1))
        or offsets.shape!=(30,3) or not np.isfinite(offsets).all() or np.max(abs(offsets))>5):
        raise ValueError('Expected a finite, topologically ordered SOMA30 skeleton in metres.')
    # Identity local rest rotations and a neutral root are required by this decoder.
    if np.linalg.norm(offsets[0])>1e-6:raise ValueError('The canonical motion root must be neutral.')
    return dict(names=names,parents=parents,offsets=offsets.tolist(),fps=30,units='metres',
                coordinate_system='right-handed Y-up; initial facing +Z',
                rest_local_quaternions_xyzw=[[0,0,0,1] for _ in names])

def load_motion(path, expected_frames=None):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>8*1024**2:raise ValueError('Motion source exceeds its size limit.')
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist())>64 or sum(item.file_size for item in archive.infolist())>8*1024**2:
            raise ValueError('Motion source exceeds its expanded size limit.')
    with np.load(path,allow_pickle=False) as data:
        positions=np.asarray(data['root_positions'],dtype=np.float32)
        rotations=np.asarray(data['local_rotations_xyzw'],dtype=np.float32)
    if (positions.ndim!=2 or positions.shape[1:]!=(3,) or not 60<=len(positions)<=300
        or expected_frames is not None and len(positions)!=expected_frames
        or rotations.shape!=(len(positions),30,4) or not np.isfinite(positions).all()
        or not np.isfinite(rotations).all() or np.max(abs(positions))>100
        or np.max(abs(np.linalg.norm(rotations,axis=-1)-1))>1e-3):
        raise ValueError('Invalid motion samples, duration or rotations.')
    return positions,rotations

def canonicalize(source, destination, frames):
    source=Path(source);destination=Path(destination)
    if (source/'motion.npz').is_file():
        positions,rotations=load_motion(source/'motion.npz',frames)
    else:
        position_path=source/'root_positions.f32';rotation_path=source/'local_rotations_xyzw.f32'
        if (position_path.stat().st_size!=frames*3*4 or rotation_path.stat().st_size!=frames*30*4*4
            or position_path.is_symlink() or rotation_path.is_symlink()):raise ValueError('Incomplete decoded motion buffers.')
        positions=np.fromfile(position_path,dtype='<f4').reshape(frames,3)
        rotations=np.fromfile(rotation_path,dtype='<f4').reshape(frames,30,4)
        temporary=destination.with_suffix('.validation.npz')
        np.savez_compressed(temporary,root_positions=positions,local_rotations_xyzw=rotations)
        try:positions,rotations=load_motion(temporary,frames)
        finally:temporary.unlink(missing_ok=True)
    np.savez_compressed(destination,root_positions=positions,local_rotations_xyzw=rotations,fps=np.float32(30))

def clip_name(identifier, name):
    label=re.sub(r'[^A-Za-z0-9_]+','_',name).strip('_') or 'Motion'
    return 'Generated_'+identifier[:8]+'_'+label[:60]

def record(folder):
    folder=Path(folder);manifest=read(folder/'manifest.json',{});state=job_status(folder)
    if not manifest:return None
    result={key:manifest.get(key) for key in ('name','prompt','duration','seed','fps','frames','created','clip_name','provenance','preview_root')}
    result.update(id=folder.name,state=state.get('state','error'),stage=state.get('stage',''),progress=state.get('progress',0),
                  preview_url=f'/api/my-animations/{folder.name}/files/preview.glb' if state.get('state')=='done' and (folder/'preview.glb').is_file() else None)
    result['files']={filename:f'/api/my-animations/{folder.name}/files/{filename}' for filename in SOURCE_FILES
                     if state.get('state')=='done' and (folder/filename).is_file() and not (folder/filename).is_symlink()}
    if state.get('error'):result['error']=state['error']
    return result

def list_records(root):
    root=Path(root).resolve()
    entries=[record(path) for path in root.iterdir() if ID.fullmatch(path.name) and path.is_dir() and path.resolve()==path] if root.is_dir() else []
    return sorted((item for item in entries if item),key=lambda item:item['created'],reverse=True)

def create_entry(root, recipe, provenance=None):
    recipe=GeneratedAnimationCreate.model_validate(recipe).model_dump()
    if recipe['name']=='New animation':recipe['name']=recipe['prompt'][:70]
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    entries=list_records(root)
    if len(entries)>=MAX_ENTRIES:raise ValueError('The personal animation library has reached its limit.')
    if sum(item['state'] in ('queued','running') for item in entries)>=MAX_PENDING:raise ValueError('Wait for pending animation generations to finish.')
    identifier=uuid.uuid4().hex
    manifest=dict(recipe,id=identifier,created=time.time(),fps=30,frames=round(recipe['duration']*30),
                  clip_name=clip_name(identifier,recipe['name']),provenance={k:v for k,v in (provenance or {}).items() if k in PROVENANCE_FIELDS})
    with TemporaryDirectory(prefix='.generated-motion-',dir=root) as temporary:
        staged=Path(temporary)
        write(staged/'manifest.json',manifest)
        write(staged/'settings.json',dict(name=recipe['name'],source_kind='generated_animation',generated_animation_action='generate'))
        write(staged/'status.json',dict(state='queued',stage='Waiting to generate animation',progress=0))
        staged.rename(root/identifier)
    return root/identifier

def finish_source(folder, source, skeleton, provenance):
    from generated_motion import create_motion_preview
    manifest=read(folder/'manifest.json');skeleton=validate_skeleton(skeleton)
    canonicalize(source,folder/'motion.npz',manifest['frames'])
    write(folder/'skeleton.json',skeleton)
    preview=create_motion_preview(folder/'motion.npz',skeleton,folder/'preview.glb',clip_name=manifest['clip_name'])
    manifest['preview_root']=preview.get('preview_root') if isinstance(preview,dict) else None
    manifest['provenance']={k:v for k,v in provenance.items() if k in PROVENANCE_FIELDS}
    manifest['files']={filename:dict(sha256=digest(folder/filename),bytes=(folder/filename).stat().st_size) for filename in SOURCE_FILES}
    write(folder/'manifest.json',manifest)
    write(folder/'status.json',dict(state='done',stage='Animation saved to My animations',progress=100))
    return record(folder)

def import_source(library_root, source_dir, *, name, prompt, seed, skeleton_path, provenance):
    """Trusted local administrator helper. No HTTP endpoint accepts filesystem paths."""
    source=Path(source_dir)
    if (source/'motion.npz').is_file():frames=len(load_motion(source/'motion.npz')[0])
    else:frames=(source/'root_positions.f32').stat().st_size//12
    folder=create_entry(library_root,dict(name=name,prompt=prompt,seed=seed,duration=frames/30),provenance)
    try:return finish_source(folder,source,read(skeleton_path),provenance)
    except Exception:
        write(folder/'status.json',dict(state='error',stage='Motion import failed',progress=0,error='The saved motion could not be imported.'))
        raise
