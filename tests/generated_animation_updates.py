"""Real CPU motion appends and atomic same-card failure/cancellation regressions."""
from pathlib import Path
from unittest.mock import Mock, patch
import asyncio
import contextlib
import io
import os
import sys

import numpy as np
from _support import isolated_workspace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import generated_motion as gm
import generated_animations as library
import generated_animation_worker as worker
import animation_edits
from api_contract import GeneratedAnimationApply
from fastapi import HTTPException
from studio_workspace import read,write


def skeleton_fixture():
    names=list(gm.SOMA30_JOINTS)
    offsets=np.zeros((30,3))
    for name,y in [('Spine1',.08),('Spine2',.10),('Chest',.10),('Neck1',.20),('Neck2',.06),('Head',.06)]:
        offsets[names.index(name)]=[0,y,0]
    offsets[7]=[0,-.03,.05];offsets[8]=[.03,.04,.05];offsets[9]=[-.03,.04,.05]
    for side,sign in [('Left',1),('Right',-1)]:
        for part,value in {'Shoulder':[sign*.08,.15,0],'Arm':[sign*.14,0,0],'ForeArm':[sign*.30,0,0],
                'Hand':[sign*.28,0,0],'HandThumbEnd':[sign*.10,-.02,.04],'HandMiddleEnd':[sign*.18,0,0],
                'Leg':[sign*.10,-.10,0],'Shin':[0,-.45,0],'Foot':[0,-.40,0],'ToeBase':[0,-.05,.15]}.items():
            offsets[names.index(side+part)]=value
    return dict(names=names,parents=list(gm.SOMA30_PARENTS),offsets=offsets.tolist(),up='Y',units='metres',fps=30)


def fixture_target(path,skeleton,*,prefix='joint_',scale=1.,shared_skins=1):
    canonical=skeleton['names'];parents=skeleton['parents'];offsets=np.asarray(skeleton['offsets'])
    neutral=np.zeros((30,3))
    for i,p in enumerate(parents):
        if p>=0:neutral[i]=neutral[p]+offsets[i]
    neutral[:,1]+=1
    names=[name for name in canonical if name in gm.SOMA_TO_SEMANTIC]
    indices={name:i for i,name in enumerate(names)};nodes=[]
    for name in names:
        i=canonical.index(name);parent=parents[i]
        while parent>=0 and canonical[parent] not in indices:parent=parents[parent]
        position=neutral[i] if parent<0 else neutral[i]-neutral[parent]
        nodes.append({'name':prefix+str(indices[name]),'translation':position.tolist()})
        if parent>=0:nodes[indices[canonical[parent]]].setdefault('children',[]).append(indices[name])
    root_node=len(nodes)+shared_skins
    nodes.extend({'name':'mesh_'+str(i),'mesh':0,'skin':i} for i in range(shared_skins))
    nodes.append({'name':'scene_root','scale':[scale]*3,'children':[0,*range(len(names),len(names)+shared_skins)]})
    data={'asset':{'version':'2.0'},'scene':0,'scenes':[{'nodes':[root_node]}],'nodes':nodes,
          'buffers':[{'byteLength':0}],'bufferViews':[],'accessors':[],
          'materials':[{'name':'Keep material','pbrMetallicRoughness':{'baseColorFactor':[.2,.4,.6,1]}}]}
    binary=bytearray()
    position=np.array([[-.8,0,0],[.8,0,0],[0,1.8,.1]],dtype='<f4')
    attrs={'POSITION':gm.append_access(data,binary,position,'VEC3'),
           'NORMAL':gm.append_access(data,binary,np.tile([0,0,1],(3,1)),'VEC3'),
           'TEXCOORD_0':gm.append_access(data,binary,[[0,0],[1,0],[.5,1]],'VEC2'),
           'WEIGHTS_0':gm.append_access(data,binary,np.tile([1,0,0,0],(3,1)),'VEC4')}
    start=len(binary);binary.extend(np.zeros((3,4),dtype='<u2').tobytes());view=len(data['bufferViews'])
    data['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':24})
    attrs['JOINTS_0']=len(data['accessors']);data['accessors'].append({'bufferView':view,'componentType':5123,'count':3,'type':'VEC4'})
    data['meshes']=[{'name':'Keep geometry','primitives':[{'attributes':attrs,'material':0}]}]
    bind=np.tile(np.eye(4),(len(names),1,1));bind[:,:3,3]=-np.array([neutral[canonical.index(name)] for name in names])
    inverse=gm.append_access(data,binary,bind.transpose(0,2,1).reshape(len(names),16),'MAT4')
    data['skins']=[{'name':'shared_'+str(i),'joints':list(range(len(names))),'inverseBindMatrices':inverse} for i in range(shared_skins)]
    # Preserve opaque binary data too, such as embedded image bytes and padding.
    binary.extend(b'\0'*(-len(binary)%4));start=len(binary);payload=b'original embedded texture bytes'
    binary.extend(payload);view=len(data['bufferViews']);data['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':len(payload)})
    data['images']=[{'bufferView':view,'mimeType':'image/png','name':'Keep image'}]
    data['textures']=[{'source':0}]
    gm.append_clip(data,binary,'Existing clip',np.array([0,1],dtype=np.float32),
                   {0:np.array([[0,0,0,1],[0,0,0,1]],dtype=np.float32)},np.tile(neutral[0],(2,1)),0,{'keep':True})
    gm.write_glb(path,data,binary)


