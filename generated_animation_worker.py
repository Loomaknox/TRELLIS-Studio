"""Generate reusable motions, or transactionally add one to an existing rigged model."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json, subprocess, sys, time, traceback, uuid
from generated_animations import (PROVENANCE_FIELDS, SOURCE_FILES, digest, finish_source,
                                  library_path, load_motion, validate_skeleton)
from generated_animation_runtime import command, load_config, stop_runtime
from studio_import import validate_glb
from studio_workspace import read, write

ROOT=Path(__file__).resolve().parent

def generate(folder):
    config=load_config(ROOT);manifest=read(folder/'manifest.json')
    write(folder/'runtime-config.json',config)
    write(folder/'status.json',dict(state='running',stage='Loading the CPU animation runtime',progress=5))
    subprocess.run(command(ROOT,folder,config),check=True,timeout=config['timeout_seconds']+30,
                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    provenance={key:config[key] for key in PROVENANCE_FIELDS if key in config}
    provenance.update(engine='kimodo',seed=manifest['seed'],prompt=manifest['prompt'],duration=manifest['duration'],
                      fps=30,steps=config['steps'],guidance=[2,2],animation_id=folder.name)
    write(folder/'status.json',dict(state='running',stage='Saving the reusable animation and preview',progress=95))
    finish_source(folder,folder/'decoded',read(config['skeleton']),provenance)

def apply_copy(folder):
    """Finish a legacy copy operation admitted before the same-model update contract."""
    from generated_motion import append_generated_motion
    request=read(folder/'generated-animation-request.json')
    library=library_path(request['library_root'],request['animation_id'])
    manifest=read(library/'manifest.json')
    if read(library/'status.json',{}).get('state')!='done':raise ValueError('This animation is not ready.')
    for filename in ('motion.npz','skeleton.json'):
        source=library/filename
        if source.is_symlink() or digest(source)!=manifest['files'][filename]['sha256']:
            raise ValueError('The saved animation source changed. Generate or import a new entry.')
    load_motion(library/'motion.npz',manifest['frames'])
    skeleton=validate_skeleton(read(library/'skeleton.json'))
    previous_result=request.get('result') or {}
    mapping=previous_result.get('humanoid_mapping')
    write(folder/'status.json',dict(state='running',stage='Transferring the saved motion to a model copy',progress=20))
    source=folder/'source.glb'
    before=validate_glb(source)
    if any(clip.get('name')==manifest['clip_name'] for clip in before.get('animations',[])):
        raise ValueError('This generated animation is already attached to the model.')
    report=append_generated_motion(source,folder/'model.glb',motion_path=library/'motion.npz',skeleton=skeleton,
        clip_name=manifest['clip_name'],provenance=manifest['provenance'],target_mapping=mapping,
        in_place=request.get('in_place') is True)
    after=validate_glb(folder/'model.glb')
    if len(after.get('animations',[]))!=len(before.get('animations',[]))+1:
        raise ValueError('The transferred model did not retain its animation set.')
    for lod in sorted((folder/'LODs').glob('LOD*.glb')):
        target=lod.with_name(lod.stem+'.generated.glb')
        append_generated_motion(lod,target,motion_path=library/'motion.npz',skeleton=skeleton,
            clip_name=manifest['clip_name'],provenance=manifest['provenance'],target_mapping=mapping,
            in_place=request.get('in_place') is True)
        target.replace(lod)
    settings=read(folder/'settings.json')
    settings['generated_animation_clips']=[*settings.get('generated_animation_clips',[]),
        dict(id=library.name,clip=manifest['clip_name'],name=manifest['name'],duration=manifest['duration'],
             in_place=request.get('in_place') is True)]
    write(folder/'settings.json',settings)
    result={**previous_result,'revision':time.time_ns(),'animations':len(after.get('animations',[])),
            'generated_animation_report':report}
    write(folder/'result.json',result)
    # These are snapshots created solely for this operation, never original assets.
    # The private workspace locator must not travel with a user's exported model.
    (folder/'generated-animation-request.json').unlink(missing_ok=True)
    (folder/'source.glb').unlink(missing_ok=True)
    write(folder/'status.json',dict(state='done',stage='Animation added to a new model copy',progress=100,result=result))


def apply_update(folder):
    from animation_edits import publish_operation
    from generated_motion import append_generated_motion
    from studio_import import find_blender
    request=read(folder/'generated-animation-request.json')
    deferred=request.get('defer_publish') is True
    previous_result=request.get('result') or {}
    library=library_path(request['library_root'],request['animation_id'])
    manifest=read(library/'manifest.json')
    if read(library/'status.json',{}).get('state')!='done':raise ValueError('This animation is not ready.')
    for filename in ('motion.npz','skeleton.json'):
        item=library/filename
        if item.is_symlink() or digest(item)!=manifest['files'][filename]['sha256']:
            raise ValueError('The saved animation source changed. Generate or import a new entry.')
    load_motion(library/'motion.npz',manifest['frames'])
    skeleton=validate_skeleton(read(library/'skeleton.json'))
    source=folder/('source.glb' if deferred else 'model.glb')
    before=validate_glb(source)
    if any(clip.get('name')==manifest['clip_name'] for clip in before.get('animations',[])):
        raise ValueError('This generated animation is already attached to the model.')
    write(folder/'status.json',dict(state='running',stage='Adding the saved motion to the model',progress=20,
                                    operation='animation',result=previous_result))
    with TemporaryDirectory(prefix='.generated-transfer-',dir=folder,ignore_cleanup_errors=True) as temporary:
        # Server already has a unique operation directory. Avoid an unnecessary
        # nesting level that can exceed Windows path limits during atomic writes.
        stage=Path(temporary) if deferred else Path(temporary)/uuid.uuid4().hex
        if not deferred:stage.mkdir()
        options=dict(motion_path=library/'motion.npz',skeleton=skeleton,clip_name=manifest['clip_name'],
                     provenance=manifest['provenance'],target_mapping=previous_result.get('humanoid_mapping'),
                     in_place=request.get('in_place') is True)
        report=append_generated_motion(source,stage/'model.glb',**options)
        after=validate_glb(stage/'model.glb')
        if len(after.get('animations',[]))!=len(before.get('animations',[]))+1:
            raise ValueError('The updated model did not retain its animation set.')
        files=['model.glb','settings.json','result.json']
        for lod in sorted((folder/'LODs').glob('LOD*.glb')):
            target=stage/'LODs'/lod.name
            target.parent.mkdir(exist_ok=True)
            append_generated_motion(lod,target,**options)
            files.append('LODs/'+lod.name)
        if request.get('update_blend'):
            blender=find_blender()
            if not blender:raise ValueError('Blender is unavailable. The model and its animations are unchanged.')
            subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
                            '--python',str(ROOT/'animation_blend.py'),'--',str(stage)],
                           check=True,timeout=240,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if not (stage/'model.blend').is_file():raise ValueError('The Blender companion could not be updated.')
            files.append('model.blend')
        settings=dict(request['settings'])
        settings.pop('generated_animation_action',None)
        settings['generated_animation_clips']=[*settings.get('generated_animation_clips',[]),
            dict(id=library.name,clip=manifest['clip_name'],name=manifest['name'],duration=manifest['duration'],
                 in_place=request.get('in_place') is True)]
        result={**previous_result,'revision':time.time_ns(),'animations':len(after.get('animations',[])),
                'generated_animation_report':report}
        write(stage/'settings.json',settings);write(stage/'result.json',result)
        state=dict(state='ready',stage='Saving animation to model',progress=98,operation='animation',
                   result=result,updated_files=files,removed_files=[])
        if deferred:
            for name in files:
                destination=folder/name
                destination.parent.mkdir(parents=True,exist_ok=True)
                (stage/name).replace(destination)
            write(folder/'status.json',state)
        else:
            publish_operation(folder,stage,state,request['revision'],allow_active=True)
    # Publication has completed. A transient Windows file lock during cleanup
    # must not turn a successful commit into a failure with stale metadata.
    try:
        (folder/'generated-animation-request.json').unlink(missing_ok=True)
    except OSError:
        print('Animation saved; a temporary request could not be removed.',file=sys.stderr)


def apply(folder):
    if read(folder/'generated-animation-request.json',{}).get('update_model'):
        return apply_update(folder)
    return apply_copy(folder)

def main(folder):
    folder=Path(folder).resolve()
    try:
        action='apply' if (folder/'generated-animation-request.json').is_file() else read(folder/'settings.json',{}).get('generated_animation_action')
        if action=='generate':generate(folder)
        elif action=='apply':apply(folder)
        else:raise ValueError('Unknown animation operation.')
    except Exception as error:
        stop_runtime(ROOT,folder)
        traceback.print_exc()
        # Paths and runtime configuration belong in the private log, never in API errors.
        message=str(error) if isinstance(error,ValueError) and not any(c in str(error) for c in ('/','\\')) else 'Animation preparation failed. The original models and saved motions are preserved.'
        request=read(folder/'generated-animation-request.json',{})
        if request.get('update_model') and not request.get('defer_publish'):
            from animation_edits import recover
            recover(folder)
            write(folder/'status.json',dict(state='done',stage='Animation update failed; model preserved',progress=100,
                                            result=request.get('result') or {},operation_error=message))
            (folder/'generated-animation-request.json').unlink(missing_ok=True)
        else:
            write(folder/'status.json',dict(state='error',stage='Animation preparation failed',progress=0,error=message))
        return 1
    return 0

if __name__=='__main__':sys.exit(main(sys.argv[1]))
