"""Personal animation routes over the same workspace queue as other computations."""
import asyncio
from fastapi import HTTPException
from fastapi.responses import FileResponse
from api_contract import GeneratedAnimationCreate, GeneratedAnimationApply
from creature_rig import is_creature_rig
from generated_animations import SOURCE_FILES, create_entry, library_path, list_records, record
from generated_animation_runtime import public_status
from studio_import import validate_glb
from studio_workspace import read, write

def install(app,g):
    def root():return (g['STUDIO'].workspace.root/'generated-animations').resolve()
    def path(identifier):
        try:return library_path(root(),identifier)
        except ValueError as error:raise HTTPException(404,'Animation not found.') from error
    def enqueue(folder):
        if g.get('SHUTTING_DOWN'):raise HTTPException(503,'Studio is stopping.')
        if g.get('WORKSPACE_CONFIG'):g['launch_worker'](folder,'generated_animation_worker.py')
        else:g['STUDIO'].workspace.enqueue(folder.name)

    @app.get('/api/my-animations')
    def generated_animation_library():
        return dict(animations=list_records(root()),engine=public_status(g['ROOT']),min_duration=2,max_duration=10,step=.5)

    @app.get('/api/my-animations/{identifier}')
    def generated_animation(identifier:str):return record(path(identifier))

    @app.post('/api/my-animations',status_code=202)
    async def generate_animation(data:GeneratedAnimationCreate):
        async with g['LOCK']:
            if g.get('SHUTTING_DOWN'):raise HTTPException(503,'Studio is stopping.')
            if not public_status(g['ROOT'])['ready']:raise HTTPException(503,'Animation generation is not configured on this installation.')
            try:
                folder=create_entry(root(),data.model_dump())
                enqueue(folder)
            except ValueError as error:raise HTTPException(400,str(error)) from error
            except OSError as error:
                if 'folder' in locals():write(folder/'status.json',dict(state='error',stage='Unable to queue animation',progress=0))
                raise HTTPException(503,'Unable to queue animation generation.') from error
            return dict(id=folder.name,state='queued',status_url='/api/my-animations/'+folder.name)

    @app.post('/api/my-animations/{identifier}/cancel')
    async def cancel_generated_animation(identifier:str):
        async with g['LOCK']:
            folder=path(identifier)
            if read(folder/'status.json',{}).get('state') in ('done','error','cancelled'):return dict(ok=True)
            if g['ACTIVE']==identifier and g['PROCESS'] is not None and g['PROCESS'].poll() is None:
                await asyncio.to_thread(g['stop_worker'])
            for item in g['STUDIO'].workspace.queue['items']:
                if item['id']==identifier:item['cancelled']=True
            g['STUDIO'].workspace.save_queue()
            write(folder/'status.json',dict(state='cancelled',stage='Animation generation cancelled',progress=0))
            return dict(ok=True)

    @app.get('/api/my-animations/{identifier}/files/{filename}')
    def generated_animation_file(identifier:str,filename:str):
        folder=path(identifier)
        if filename not in SOURCE_FILES or read(folder/'status.json',{}).get('state')!='done':raise HTTPException(404)
        target=folder/filename
        if target.is_symlink() or target.resolve().parent!=folder or not target.is_file():raise HTTPException(404)
        return FileResponse(target,media_type={'preview.glb':'model/gltf-binary','skeleton.json':'application/json','motion.npz':'application/octet-stream'}[filename],
                            headers={'Cache-Control':'private, max-age=3600'})

    @app.post('/api/jobs/{identifier}/my-animations',status_code=202)
    async def apply_generated_animation(identifier:str,data:GeneratedAnimationApply):
        async with g['LOCK']:
            if g.get('SHUTTING_DOWN'):raise HTTPException(503,'Studio is stopping.')
            if not g.get('WORKSPACE_CONFIG'):g['require_idle']()
            library=path(data.animation_id);motion=record(library)
            if motion['state']!='done':raise HTTPException(409,'Choose a completed generated animation.')
            source,previous=g['STUDIO'].available(identifier)
            if is_creature_rig(previous['settings']):
                raise HTTPException(422, 'Generated humanoid motions cannot be retargeted to Creature rigs.')
            model=validate_glb(source/'model.glb')
            if not model.get('skins'):raise HTTPException(409,'Add a humanoid rig to the model first.')
            if any(clip.get('name')==motion['clip_name'] for clip in model.get('animations',[])):
                raise HTTPException(409,'This generated animation is already attached to the model.')
            update_blend=(source/'model.blend').is_file()
            if update_blend and not g['find_blender']():raise HTTPException(503,'Blender is required to update this model’s Blender companion.')
            revision=str((source/'model.glb').stat().st_mtime_ns)
            result=previous.get('result') or {}
            recipe=dict(library_root=str(root()),animation_id=data.animation_id,in_place=data.in_place,
                        result=result,settings=previous['settings'],revision=revision,
                        update_model=True,update_blend=update_blend)
            if g.get('WORKSPACE_CONFIG'):
                target=await asyncio.to_thread(g['stage_animation_operation'],source,previous,recipe,revision,True)
            else:
                target=source
                write(source/'generated-animation-request.json',recipe)
                write(source/'status.json',dict(state='queued',stage='Updating animations',progress=5,
                                                operation='animation',result=result))
            try:g['launch_worker'](target,'generated_animation_worker.py')
            except OSError as error:
                if g.get('WORKSPACE_CONFIG'):
                    write(target/'status.json',dict(state='error',stage='Unable to queue animation transfer',progress=0))
                else:
                    (source/'generated-animation-request.json').unlink(missing_ok=True)
                    write(source/'status.json',dict(state='done',stage='Model preserved',progress=100,result=result))
                raise HTTPException(503,'Unable to queue animation transfer.') from error
            response=dict(id=identifier,state='queued',status_url='/api/v1/jobs/'+identifier)
            if g.get('WORKSPACE_CONFIG'):
                response.update(operation_id=target.name,status_url='/api/v1/animation-operations/'+target.name)
            return response

    g.update(generated_animation_library=generated_animation_library,generated_animation=generated_animation,
             generate_animation=generate_animation,cancel_generated_animation=cancel_generated_animation,
             generated_animation_file=generated_animation_file,apply_generated_animation=apply_generated_animation,
             generated_animations_root=root)
