"""Private libraries, credits, admission rollback and real CPU same-card publication; no inference."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server_lan import serve,call,login,account,eventually,PASSWORD,MIB
from server_store import Store
from studio_workspace import read,write
import generated_animations as motions
import generated_motion as gm
import generated_animation_worker as worker
from generated_animation_updates import skeleton_fixture,fixture_target

def run():
    with TemporaryDirectory(prefix='trellis-motion-server-') as temporary:
        data=Path(temporary).resolve();store=Store(data/'server.sqlite3')
        source=data/'fixture-motion';source.mkdir();skeleton=skeleton_fixture()
        roots=np.tile([0.,1.,0.],(150,1));roots[:,2]=np.linspace(0,.25,150)
        rotations=np.zeros((150,30,4));rotations[:,:,3]=1
        np.savez(source/'motion.npz',root_positions=roots,local_rotations_xyzw=rotations)
        write(source/'skeleton.json',skeleton)
        profile=lambda name:{k:v for k,v in account(name).items() if k!='password'}
        admin=store.bootstrap_admin(profile('admin'),PASSWORD)
        users={}
        for name in ('alice','bob'):
            user=store.register(profile(name),PASSWORD)
            users[name]=store.update_user(admin['id'],user['id'],dict(status='active',credits=1,disk_limit_bytes=128*MIB,reason='Fixture'))
        write(data/'queue-control.json',dict(paused=True))
        with patch('generated_animation_api.public_status',return_value=dict(ready=True,label='Fixture',backend='CPU',experimental=True,message='Fixture')):
            with serve(data) as (base,state):
                call(base,'GET','/api/v1/my-animations',401)
                alice,_=login(base,'alice');bob,_=login(base,'bob')
                call(base,'GET','/api/my-animations',client=alice)
                workspace=state.runtime.workspaces[users['alice']['id']]
                first=call(base,'POST','/api/v1/my-animations',202,alice,json={'prompt':'Walk forward then stop'}).json()
                assert store.jobs(users['alice']['id'])[0]['credit_cost']==1
                assert store.get_user(users['alice']['id'])['credits_available']==0
                before=set(workspace.generated_animations.iterdir())
                call(base,'POST','/api/v1/my-animations',402,alice,json={'prompt':'A second walk'})
                assert set(workspace.generated_animations.iterdir())==before
                call(base,'GET',first['status_url'],404,bob)
                call(base,'POST',first['status_url']+'/cancel',404,bob)
                assert call(base,'GET','/api/my-animations',client=bob).json()['animations']==[]
                call(base,'POST',first['status_url']+'/cancel',client=alice)
                assert store.get_user(users['alice']['id'])['credits_available']==1
                assert read(workspace.job_folder(first['id'])/'status.json')['state']=='cancelled'
                second=call(base,'POST','/api/my-animations',202,alice,json={'name':'Saved motion','prompt':'Crouch then stand'}).json()
                def launch(folder,script,source_id=None):
                    assert script=='generated_animation_worker.py'
                    def preview(motion,rig,destination,*,clip_name):
                        return gm._procedural_preview(motion,rig,destination,clip_name)
                    with patch.object(gm,'create_motion_preview',side_effect=preview):
                        motions.finish_source(folder,source,skeleton,dict(model='CPU fixture'))
                workspace.launch=launch
                state.runtime.set_paused(False)
                eventually(lambda:next(row for row in store.jobs(users['alice']['id']) if row['id']==second['id'])['state']=='done')
                assert store.get_user(users['alice']['id'])['credits']==0
                assert len([row for row in store.user_ledger(users['alice']['id']) if row['delta']==-1])==1
                state.runtime.set_paused(True)
                identifier='a'*32;model=workspace.outputs/identifier;model.mkdir()
                fixture_target(model/'model.glb',skeleton,shared_skins=3)
                original=(model/'model.glb').read_bytes()
                original_descriptor,original_binary=gm.read(model/'model.glb')
                (model/'LODs').mkdir();(model/'LODs'/'LOD0.glb').write_bytes(original)
                write(model/'settings.json',dict(name='Rig fixture',asset_type='rigged'))
                write(model/'metadata.json',dict(display_name='Rig fixture'))
                write(model/'status.json',dict(state='done',stage='Ready',progress=100))
                applied=call(base,'POST',f'/api/v1/models/{identifier}/my-animations',202,alice,
                             json={'animation_id':second['id']}).json()
                assert applied['id']==identifier and applied['operation_id']!=identifier
                operation=workspace.animation_operations/applied['operation_id']
                assert operation.is_dir() and set(workspace.outputs.iterdir())=={model}
                assert workspace.job_spec(operation)[0]=='generated_animation_worker.py'
                recipe=read(operation/'generated-animation-request.json')
                assert recipe['update_model'] and recipe['defer_publish']
                assert next(row for row in store.jobs(users['alice']['id']) if row['id']==applied['operation_id'])['credit_cost']==0
                assert (model/'model.glb').read_bytes()==original
                call(base,'GET',applied['status_url'],404,bob)
                call(base,'POST',f'/api/v1/models/{identifier}/my-animations',409,alice,json={'animation_id':second['id']})
                assert any(row['id']==second['id'] for row in call(base,'GET','/api/my-animations',client=alice).json()['animations'])
                store.update_user(admin['id'],users['bob']['id'],dict(disk_limit_bytes=0))
                call(base,'POST','/api/my-animations',413,bob,json={'prompt':'Quota fixture'})
                assert not list(state.runtime.workspaces[users['bob']['id']].generated_animations.glob('*'))
                call(base,'POST',applied['status_url']+'/cancel',client=alice)
                assert store.get_user(users['alice']['id'])['credits']==0
                assert (model/'model.glb').read_bytes()==original
                assert read(model/'status.json')['state']=='done'
                assert set(workspace.outputs.iterdir())=={model}
                # Actual CPU retarget and deferred publication reuse this card without spending credits.
                def transfer(folder,script,source_id=None):
                    assert script=='generated_animation_worker.py'
                    assert worker.main(folder)==0
                workspace.launch=transfer
                third=motions.import_source(workspace.generated_animations,source,name='Second saved motion',
                    prompt='Walk forward',seed=43,skeleton_path=source/'skeleton.json',provenance={'model':'CPU fixture'})
                operations_before=set(workspace.animation_operations.iterdir())
                store.update_user(admin['id'],users['alice']['id'],dict(disk_limit_bytes=0))
                call(base,'POST',f'/api/v1/models/{identifier}/my-animations',413,alice,
                    json={'animation_id':third['id']})
                assert set(workspace.animation_operations.iterdir())==operations_before
                assert (model/'model.glb').read_bytes()==original
                store.update_user(admin['id'],users['alice']['id'],dict(disk_limit_bytes=128*MIB))
                for index,motion_id in enumerate((second['id'],third['id'])):
                    applied=call(base,'POST',f'/api/v1/models/{identifier}/my-animations',202,alice,
                        json={'animation_id':motion_id}).json()
                    assert applied['id']==identifier and applied['operation_id']!=identifier
                    state.runtime.set_paused(False)
                    eventually(lambda:next(row for row in store.jobs(users['alice']['id'])
                        if row['id']==applied['operation_id'])['state']=='done')
                    state.runtime.set_paused(True)
                    assert call(base,'GET',applied['status_url'],client=alice).json()['state']=='done'
                    assert set(workspace.outputs.iterdir())=={model}
                    assert store.get_user(users['alice']['id'])['credits']==0
                    assert read(model/'status.json')['state']=='done'
                    for path in (model/'model.glb',model/'LODs'/'LOD0.glb'):
                        descriptor,binary=gm.read(path)
                        assert len(descriptor['animations'])==index+2
                        assert binary[:len(original_binary)]==original_binary
                        assert descriptor['animations'][0]==original_descriptor['animations'][0]
                    operation=workspace.animation_operations/applied['operation_id']
                    assert {p.name for p in operation.iterdir()}<={'operation.json','status.json','generation.log'}
                call(base,'POST',f'/api/v1/models/{identifier}/my-animations',409,alice,
                    json={'animation_id':second['id']})
                assert len([row for row in store.user_ledger(users['alice']['id']) if row['delta']==-1])==1
            with serve(data) as (base,state):
                alice,_=login(base,'alice')
                records=call(base,'GET','/api/v1/my-animations',client=alice).json()['animations']
                assert any(row['id']==second['id'] and row['state']=='done' for row in records)
    print('Generated animation Server auth, isolation, credits, quota rollback, queue and restart checks passed.')

if __name__=='__main__':run()
