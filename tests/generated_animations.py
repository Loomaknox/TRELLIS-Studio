"""Private library persistence, queueing, same-model transfer and source validation; no inference."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import Mock, patch
import asyncio, json, socket, struct, sys, time
import numpy as np
import requests, uvicorn
from _support import isolated_workspace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import generated_animations as motions
from generated_motion import SOMA30_JOINTS
from studio_workspace import read,write

def glb(path,names=()):
    binary=struct.pack('<5f',0,0,0,0,1)
    data=dict(asset={'version':'2.0'},meshes=[{'primitives':[]}],skins=[{'joints':[0]}],nodes=[{'name':'Hips'}],
              buffers=[{'byteLength':len(binary)}],
              bufferViews=[{'buffer':0,'byteLength':4},{'buffer':0,'byteOffset':4,'byteLength':16}],
              accessors=[dict(bufferView=0,componentType=5126,type='SCALAR',count=1),
                         dict(bufferView=1,componentType=5126,type='VEC4',count=1)],
              animations=[dict(name=name,samplers=[dict(input=0,output=1)],
                               channels=[dict(sampler=0,target=dict(node=0,path='rotation'))]) for name in names])
    raw=json.dumps(data).encode();raw+=b' '*(-len(raw)%4)
    path.write_bytes(struct.pack('<4sIIII',b'glTF',2,28+len(raw)+len(binary),len(raw),0x4e4f534a)
                     +raw+struct.pack('<II',len(binary),0x004e4942)+binary)

def preview(motion,skeleton,destination,**kwargs):
    glb(destination,[kwargs['clip_name']]);return dict(preview_root='Hips')

def run():
    with isolated_workspace('generated-animations') as isolated:
        import app
        import generated_animation_worker as worker
        app.STUDIO.workspace.queue['paused']=True
        source=isolated/'source';source.mkdir()
        positions=np.zeros((75,3),np.float32);positions[:,1]=1
        rotations=np.zeros((75,30,4),np.float32);rotations[:,:,3]=1
        np.savez_compressed(source/'motion.npz',root_positions=positions,local_rotations_xyzw=rotations)
        skeleton=dict(names=list(SOMA30_JOINTS),parents=[-1,*range(29)],offsets=[[0,0,0],*([[.1,0,0]]*29)])
        write(source/'skeleton.json',skeleton)
        with patch('generated_motion.create_motion_preview',side_effect=preview):
            item=motions.import_source(app.generated_animations_root(),source,name='Saved walk',prompt='Walk forward then stop',
                seed=42,skeleton_path=source/'skeleton.json',provenance={'model':'Fixture','private_path':'must be excluded'})
        assert item['state']=='done' and item['fps']==30 and item['frames']==75
        assert 'private_path' not in item['provenance']
        saved=motions.library_path(app.generated_animations_root(),item['id'])
        assert (saved/'motion.npz').read_bytes() and (saved/'preview.glb').read_bytes()
        try:motions.library_path(app.generated_animations_root(),'../source')
        except ValueError:pass
        else:raise AssertionError('Traversal accepted')
        malformed=isolated/'malformed.npz'
        np.savez_compressed(malformed,root_positions=positions,local_rotations_xyzw=rotations*np.nan)
        try:motions.load_motion(malformed)
        except ValueError:pass
        else:raise AssertionError('Nonfinite rotations accepted')
        np.savez_compressed(malformed,root_positions=np.zeros((4_000_000,3)),local_rotations_xyzw=rotations)
        try:motions.load_motion(malformed)
        except ValueError:pass
        else:raise AssertionError('Expanded archive size accepted')
        wrong=isolated/'other-workspace';foreign=motions.create_entry(wrong,dict(prompt='Another saved motion'))
        model_id='a'*32;model=app.OUTPUT/model_id;model.mkdir()
        glb(model/'model.glb',['Existing idle','Existing walk'])
        write(model/'settings.json',dict(name='Character fixture',asset_type='rigged',animation_clips=[{'id':'idle','duration':2.5}]))
        write(model/'metadata.json',dict(display_name='Character fixture',favorite=True))
        write(model/'status.json',dict(state='done',stage='Ready',progress=100,result={'rigged':True}))
        original={p.name:p.read_bytes() for p in model.iterdir()}
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app.app,host='127.0.0.1',port=port,log_level='error'))
        thread=Thread(target=server.run,daemon=True)
        def send(method,path,code=200,**kwargs):
            result=requests.request(method,f'http://127.0.0.1:{port}'+path,timeout=10,**kwargs)
            assert result.status_code==code,(path,result.status_code,result.text[:400])
            return result
        with patch('generated_animation_api.public_status',return_value=dict(ready=True,label='Fixture',backend='CPU',experimental=True,message='Fixture')):
            thread.start()
            try:
                for _ in range(100):
                    if server.started:break
                    time.sleep(.05)
                assert server.started
                authored=send('GET','/api/animations').json()
                listed=send('GET','/api/v1/my-animations').json()
                assert len(listed['animations'])==1 and listed['animations'][0]['id']==item['id']
                assert listed['animations'][0]['preview_root']=='Hips'
                assert set(listed['animations'][0]['files'])==set(motions.SOURCE_FILES)
                assert all(url.startswith('/api/v1/') for url in listed['animations'][0]['files'].values())
                assert listed['animations'][0]['preview_url'].startswith('/api/v1/')
                send('GET','/api/my-animations/'+foreign.name,404)
                send('GET','/api/my-animations/'+item['id']+'/files/manifest.json',404)
                assert send('GET',item['preview_url']).content==(saved/'preview.glb').read_bytes()
                for bad in ({'prompt':'Walk','seed':True},{'prompt':'Walk','duration':2.25},{'prompt':'Walk\0stop'},
                            {'prompt':'Walk','executable':'arbitrary'},{'prompt':'Walk','duration':99}):
                    send('POST','/api/v1/my-animations',422,json=bad)
                created=send('POST','/api/v1/my-animations',202,json={'prompt':'Reach\nforward\tthen relax','duration':5}).json()
                assert created['state']=='queued' and created['status_url'].startswith('/api/v1/')
                assert send('GET',created['status_url']).json()['prompt']=='Reach forward then relax'
                assert send('GET',created['status_url']).json()['files']=={}
                assert app.STUDIO.job_folder(created['id']).parent==app.generated_animations_root()
                assert any(row['id']==created['id'] for row in send('GET','/api/queue').json()['items'])
                send('POST',created['status_url']+'/cancel')
                assert send('GET',created['status_url']).json()['state']=='cancelled'
                def launched(folder,script):
                    app.ACTIVE=folder.name;app.PROCESS=Mock();app.PROCESS.poll.return_value=None
                with patch.object(app,'launch_worker',side_effect=launched) as launch:
                    applied=send('POST',f'/api/v1/models/{model_id}/my-animations',202,
                                 json={'animation_id':item['id'],'in_place':True}).json()
                launch.assert_called_once_with(model,'generated_animation_worker.py')
                assert applied['id']==model_id and not applied.get('operation_id')
                assert set(app.OUTPUT.iterdir())=={model}
                request=read(model/'generated-animation-request.json')
                assert request['in_place'] is True and request['update_model'] is True
                assert read(model/'settings.json')['animation_clips']==[{'id':'idle','duration':2.5}]
                assert 'parent_id' not in read(model/'settings.json')
                assert send('GET','/api/animations').json()==authored
                assert (model/'model.glb').read_bytes()==original['model.glb']
                def append(source_glb,destination,**kwargs):
                    assert kwargs['motion_path']==saved/'motion.npz'
                    glb(destination,['Existing idle','Existing walk',kwargs['clip_name']])
                    return dict(preserved=True)
                with patch('generated_motion.append_generated_motion',side_effect=append),patch.object(worker,'generate',side_effect=AssertionError('Regeneration is forbidden')):
                    assert worker.main(model)==0
                app.ACTIVE=None;app.PROCESS=None
                assert read(model/'status.json')['state']=='done'
                assert not (model/'generated-animation-request.json').exists() and not (model/'source.glb').exists()
                assert (model/'metadata.json').read_bytes()==original['metadata.json']
                assert read(model/'settings.json')['generated_animation_clips'][0]['id']==item['id']
                assert read(model/'result.json')['animations']==3
                assert set(app.OUTPUT.iterdir())=={model}
                send('POST',f'/api/jobs/{model_id}/my-animations',409,json={'animation_id':item['id']})
            finally:
                app.ACTIVE=None;app.PROCESS=None
                server.should_exit=True;thread.join(8);assert not thread.is_alive()
        # Restart discovery uses immutable workspace entries, not in-memory sessions.
        assert motions.list_records(app.generated_animations_root())[1]['id']==item['id']
        from server_runtime import PrivateStudio,reserve_bytes
        private=PrivateStudio((isolated/'private-user').resolve(),'f'*32)
        try:
            entry=motions.create_entry(private.generated_animations,dict(prompt='Private queued motion'))
            assert private.job_folder(entry.name)==entry
            assert private.job_spec(entry)[0]=='generated_animation_worker.py'
            assert private.generated_animations in private.snapshot('/api/my-animations')
            assert reserve_bytes(read(entry/'settings.json'),'generated_animation_worker.py',entry)>=32*1024**2
        finally:asyncio.run(private.close())
    print('Generated animation persistence, validation, queue, isolation and same-model API checks passed.')

if __name__=='__main__':run()