def snapshot(folder):
    return {str(p.relative_to(folder)):p.read_bytes() for p in folder.rglob('*')
            if p.is_file() and p.name not in ('status.json','generated-animation-request.json')}


def run():
    with isolated_workspace('same-card-motion') as private:
        import app
        app.STUDIO.workspace.queue['paused']=True
        skeleton=skeleton_fixture();source=private/'canonical';source.mkdir()
        roots=np.tile([0.,1.,0.],(60,1));roots[:,2]=np.linspace(0,.25,60)
        rotations=np.zeros((60,30,4));rotations[:,:,3]=1
        np.savez(source/'motion.npz',root_positions=roots,local_rotations_xyzw=rotations)
        write(source/'skeleton.json',skeleton)
        def preview(motion,rig,destination,*,clip_name):
            return gm._procedural_preview(motion,rig,destination,clip_name)
        with patch.object(gm,'create_motion_preview',side_effect=preview):
            motions=[library.import_source(app.generated_animations_root(),source,name=name,prompt='Walk forward',
                     seed=seed,skeleton_path=source/'skeleton.json',provenance={'model':'CPU fixture'})
                     for name,seed in [('First saved motion',42),('Second saved motion',43)]]
        canonical=snapshot(app.generated_animations_root())
        model=app.OUTPUT/('a'*32);model.mkdir();(model/'LODs').mkdir()
        fixture_target(model/'model.glb',skeleton,shared_skins=3)
        original_glb=(model/'model.glb').read_bytes()
        for name in ('LOD0.glb','LOD1.glb'):(model/'LODs'/name).write_bytes(original_glb)
        settings=dict(name='Existing character',asset_type='rigged',animation_clips=[{'id':'authored','duration':2}],
                      lods={'enabled':True},custom_setting='preserve')
        metadata=dict(display_name='Keep this card',favorite=True,folder_id='existing-folder',review_status='approved')
        result=dict(rigged=True,animations=1,revision=123,custom_result='preserve')
        write(model/'settings.json',settings);write(model/'metadata.json',metadata);write(model/'result.json',result)
        write(model/'status.json',dict(state='done',stage='Ready',progress=100,result=result))
        original=snapshot(model)
        before,binary=gm.read(model/'model.glb')

        def queue(index=0):
            with patch.object(app,'launch_worker') as launch:
                response=asyncio.run(app.apply_generated_animation(model.name,
                    GeneratedAnimationApply(animation_id=motions[index]['id'])))
            launch.assert_called_once_with(model,'generated_animation_worker.py')
            assert response['id']==model.name and not response.get('operation_id')
            assert set(app.OUTPUT.iterdir())=={model}
            assert read(model/'status.json')['operation']=='animation'
            return response

        def reset():
            assert not (model/'animation-transaction.json').exists()
            for relative,payload in original.items():(model/relative).write_bytes(payload)
            (model/'model.blend').unlink(missing_ok=True)
            (model/'generated-animation-request.json').unlink(missing_ok=True)
            write(model/'status.json',dict(state='done',stage='Ready',progress=100,result=result))
            assert not list(model.glob('.generated-transfer-*')) and not list(model.glob('.animation-*'))

        def fail_preserved(callback):
            with contextlib.redirect_stderr(io.StringIO()):assert callback()==1
            assert snapshot(model)==original
            state=read(model/'status.json')
            assert state['state']=='done' and state['operation_error']
            assert not (model/'generated-animation-request.json').exists()
            assert set(app.OUTPUT.iterdir())=={model}

        # Two successful operations reuse sources, append every LOD, and keep the original card/asset data.
        with patch.object(worker,'generate',side_effect=AssertionError('No inference during source reuse')):
            for index in range(2):
                queue(index);assert worker.main(model)==0
                state=read(model/'status.json');current=read(model/'result.json')
                assert state['state']=='done' and not state.get('operation_error')
                assert current==state['result'] and current['animations']==index+2
                assert current['revision']!=123
                for path in [model/'model.glb',*sorted((model/'LODs').glob('*.glb'))]:
                    descriptor,payload=gm.read(path)
                    assert len(descriptor['animations'])==index+2
                    assert descriptor['animations'][0]==before['animations'][0]
                    assert payload[:len(binary)]==binary
                    for key in ('meshes','skins','nodes','materials','images','textures'):
                        assert descriptor.get(key)==before.get(key)
                assert read(model/'metadata.json')==metadata
                assert read(model/'settings.json')['animation_clips']==settings['animation_clips']
            assert len(read(model/'settings.json')['generated_animation_clips'])==2
            try:queue(0)
            except HTTPException as error:assert error.status_code==409
            else:raise AssertionError('Duplicate saved animation was accepted')
        assert snapshot(app.generated_animations_root())==canonical
        assert set(app.OUTPUT.iterdir())=={model}

        # An error on the second LOD cannot leak the already-produced main model / first LOD.
        reset();queue();append=gm.append_generated_motion
        def broken_lod(source_glb,destination,**options):
            if source_glb.name=='LOD1.glb':raise ValueError('Fixture LOD cannot be transferred')
            return append(source_glb,destination,**options)
        with patch.object(gm,'append_generated_motion',side_effect=broken_lod):fail_preserved(lambda:worker.main(model))

        # Optimistic revision checking refuses publication when the source changes during retargeting.
        reset();queue()
        def concurrent_revision(source_glb,destination,**options):
            value=append(source_glb,destination,**options)
            if source_glb==model/'model.glb':
                stamp=source_glb.stat();os.utime(source_glb,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+1_000_000))
            return value
        with patch.object(gm,'append_generated_motion',side_effect=concurrent_revision):fail_preserved(lambda:worker.main(model))
        assert 'changed' in read(model/'status.json')['operation_error']

        # Failure during the actual commit rolls back every replaced file, including shared LODs.
        reset();queue();replace=animation_edits.replace_file;failed=False
        def fail_commit(source_file,destination):
            nonlocal failed
            if destination==model/'LODs'/'LOD1.glb' and not failed:
                failed=True;raise OSError('Fixture replacement failure')
            return replace(source_file,destination)
        with patch.object(animation_edits,'replace_file',side_effect=fail_commit):fail_preserved(lambda:worker.main(model))
        assert failed

        # An existing Blender companion is mandatory to refresh, never silently discarded.
        reset();(model/'model.blend').write_bytes(b'Existing Blender companion')
        with patch.object(app,'find_blender',return_value=Path('fixture-blender')):queue()
        protected=snapshot(model)
        with patch('studio_import.find_blender',return_value=None),contextlib.redirect_stderr(io.StringIO()):
            assert worker.main(model)==1
        assert snapshot(model)==protected and read(model/'status.json')['operation_error']

        # Historical generation-queue entries must not divert cancellation away from the running edit.
        reset();app.STUDIO.workspace.enqueue(model.name);queue();process=Mock();process.poll.return_value=None
        with patch.object(app,'ACTIVE',model.name),patch.object(app,'PROCESS',process),patch.object(app,'stop_worker') as stop:
            asyncio.run(app.cancel(model.name));stop.assert_called_once_with()
        assert snapshot(model)==original
        assert read(model/'status.json')['state']=='done'
        assert 'cancelled' in read(model/'status.json')['operation_error'].lower()
        assert not (model/'generated-animation-request.json').exists()
        assert app.STUDIO.workspace.pending(model.name)

        # A best-effort cleanup failure after a successful commit must not claim the old model survived.
        reset();queue();unlink=Path.unlink;injected=False
        def fail_cleanup(path,*args,**kwargs):
            nonlocal injected
            if path==model/'generated-animation-request.json' and not injected:
                injected=True;raise PermissionError('Fixture post-commit cleanup is temporarily blocked')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail_cleanup):assert worker.main(model)==0
        assert injected
        state=read(model/'status.json')
        assert state['state']=='done' and not state.get('operation_error')
        assert state['result']==read(model/'result.json') and state['result']['animations']==2

        # Windows readers can temporarily hold a staging file open after the commit.
        if os.name=='nt':
            reset();queue();held=[]
            def hold_stage_file(source_glb,destination,**options):
                value=append(source_glb,destination,**options)
                if not held:
                    handle=(destination.parent/'temporary-reader.bin').open('w+b')
                    handle.write(b'Temporary reader');handle.flush();held.append(handle)
                return value
            try:
                with patch.object(gm,'append_generated_motion',side_effect=hold_stage_file):
                    assert worker.main(model)==0
                state=read(model/'status.json')
                assert state['state']=='done' and not state.get('operation_error')
                assert state['result']==read(model/'result.json') and state['result']['animations']==2
                assert held and list(model.glob('.generated-transfer-*'))
            finally:
                for handle in held:handle.close()
        assert snapshot(app.generated_animations_root())==canonical
        assert set(app.OUTPUT.iterdir())=={model}
    print('Same-card real CPU transactions passed: repeated reuse, binary/LOD preservation, duplicates, revision conflicts, rollback, Blender companion, cancellation and post-commit cleanup.')


if __name__=='__main__':run()
