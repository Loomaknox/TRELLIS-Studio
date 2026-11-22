"""CPU regression checks for reusable motion and immutable target assets."""
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import hashlib
import json
import sys
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import generated_motion as gm


def fixture_skeleton():
    names=list(gm.SOMA30_JOINTS)
    parents=[-1,0,1,2,3,4,5,6,6,6,3,10,11,12,13,13,3,16,17,18,19,19,0,22,23,24,0,26,27,28]
    offsets=np.zeros((30,3))
    for name,y in [('Spine1',.08),('Spine2',.10),('Chest',.10),('Neck1',.20),('Neck2',.06),('Head',.06)]:
        offsets[names.index(name)]=[0,y,0]
    offsets[7]=[0,-.03,.05];offsets[8]=[.03,.04,.05];offsets[9]=[-.03,.04,.05]
    for side,sign in [('Left',1),('Right',-1)]:
        values={'Shoulder':[sign*.08,.15,0],'Arm':[sign*.14,0,0],'ForeArm':[sign*.30,0,0],
                'Hand':[sign*.28,0,0],'HandThumbEnd':[sign*.10,-.02,.04],'HandMiddleEnd':[sign*.18,0,0],
                'Leg':[sign*.10,-.10,0],'Shin':[0,-.45,0],'Foot':[0,-.40,0],'ToeBase':[0,-.05,.15]}
        for part,value in values.items():offsets[names.index(side+part)]=value
    return {'name':'somaskel30','names':names,'parents':parents,'offsets':offsets.tolist(),'up':'Y','units':'metres','fps':30}


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


def reject(callback,match):
    try:callback()
    except ValueError as error:
        assert match.lower() in str(error).lower(),str(error)
    else:raise AssertionError('Expected a validation error: '+match)


# The CPU helper matches Blender's local delta in arbitrary rest orientations,
# and unwraps the wrist across 180 degrees without making the helper snap.
rest_rot={i:gm.Rotation.random(random_state=i+10).as_matrix() for i in range(3)}
axis=gm.normalize(np.array([.75,.22,.44]));rest={i:np.eye(4) for i in range(3)}
rest[1][:3,3]=axis;rest[2][:3,3]=axis*.5
forearm_pose=gm.Rotation.random(random_state=42).as_matrix()
for sign in (-1,1):
    previous={}
    for degrees in (170,179,181,190):
        delta=gm.Rotation.from_rotvec(rest_rot[1].T@axis*np.deg2rad(sign*degrees)).as_matrix()
        desired={0:forearm_pose,1:forearm_pose@rest_rot[0].T@rest_rot[1]@delta}
        gm.drive_advanced_twists(desired,{'left':(2,0,1)},rest,rest_rot,previous)
        expected=forearm_pose@rest_rot[0].T@rest_rot[2]@gm.Rotation.from_rotvec(rest_rot[2].T@axis*np.deg2rad(sign*degrees*.5)).as_matrix()
        assert np.max(abs(desired[2]-expected))<1e-8


with TemporaryDirectory(prefix='trellis-generated-motion-') as directory:
    folder=Path(directory);skeleton=fixture_skeleton();motion=folder/'motion.npz'
    rotations=np.zeros((31,30,4));rotations[:,:,3]=1
    roots=np.tile([0.,1.,0.],(31,1));roots[:,2]=np.linspace(0,.3,31)
    np.savez(motion,root_positions=roots,local_rotations_xyzw=rotations)
    motion_hash=gm.sha(motion)
    target=folder/'target.glb';fixture_target(target,skeleton,shared_skins=3)
    source_hash=gm.sha(target);before,old_binary=gm.read(target)
    output=folder/'result.glb'
    report=gm.append_generated_motion(target,output,motion_path=motion,skeleton=skeleton,
             clip_name='Generated one',provenance={'engine':'Kimodo','seed':42,'private_path':'must not be embedded'})
    after,new_binary=gm.read(output)
    assert len(after['animations'])==2
    assert new_binary[:len(old_binary)]==old_binary
    assert all(report['preservation']['unchanged_asset_descriptors'].values())
    assert all(report['preservation']['unchanged_prior_entries'].values())
    assert 'private_path' not in json.dumps(after['animations'][-1])
    assert after['animations'][-1]['extras']['generated'] is True
    assert report['quaternion_checks']['target_hemisphere_continuous']
    assert report['quaternion_checks']['target_max_norm_error']<1e-6
    times=gm.accessor(after,new_binary,after['animations'][-1]['samplers'][0]['input']).ravel()
    assert len(times)==31 and abs(times[-1]-1)<1e-6 and np.max(abs(np.diff(times)-1/30))<1e-6
    assert gm.sha(target)==source_hash and gm.sha(motion)==motion_hash
    assert report['root_path_length_m']>.29

    # Reuse the exact same source motion on a differently named/scaled rig.
    second=folder/'second.glb';fixture_target(second,skeleton,prefix='different_',scale=1.2)
    other=gm.append_generated_motion(second,folder/'other.glb',motion_path=motion,skeleton=skeleton,
                                    clip_name='Generated again',in_place=True)
    assert other['leg_scale']>report['leg_scale']*1.19
    assert abs(other['root_displacement_m'][0])+abs(other['root_displacement_m'][2])<1e-8
    assert gm.sha(motion)==motion_hash

    reject(lambda:gm.append_generated_motion(target,target,motion_path=motion,skeleton=skeleton,clip_name='Unsafe'),'separate')
    reject(lambda:gm.append_generated_motion(output,folder/'duplicate.glb',motion_path=motion,skeleton=skeleton,clip_name='Generated one'),'already')
    reject(lambda:gm.append_generated_motion(target,folder/'bad-map.glb',motion_path=motion,skeleton=skeleton,
           clip_name='Invalid',target_mapping={'left_arm':'joint_0'}),'mapping')
    reject(lambda:gm.append_generated_motion(target,folder/'bad-fps.glb',motion_path=motion,skeleton=dict(skeleton,fps=24),clip_name='Wrong fps'),'30 fps')
    wrong_soma=copy.deepcopy(skeleton);wrong_soma['parents'][13]=6
    reject(lambda:gm.validate_skeleton(wrong_soma),'canonical SOMA30 hierarchy')
    reject(lambda:gm.gltf_rig({'nodes':[{'children':[1]},{'children':[0]}]}),'cyclic')
    for scale,expected in [([-1,1,1],'Negative'),([0,0,0],'zero'),([1,2,1],'Nonuniform')]:
        reject(lambda scale=scale:gm.gltf_rig({'nodes':[{'scale':scale}]}),expected)
    gm.gltf_rig({'nodes':[{'scale':[1.0000282526,.9999997616,1.0000082254]}]})
    reject(lambda:gm.gltf_rig({'nodes':[{'scale':[1.001,1,1]}]}),'Nonuniform')
    shear=np.eye(4);shear[0,1]=shear[1,0]=.2;shear[2,2]=np.sqrt(1.04)
    reject(lambda:gm.gltf_rig({'nodes':[{'matrix':shear.T.reshape(-1).tolist()}]}),'sheared')
    reflection=np.diag([-1.,1.,1.,1.])
    reject(lambda:gm.gltf_rig({'nodes':[{'matrix':reflection.T.reshape(-1).tolist()}]}),'Reflected')
    broken=copy.deepcopy(before);broken['nodes'][0]['children'].append(0)
    gm.write_glb(folder/'cyclic.glb',broken,old_binary)
    reject(lambda:gm.append_generated_motion(folder/'cyclic.glb',folder/'bad-rig.glb',motion_path=motion,skeleton=skeleton,clip_name='Invalid'),'hierarchy')
    no_rig=copy.deepcopy(before);no_rig.pop('skins')
    for node in no_rig['nodes']:node.pop('skin',None)
    gm.write_glb(folder/'static.glb',no_rig,old_binary)
    reject(lambda:gm.append_generated_motion(folder/'static.glb',folder/'bad-static.glb',motion_path=motion,skeleton=skeleton,clip_name='Invalid'),'Rig the character')
    malformed=rotations.copy();malformed[10,0]=0
    np.savez(folder/'malformed.npz',root_positions=roots,local_rotations_xyzw=malformed)
    reject(lambda:gm.append_generated_motion(target,folder/'bad-motion.glb',motion_path=folder/'malformed.npz',skeleton=skeleton,clip_name='Invalid'),'normalized')
    assert gm.sha(target)==source_hash
    assert not (folder/'bad-map.glb').exists() and not (folder/'bad-motion.glb').exists()

    # Advanced helpers are driven for Kimodo as well as authored motions.
    advanced=copy.deepcopy(before);advanced_binary=bytearray(old_binary)
    mapping,_=gm.resolve_target_mapping(advanced,advanced_binary)
    saved={gm.SOMA_TO_SEMANTIC[source]:advanced['nodes'][node]['name'] for source,node in mapping.items()}
    helpers={}
    for source,side in [('Left','left'),('Right','right')]:
        forearm,hand=mapping[source+'ForeArm'],mapping[source+'Hand']
        helper=len(advanced['nodes']);name=advanced['nodes'][forearm]['name']+'_StudioTwist'
        advanced['nodes'].append({'name':name,'translation':(np.asarray(advanced['nodes'][hand]['translation'])*.5).tolist()})
        advanced['nodes'][forearm]['children'].append(helper)
        saved[side+'_forearm_twist']=name;helpers[side]=helper
    _,_,world,_,_=gm.gltf_rig(advanced)
    for skin in advanced['skins']:
        skin['joints'].extend(helpers.values())
        binds=np.array([np.linalg.inv(world[node]) for node in skin['joints']])
        skin['inverseBindMatrices']=gm.append_access(advanced,advanced_binary,binds.transpose(0,2,1).reshape(-1,16),'MAT4')
    advanced_path=folder/'advanced.glb';gm.write_glb(advanced_path,advanced,advanced_binary)
    wrist=rotations.copy()
    for side in ('Left','Right'):
        wrist[:,skeleton['names'].index(side+'Hand')]=gm.Rotation.from_rotvec([np.pi/2,0,0]).as_quat()
    wrist_path=folder/'wrist.npz';np.savez(wrist_path,root_positions=roots,local_rotations_xyzw=wrist)
    for label,target_map in [('saved',saved),('imported',None)]:
        driven_path=folder/('advanced-'+label+'.glb')
        driven=gm.append_generated_motion(advanced_path,driven_path,motion_path=wrist_path,skeleton=skeleton,
                                         clip_name='Advanced wrist',target_mapping=target_map)
        assert set(driven['forearm_helpers']['nodes'])=={'left','right'}
        descriptor,payload=gm.read(driven_path);clip=descriptor['animations'][-1]
        gm.verify_preservation(advanced,advanced_binary,descriptor,payload)
        for helper in helpers.values():
            channel=next(c for c in clip['channels'] if c['target']=={'node':helper,'path':'rotation'})
            values=gm.accessor(descriptor,payload,clip['samplers'][channel['sampler']]['output'])
            expected=gm.Rotation.from_rotvec([np.pi/4,0,0]).as_quat()
            assert np.min(abs(values@expected))>1-1e-6
    invalid=copy.deepcopy(advanced);invalid['nodes'][helpers['left']]['translation']=[0,0,0]
    gm.write_glb(folder/'invalid-helper.glb',invalid,advanced_binary)
    reject(lambda:gm.append_generated_motion(folder/'invalid-helper.glb',folder/'bad-helper.glb',motion_path=wrist_path,
           skeleton=skeleton,clip_name='Invalid helper',target_mapping=saved),'forearm helper')
    assert not (folder/'bad-helper.glb').exists()

    preview=folder/'preview.glb'
    metadata=gm._procedural_preview(motion,skeleton,preview,'Generated preview')
    descriptor,payload=gm.read(preview)
    assert descriptor['skins'] and descriptor['meshes'] and len(descriptor['animations'])==1
    assert descriptor['animations'][0]['name']=='Generated preview' and metadata['preview_root']=='Hips'
    with patch.object(gm.Path,'is_file',return_value=True), patch.object(gm,'append_generated_motion',side_effect=ValueError('Incompatible installed preview rig')):
        fallback=gm.create_motion_preview(motion,skeleton,folder/'fallback.glb',clip_name='Fallback preview')
    assert fallback['preview_source']=='Procedural mannequin'
    assert fallback['preview_fallback']=='installed_mannequin_unavailable'
    assert gm.read(folder/'fallback.glb')[0]['animations'][0]['name']=='Fallback preview'
    assert not any(path.name.startswith('.generated-motion-') for path in folder.iterdir())

print('Generated motion checks passed: reuse, shared skins, preservation, timing, provenance, canonical hierarchy, transform rejection, Advanced helpers/continuity and preview fallback.')
