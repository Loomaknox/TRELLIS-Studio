"""Reusable humanoid motion transfer with append-only glTF asset preservation.

Generated motion stays independent of target meshes. Ambiguous or incompatible
skeletons are rejected; this is not an autorigger or a foot-contact solver.
"""
from pathlib import Path
import copy
import hashlib
import json
import logging
import math
import os
import struct
import tempfile
import zipfile

import numpy as np
from scipy.spatial.transform import Rotation

from glb_data import read, accessor, animation_info, posed_bounds
from humanoid_mapping import infer_positions

SOMA_TO_SEMANTIC = {
    'Hips':'root', 'Spine1':'spine_1', 'Spine2':'spine_2', 'Chest':'spine',
    'Neck2':'neck', 'Head':'head',
    **{side+part:label+'_'+semantic for side,label in [('Left','left'),('Right','right')]
       for part,semantic in [('Shoulder','clavicle'),('Arm','arm'),('ForeArm','forearm'),
                             ('Hand','hand'),('Leg','leg'),('Shin','shin'),('Foot','foot'),('ToeBase','toe')]},
}
ALIGN_PAIRS = [(side+a,side+b) for side in ('Left','Right')
               for a,b in [('Arm','ForeArm'),('ForeArm','Hand'),('Leg','Shin'),('Shin','Foot')]]
PROVENANCE_FIELDS = {'engine','model','runtime','model_sha256','text_encoder_sha256',
                     'source_revision','seed','prompt','duration','fps','steps','guidance','animation_id'}
SOMA30_JOINTS = ('Hips','Spine1','Spine2','Chest','Neck1','Neck2','Head','Jaw','LeftEye','RightEye',
                'LeftShoulder','LeftArm','LeftForeArm','LeftHand','LeftHandThumbEnd','LeftHandMiddleEnd',
                'RightShoulder','RightArm','RightForeArm','RightHand','RightHandThumbEnd','RightHandMiddleEnd',
                'LeftLeg','LeftShin','LeftFoot','LeftToeBase','RightLeg','RightShin','RightFoot','RightToeBase')
SOMA30_PARENTS = (-1,0,1,2,3,4,5,6,6,6,3,10,11,12,13,13,3,16,17,18,19,19,0,22,23,24,0,26,27,28)

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize(v):
    return v / max(float(np.linalg.norm(v)), 1e-12)


def swing(a,b):
    a,b = normalize(a),normalize(b)
    c = np.cross(a,b); d = float(np.clip(a@b,-1,1))
    if d < -.999999:
        axis = normalize(np.cross(a, [1,0,0] if abs(a[0])<.8 else [0,1,0]))
        return Rotation.from_rotvec(axis*np.pi).as_matrix()
    q = np.r_[c,1+d]
    return Rotation.from_quat(q/np.linalg.norm(q)).as_matrix()


def local_matrix(node):
    if 'matrix' in node: return np.array(node['matrix'],dtype=float).reshape(4,4).T
    m=np.eye(4)
    m[:3,:3]=Rotation.from_quat(node.get('rotation',[0,0,0,1])).as_matrix()@np.diag(node.get('scale',[1,1,1]))
    m[:3,3]=node.get('translation',[0,0,0])
    return m


def gltf_rig(data):
    _validate_hierarchy(data)
    parents={c:i for i,n in enumerate(data['nodes']) for c in n.get('children',[])}
    for node in data['nodes']:
        scale=np.asarray(node.get('scale',[1,1,1]),dtype=float)
        if scale.shape!=(3,) or not np.isfinite(scale).all() or np.min(scale)<=0:
            raise ValueError('Negative or zero target scale is not supported. Apply the model transforms before transferring animation.')
    try:local=[local_matrix(n) for n in data['nodes']]
    except (ValueError,TypeError):raise ValueError('The target contains an invalid rest transform.') from None

    def validate_transform(matrix):
        if not np.isfinite(matrix).all() or np.max(abs(matrix[3]-[0,0,0,1]))>1e-8:
            raise ValueError('The target contains an invalid affine transform.')
        scales=np.linalg.norm(matrix[:3,:3],axis=0)
        if np.min(scales)<1e-8:
            raise ValueError('Zero target scale is not supported.')
        if scales.max()-scales.min()>scales.max()*1e-4:
            raise ValueError('Nonuniform target scale is not supported. Apply the model transforms before transferring animation.')
        rotation=matrix[:3,:3]/scales
        if np.linalg.det(rotation)<.99999 or np.max(abs(rotation.T@rotation-np.eye(3)))>1e-5:
            raise ValueError('Reflected or sheared target transforms are not supported. Apply the model transforms first.')

    for matrix in local:validate_transform(matrix)
    world={}
    def calc(i):
        if i not in world: world[i]=calc(parents[i])@local[i] if i in parents else local[i]
        return world[i]
    for i in range(len(local)):calc(i)
    order=sorted(range(len(local)),key=lambda i:depth(i,parents))
    for matrix in world.values():validate_transform(matrix)
    rotations={i:world[i][:3,:3]/np.linalg.norm(world[i][:3,:3],axis=0) for i in world}
    return parents,local,world,rotations,order


def depth(i,parents):
    return 0 if i not in parents else 1+depth(parents[i],parents)


def source_fk(names,parents,offsets,quats,roots):
    rotations=Rotation.from_quat(quats.reshape(-1,4)).as_matrix().reshape(*quats.shape[:-1],3,3)
    g=np.zeros_like(rotations);p=np.zeros((*quats.shape[:-1],3))
    for j,parent in enumerate(parents):
        if parent<0:g[:,j]=rotations[:,j];p[:,j]=roots
        else:
            g[:,j]=g[:,parent]@rotations[:,j]
            p[:,j]=p[:,parent]+np.einsum('tij,j->ti',g[:,parent],offsets[j])
    neutral=np.zeros((len(names),3))
    for j,parent in enumerate(parents):
        if parent>=0:neutral[j]=neutral[parent]+offsets[j]
    return g,p,neutral


def load_motion(folder,skeleton):
    path=Path(folder); joints=len(skeleton['names'])
    if not path.is_file() or path.suffix.lower()!='.npz' or path.stat().st_size>16*1024*1024:
        raise ValueError('A bounded canonical NPZ motion file is required.')
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist())>32*1024*1024:
            raise ValueError('The motion archive is too large.')
    with np.load(path,allow_pickle=False) as npz:
        roots=np.asarray(npz['root_positions'],dtype=float)
        if roots.ndim!=2 or roots.shape[1]!=3 or not 2<=len(roots)<=300:
            raise ValueError('Motion requires 2–300 frames of root positions.')
        if 'local_rotations_xyzw' in npz:
            q=np.asarray(npz['local_rotations_xyzw'],dtype=float)
            if q.shape!=(len(roots),joints,4):raise ValueError('Motion quaternion dimensions do not match the source skeleton.')
        else:
            matrices=np.asarray(npz['local_rot_mats'],dtype=float)
            if matrices.shape!=(len(roots),joints,3,3) or not np.isfinite(matrices).all():
                raise ValueError('Motion rotation dimensions do not match the source skeleton.')
            if np.max(abs(matrices@matrices.swapaxes(-1,-2)-np.eye(3)))>.001 or np.min(np.linalg.det(matrices))<.999:
                raise ValueError('Motion rotations must be orthonormal.')
            q=Rotation.from_matrix(matrices.reshape(-1,3,3)).as_quat().reshape(-1,joints,4)
    if not np.isfinite(roots).all() or not np.isfinite(q).all() or abs(roots).max()>1000:
        raise ValueError('Motion contains invalid positions or rotations.')
    norms=np.linalg.norm(q,axis=-1,keepdims=True)
    if np.max(abs(norms-1))>.01:raise ValueError('Motion quaternions must be normalized.')
    return roots,q/norms


def advanced_twist_nodes(data, mapping, target_mapping, parents, rest):
    """Recognize only Studio's two validated Advanced forearm helpers."""
    joints = set(data['skins'][0]['joints'])
    by_name = {data['nodes'][i]['name']: i for i in joints}
    supplied = target_mapping if isinstance(target_mapping, dict) else {}
    helpers = {}
    for source, side in (('Left', 'left'), ('Right', 'right')):
        forearm, hand = mapping[source+'ForeArm'], mapping[source+'Hand']
        name = supplied.get(side+'_forearm_twist')
        if name is None:
            candidates = (data['nodes'][forearm]['name']+'_StudioTwist', 'Studio_'+side+'_forearm_twist')
            name = next((candidate for candidate in candidates if candidate in by_name), None)
        if name is None:
            continue
        if not isinstance(name, str) or name not in by_name:
            raise ValueError('The saved Advanced forearm helper is missing from the skin.')
        node = by_name[name]
        span = rest[hand][:3,3] - rest[forearm][:3,3]
        if (parents.get(node) != forearm or np.linalg.norm(span) < 1e-8
                or np.linalg.norm(rest[node][:3,3] - rest[forearm][:3,3] - span*.5) > np.linalg.norm(span)*.02
                or 'matrix' in data['nodes'][node]):
            raise ValueError('The Advanced forearm helper does not match this skeleton.')
        helpers[side] = (node, forearm, hand)
    if helpers and len(helpers) != 2:
        raise ValueError('Advanced animation transfer requires both forearm helpers.')
    return helpers


def drive_advanced_twists(desired, helpers, rest, rest_rot, previous=None):
    """Use the same half-wrist axial rotation as authored Blender motions."""
    for side, (node, forearm, hand) in helpers.items():
        world_axis = normalize(rest[hand][:3,3] - rest[forearm][:3,3])
        axis = rest_rot[hand].T @ world_axis
        delta = rest_rot[hand].T @ rest_rot[forearm] @ desired[forearm].T @ desired[hand]
        quat = Rotation.from_matrix(delta).as_quat()
        if quat[3] < 0:
            quat = -quat
        angle = 2*math.atan2(float(quat[:3] @ axis), float(quat[3]))
        if previous is not None:
            angle += math.tau * round((previous.get(side, angle) - angle) / math.tau)
            previous[side] = angle
        correction = Rotation.from_rotvec((rest_rot[node].T @ world_axis)*angle*.5).as_matrix()
        desired[node] = desired[forearm] @ rest_rot[forearm].T @ rest_rot[node] @ correction


def solve_clip(data,binary,skeleton,motion, *, fps=30, inplace=False, leg_ik=True, target_mapping=None):
    names=skeleton['names']; lookup={n:i for i,n in enumerate(names)}
    s_parents=skeleton['parents']; offsets=np.asarray(skeleton['offsets'],dtype=float)
    if skeleton.get('up','Y')!='Y' or skeleton.get('units','metres')!='metres':raise ValueError('Unsupported source coordinates.')
    roots,q=load_motion(motion,skeleton)
    src_rot,src_pos,neutral=source_fk(names,s_parents,offsets,q,roots)
    parents,local,rest,rest_rot,order=gltf_rig(data)
    mapping, mapping_method = resolve_target_mapping(data,binary,target_mapping)
    twists = advanced_twist_nodes(data,mapping,target_mapping,parents,rest)
    for s in mapping:
        if s not in lookup:raise ValueError('Source joint missing: '+s)
    inverse={t:s for s,t in mapping.items()}
    joints=set(j for skin in data['skins'] for j in skin['joints'])
    if not set(mapping.values())<=joints:raise ValueError('Target map is not contained in the skin.')
    for i in mapping.values():
        if 'matrix' in data['nodes'][i]:raise ValueError('Animated node uses matrix instead of TRS.')
    # Preserve limb reach rather than scaling by stylized head height.
    ratios=[]
    for side in ('Left','Right'):
        a,b,c=[side+n for n in ('Leg','Shin','Foot')]
        src_length=np.linalg.norm(neutral[lookup[b]]-neutral[lookup[a]])+np.linalg.norm(neutral[lookup[c]]-neutral[lookup[b]])
        dst_length=np.linalg.norm(rest[mapping[b]][:3,3]-rest[mapping[a]][:3,3])+np.linalg.norm(rest[mapping[c]][:3,3]-rest[mapping[b]][:3,3])
        ratios.append(dst_length/src_length)
    scale=float(np.mean(ratios))
    proportions={}
    for side in ('Left','Right'):
        for limb,chain in [('arm',('Arm','ForeArm','Hand')),('leg',('Leg','Shin','Foot'))]:
            points=[side+n for n in chain]
            sl=sum(np.linalg.norm(neutral[lookup[b]]-neutral[lookup[a]]) for a,b in zip(points,points[1:]))
            tl=sum(np.linalg.norm(rest[mapping[b]][:3,3]-rest[mapping[a]][:3,3]) for a,b in zip(points,points[1:]))
            proportions[side+'_'+limb]={'source_length_m':float(sl),'target_length_m':float(tl),'ratio':float(tl/sl)}
    source_ground=-min(neutral[lookup[n],1] for n in ('LeftToeBase','RightToeBase'))
    source_neutral=neutral+np.array([0,source_ground,0])
    troot=mapping['Hips']; sroot=lookup['Hips']
    horizontal=roots[0].copy();horizontal[1]=0
    root_delta=(roots-horizontal-np.array([0,source_ground,0]))*scale
    if inplace:root_delta[:,[0,2]]=0
    result_rot={i:[] for i in [*mapping.values(), *(helper[0] for helper in twists.values())]};result_trans=[]
    foot_positions={side:[] for side in ('Left','Right')}
    toe_positions={side:[] for side in ('Left','Right')}
    target_head_positions=[]
    align={a:b for a,b in ALIGN_PAIRS}
    max_reach_error=0.
    twist_angles={}
    for frame in range(len(roots)):
        desired={};positions={}
        for i in order:
            parent=parents.get(i); parent_rot=desired[parent] if parent is not None else np.eye(3)
            parent_rest=rest_rot[parent] if parent is not None else np.eye(3)
            if i in inverse:
                semantic=inverse[i];j=lookup[semantic]
                # SOMA30 is a standard T-pose with identity rest rotations.
                world=src_rot[frame,j]@rest_rot[i]
                if semantic in align:
                    child=align[semantic]
                    target_axis=rest_rot[i].T@(rest[mapping[child]][:3,3]-rest[i][:3,3])
                    source_axis=src_pos[frame,lookup[child]]-src_pos[frame,j]
                    world=swing(world@target_axis,source_axis)@world
            else:world=parent_rot@parent_rest.T@rest_rot[i]
            desired[i]=world
            if parent is None:positions[i]=rest[i][:3,3].copy()
            else:positions[i]=positions[parent]+parent_rot@parent_rest.T@(rest[i][:3,3]-rest[parent][:3,3])
            if i==troot:positions[i]=rest[i][:3,3]+root_delta[frame]
        if leg_ik:
            for side in ('Left','Right'):
                a,b,c=[side+n for n in ('Leg','Shin','Foot')]
                thigh,shin,foot=[mapping[n] for n in (a,b,c)]
                hip=positions[thigh]
                # Match source ankle lift and movement relative to hip, at target proportions.
                goal=hip+(src_pos[frame,lookup[c]]-src_pos[frame,lookup[a]])*scale
                goal[1]=rest[foot][1,3]+(src_pos[frame,lookup[c],1]-source_neutral[lookup[c],1])*scale
                l1=np.linalg.norm(rest[shin][:3,3]-rest[thigh][:3,3]);l2=np.linalg.norm(rest[foot][:3,3]-rest[shin][:3,3])
                delta=goal-hip;distance=np.linalg.norm(delta);clamped=np.clip(distance,1e-5,l1+l2-1e-6)
                max_reach_error=max(max_reach_error,float(max(0,distance-(l1+l2))))
                direction=normalize(delta)
                bend=src_pos[frame,lookup[b]]-src_pos[frame,lookup[a]];bend-=direction*np.dot(bend,direction)
                if np.linalg.norm(bend)<1e-5:bend=np.array([0.,0.,1.])-direction*direction[2]
                bend=normalize(bend)
                cosine=np.clip((l1*l1+clamped*clamped-l2*l2)/(2*l1*clamped),-1,1)
                knee=hip+direction*l1*cosine+bend*l1*np.sqrt(max(0,1-cosine*cosine))
                ankle=hip+direction*clamped
                for bone,child,vector in ((thigh,shin,knee-hip),(shin,foot,ankle-knee)):
                    axis=rest_rot[bone].T@(rest[child][:3,3]-rest[bone][:3,3])
                    desired[bone]=swing(desired[bone]@axis,vector)@desired[bone]
                positions[shin]=knee;positions[foot]=ankle
        drive_advanced_twists(desired,twists,rest,rest_rot,twist_angles)
        # Re-evaluate positions from corrected parent rotations; these are the
        # transforms the GLB player will actually apply, including ankle/toes.
        for i in order:
            parent=parents.get(i)
            if parent is None:positions[i]=rest[i][:3,3].copy()
            else:positions[i]=positions[parent]+desired[parent]@rest_rot[parent].T@(rest[i][:3,3]-rest[parent][:3,3])
            if i==troot:positions[i]=rest[i][:3,3]+root_delta[frame]
        for i in result_rot:
            parent=parents.get(i);parent_rot=desired[parent] if parent is not None else np.eye(3)
            quat=Rotation.from_matrix(parent_rot.T@desired[i]).as_quat()
            if result_rot[i] and np.dot(quat,result_rot[i][-1])<0:quat=-quat
            result_rot[i].append(quat)
        parent=parents.get(troot)
        matrix=rest[parent] if parent is not None else np.eye(4)
        result_trans.append((np.linalg.inv(matrix)@np.r_[positions[troot],1])[:3])
        for side in foot_positions:
            foot_positions[side].append(positions[mapping[side+'Foot']].copy())
            toe_positions[side].append(positions[mapping[side+'ToeBase']].copy())
        target_head_positions.append(positions[mapping['Head']])
    foot_diagnostics={}
    for side in foot_positions:
        src_ankle=src_pos[:,lookup[side+'Foot']];src_toe=src_pos[:,lookup[side+'ToeBase']]
        dst_ankle=np.array(foot_positions[side]);dst_toe=np.array(toe_positions[side])
        source_speed=np.linalg.norm(np.diff(src_toe[:,[0,2]],axis=0),axis=1)*fps
        target_speed=np.linalg.norm(np.diff(dst_toe[:,[0,2]],axis=0),axis=1)*fps
        # A diagnostic mask only: it does not manufacture learned contact labels.
        contact=(src_toe[:-1,1]<.04)&(src_toe[1:,1]<.04)&(source_speed<.15)
        expected_toe=rest[mapping[side+'ToeBase']][1,3]+(src_toe[:,1]-source_neutral[lookup[side+'ToeBase'],1])*scale
        foot_diagnostics[side]={
            'source_toe_min_y_m':float(src_toe[:,1].min()),'target_toe_min_y_m':float(dst_toe[:,1].min()),
            'source_toe_below_ground_m':float(max(0,-src_toe[:,1].min())),
            'target_toe_below_ground_m':float(max(0,-dst_toe[:,1].min())),
            'target_vs_scaled_source_toe_y_error_max_m':float(abs(dst_toe[:,1]-expected_toe).max()),
            'source_ankle_min_y_m':float(src_ankle[:,1].min()),'target_ankle_min_y_m':float(dst_ankle[:,1].min()),
            'source_low_slow_toe_intervals':int(contact.sum()),
            'source_low_slow_toe_speed_mean_m_s':float(source_speed[contact].mean()) if contact.any() else None,
            'target_same_intervals_toe_speed_mean_m_s':float(target_speed[contact].mean()) if contact.any() else None,
            'caveat':'Toe/ankle joint diagnostics, not exact shoe sole collision; contact mask is heuristic, not model prediction.'}
    source_steps=2*np.arccos(np.clip(abs(np.sum(q[1:]*q[:-1],axis=-1)),0,1))*180/np.pi
    target_steps={data['nodes'][i]['name']:float((2*np.arccos(np.clip(abs(np.sum(np.array(values)[1:]*np.array(values)[:-1],axis=-1)),0,1))*180/np.pi).max()) for i,values in result_rot.items()}
    quat_norm_error=max(float(abs(np.linalg.norm(values,axis=1)-1).max()) for values in result_rot.values())
    quaternion_check={'target_max_norm_error':quat_norm_error,'target_hemisphere_continuous':all(np.min(np.sum(np.array(v)[1:]*np.array(v)[:-1],axis=-1))>=0 for v in result_rot.values()),
                      'source_largest_step_deg':float(source_steps.max()),'target_largest_step_deg':max(target_steps.values()),
                      'target_step_max_by_node_deg':target_steps}
    if quat_norm_error>1e-5 or not quaternion_check['target_hemisphere_continuous']:raise ValueError('Invalid target quaternion sequence.')
    report={'fps':fps,'frames':len(roots),'duration_s':(len(roots)-1)/fps,'root_motion':'in_place' if inplace else 'displacement',
            'mapping_method':mapping_method,'source_skeleton':skeleton.get('name','SOMA30'),'source_joint_count':len(names),'target_mapping':{s:data['nodes'][i]['name'] for s,i in mapping.items()},
            'target_nodes':mapping,'leg_scale':scale,'leg_scale_each':ratios,'source_neutral_pelvis_height_m':source_ground,
            'limb_proportions':proportions,
            'leg_ik':leg_ik,'max_unreachable_ankle_m':max_reach_error,'foot_contacts':'no contact locking; source ankle trajectories preserved with two-bone IK',
            'fingers':'existing rest pose retained; SOMA30 does not generate articulated fingers',
            'forearm_helpers':{'method':'half of wrist axial rotation' if twists else 'none',
                               'nodes':{side:data['nodes'][helper[0]]['name'] for side,helper in twists.items()}},
            'root_displacement_m':root_delta[-1].tolist(),'root_path_length_m':float(np.linalg.norm(np.diff(root_delta,axis=0),axis=1).sum()),
            'foot_bounds_m':{side:{'min':np.min(pos,axis=0).tolist(),'max':np.max(pos,axis=0).tolist()} for side,pos in foot_positions.items()},
            'foot_diagnostics':foot_diagnostics}
    report['quaternion_checks']=quaternion_check
    root_speeds=np.linalg.norm(np.diff(roots[:,[0,2]],axis=0),axis=1)*fps
    window=min(len(root_speeds),max(1,round(fps*.5)))
    report['source_intent_measures']={
        'horizontal_speed_first_half_second_m_s':float(root_speeds[:window].mean()),
        'horizontal_speed_last_half_second_m_s':float(root_speeds[-window:].mean()),
        'pelvis_height_first_m':float(roots[0,1]),'pelvis_height_min_m':float(roots[:,1].min()),
        'pelvis_height_max_m':float(roots[:,1].max()),'pelvis_height_last_m':float(roots[-1,1]),
        'pelvis_end_minus_start_m':float(roots[-1,1]-roots[0,1]),
        'loopability':'not automatically loopable; no loop correction applied'}
    return np.arange(len(roots),dtype=np.float32)/fps,{i:np.array(v,dtype=np.float32) for i,v in result_rot.items()},np.array(result_trans,dtype=np.float32),troot,report


def append_access(data,binary,values,kind):
    values=np.asarray(values,dtype='<f4');start=len(binary)
    binary.extend(b'\0'*(-start%4));start=len(binary);raw=values.tobytes();binary.extend(raw)
    view=len(data['bufferViews']);data['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':len(raw)})
    item={'bufferView':view,'componentType':5126,'count':len(values),'type':kind}
    if kind=='SCALAR':item.update(min=[float(values.min())],max=[float(values.max())])
    index=len(data['accessors']);data['accessors'].append(item)
    return index


def append_clip(data,binary,name,times,rotations,translations,root,extras):
    if any(c.get('name')==name for c in data.get('animations',[])):raise ValueError('Clip already exists: '+name)
    timeidx=append_access(data,binary,times,'SCALAR');samplers=[];channels=[]
    for node,values in rotations.items():
        idx=append_access(data,binary,values,'VEC4');samplers.append({'input':timeidx,'output':idx,'interpolation':'LINEAR'})
        channels.append({'sampler':len(samplers)-1,'target':{'node':node,'path':'rotation'}})
    idx=append_access(data,binary,translations,'VEC3');samplers.append({'input':timeidx,'output':idx,'interpolation':'LINEAR'})
    channels.append({'sampler':len(samplers)-1,'target':{'node':root,'path':'translation'}})
    data.setdefault('animations',[]).append({'name':name,'samplers':samplers,'channels':channels,'extras':extras})


def write_glb(path,data,binary):
    data['buffers'][0]['byteLength']=len(binary)
    descriptor=json.dumps(data,separators=(',',':'),ensure_ascii=False).encode();descriptor+=b' '*(-len(descriptor)%4)
    binary=bytes(binary)+b'\0'*(-len(binary)%4)
    blob=struct.pack('<4sII',b'glTF',2,12+8+len(descriptor)+8+len(binary))+struct.pack('<II',len(descriptor),0x4e4f534a)+descriptor+struct.pack('<II',len(binary),0x004e4942)+binary
    Path(path).write_bytes(blob)


def verify_preservation(before,oldbin,after,newbin):
    expected=copy.deepcopy(before)
    for key in ('animations','accessors','bufferViews'):
        if after.get(key,[])[:len(before.get(key,[]))]!=before.get(key,[]):raise AssertionError('Changed original '+key)
        expected[key]=after.get(key,[])
    expected['buffers'][0]['byteLength']=after['buffers'][0]['byteLength']
    if expected!=after:raise AssertionError('Changed original asset descriptor.')
    if newbin[:len(oldbin)]!=oldbin:raise AssertionError('Changed original binary payload.')
    descriptors={key:before.get(key)==after.get(key) for key in ('meshes','skins','nodes','materials','textures','images','samplers','scenes','scene')}
    prior_entries={key:before.get(key,[])==after.get(key,[])[:len(before.get(key,[]))] for key in ('animations','accessors','bufferViews')}
    return {'original_binary_prefix_identical':True,'original_binary_bytes':len(oldbin),'original_binary_sha256':hashlib.sha256(oldbin).hexdigest(),
            'unchanged_asset_descriptors':descriptors,'unchanged_prior_entries':prior_entries,
            'original_animation_descriptors_identical':True,'asset_descriptors_identical':True,
            'original_clips':len(before.get('animations',[])),'final_clips':len(after.get('animations',[])),
            'vertices_uv_weights_bind_matrices_materials_images_preserved':True}


def validate_skeleton(skeleton):
    """Accept the canonical SOMA30 motion convention supported by this version."""
    if not isinstance(skeleton,dict) or tuple(skeleton.get('names',())) != SOMA30_JOINTS:
        raise ValueError('Generated animation currently requires the SOMA30 humanoid skeleton.')
    parents=skeleton.get('parents',[])
    if any(type(p) is not int for p in parents) or tuple(parents)!=SOMA30_PARENTS:
        raise ValueError('The source skeleton must use the canonical SOMA30 hierarchy.')
    offsets=np.asarray(skeleton.get('offsets',[]),dtype=float)
    if offsets.shape!=(30,3) or not np.isfinite(offsets).all() or abs(offsets).max()>5 or abs(offsets[0]).max()>1e-6:
        raise ValueError('The source skeleton offsets are invalid.')
    if skeleton.get('up','Y')!='Y' or skeleton.get('forward','+Z')!='+Z' or skeleton.get('units','metres') not in ('metres','meters'):
        raise ValueError('The source motion must use metres, Y-up and +Z-forward.')
    if 'coordinate_system' in skeleton and 'Y-up' not in str(skeleton['coordinate_system']):
        raise ValueError('The source motion must use Y-up coordinates.')
    if skeleton.get('quaternion_order','xyzw')!='xyzw' or skeleton.get('fps',30)!=30:
        raise ValueError('The source motion must use XYZW quaternions at 30 fps.')
    rest=skeleton.get('rest_local_quaternions_xyzw')
    if rest is not None and (np.shape(rest)!=(30,4) or np.max(abs(np.asarray(rest)-[0,0,0,1]))>1e-6):
        raise ValueError('A standard T-pose source skeleton is required.')
    for name in ('LeftShin','LeftFoot','RightShin','RightFoot','LeftForeArm','LeftHand','RightForeArm','RightHand'):
        if np.linalg.norm(offsets[SOMA30_JOINTS.index(name)])<1e-4:
            raise ValueError('The source skeleton contains a zero-length limb.')
    return dict(skeleton,units='metres',up='Y',fps=30)


def _validate_hierarchy(data):
    nodes=data.get('nodes',[])
    if not 1<=len(nodes)<=4096:
        raise ValueError('The target skeleton is too large or missing.')
    parents={}
    for i,node in enumerate(nodes):
        for child in node.get('children',[]):
            if type(child) is not int or not 0<=child<len(nodes) or child in parents:
                raise ValueError('The target node hierarchy is invalid.')
            parents[child]=i
    for i in range(len(nodes)):
        chain=set()
        while i in parents:
            if i in chain or len(chain)>128:
                raise ValueError('The target node hierarchy is cyclic or too deep.')
            chain.add(i);i=parents[i]


def resolve_target_mapping(data,binary,target_mapping=None):
    """Validate one humanoid skeleton, including shared skins across meshes."""
    _validate_hierarchy(data)
    skins=data.get('skins',[])
    if not skins:
        raise ValueError('Rig the character before adding an animation.')
    joint_sets=[set(skin.get('joints',[])) for skin in skins]
    joints=joint_sets[0]
    if not 22<=len(joints)<=256 or any(group!=joints for group in joint_sets):
        raise ValueError('Animation transfer requires one compatible humanoid skeleton. Shared skins are supported.')
    if any(type(i) is not int or not 0<=i<len(data['nodes']) for i in joints):
        raise ValueError('The target skin contains invalid joints.')
    names={i:data['nodes'][i].get('name') for i in joints}
    if any(not isinstance(name,str) or not name for name in names.values()) or len(set(names.values()))!=len(names):
        raise ValueError('The humanoid joints must have unique names.')
    parents,local,world,rotations,order=gltf_rig(data)
    if any(not np.isfinite(matrix).all() for matrix in world.values()):
        raise ValueError('The target contains invalid rest transforms.')
    points={names[i]:world[i][:3,3] for i in joints}
    named_parents={names[i]:names.get(parents.get(i)) for i in joints}
    low,high=posed_bounds(data,binary)
    inferred=infer_positions(points,named_parents,low,high)
    required=set(SOMA_TO_SEMANTIC.values())
    if not required<=inferred.keys():
        raise ValueError('This rig is not a confidently recognized upright humanoid. Use a compatible T-pose or A-pose rig.')
    if any(points[inferred[side+'_toe']][2]-points[inferred[side+'_foot']][2]<(high[1]-low[1])*.005 for side in ('left','right')):
        raise ValueError('The rig must stand upright and face forward in its rest pose. Prepare its orientation before transferring animation.')
    method='validated geometric humanoid mapping'
    if target_mapping:
        if not isinstance(target_mapping,dict):
            raise ValueError('The saved humanoid mapping is invalid.')
        for semantic in required & target_mapping.keys():
            if target_mapping[semantic]!=inferred[semantic]:
                raise ValueError('The saved humanoid mapping does not match the current skeleton. Prepare the rig again.')
        if required<=target_mapping.keys():
            method='saved humanoid mapping verified against geometry'
    by_name={name:i for i,name in names.items()}
    mapping={source:by_name[inferred[semantic]] for source,semantic in SOMA_TO_SEMANTIC.items()}
    return mapping,method


def _clip_name(name):
    if not isinstance(name,str) or not name.strip() or len(name)>120 or any(ord(c)<32 for c in name):
        raise ValueError('An animation name of 1–120 printable characters is required.')
    return name.strip()


def _write_atomic(destination,data,binary):
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.generated-motion-',suffix='.glb',dir=destination.parent)
    os.close(descriptor);temporary=Path(temporary)
    try:
        write_glb(temporary,data,binary)
        read(temporary)
        os.replace(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)


def append_generated_motion(source_glb,destination,*,motion_path,skeleton,clip_name,
                            provenance=None,target_mapping=None,in_place=False):
    """Append a reusable motion without changing existing assets or animations.

    Returns a JSON-serializable preservation and transfer report. The caller
    owns transactional workspace publishing and must pass a separate output.
    No generator is started and no network or GPU work occurs here.
    """
    source_glb=Path(source_glb);destination=Path(destination)
    if source_glb.resolve()==destination.resolve():
        raise ValueError('Animation transfer requires a separate output file.')
    if type(in_place) is not bool:
        raise ValueError('The in-place option must be boolean.')
    skeleton=validate_skeleton(skeleton);clip_name=_clip_name(clip_name)
    before,oldbin=read(source_glb)
    if len(before.get('buffers',[]))!=1:
        raise ValueError('Animation transfer requires one embedded GLB buffer.')
    if any(clip.get('name')==clip_name for clip in before.get('animations',[])):
        raise ValueError('This animation is already present on the model.')
    source_hash=sha(source_glb)
    times,rotations,translations,root,report=solve_clip(before,oldbin,skeleton,motion_path,
        fps=30,inplace=in_place,leg_ik=True,target_mapping=target_mapping)
    if provenance is not None and not isinstance(provenance,dict):
        raise ValueError('Animation provenance must be an object.')
    metadata={key:value for key,value in (provenance or {}).items() if key in PROVENANCE_FIELDS}
    encoded=json.dumps(metadata,allow_nan=False)
    if len(encoded)>16384:
        raise ValueError('Animation provenance is too large.')
    metadata.update(generated=True,fps=30,in_place=in_place,source_skeleton='somaskel30')
    data=copy.deepcopy(before);binary=bytearray(oldbin)
    append_clip(data,binary,clip_name,times,rotations,translations,root,metadata)
    preservation=verify_preservation(before,oldbin,data,binary)
    if sha(source_glb)!=source_hash:
        raise ValueError('The source model changed during animation transfer.')
    _write_atomic(destination,data,binary)
    final,finalbin=read(destination)
    verify_preservation(before,oldbin,final,finalbin)
    return dict(report,clip_name=clip_name,provenance=metadata,preservation=preservation,
                source_sha256=source_hash,output_sha256=sha(destination),
                preview_root=data['nodes'][root]['name'],
                limitations='Review foot contacts, clothing and appendages. Finger articulation and collision correction are not generated.')


def create_motion_preview(motion_path,skeleton,destination,*,clip_name='Generated animation'):
    """Renderable preview on the installed CC0 mannequin, or a procedural rig."""
    skeleton=validate_skeleton(skeleton);clip_name=_clip_name(clip_name)
    root=Path(__file__).resolve().parent
    mannequin=root/'animations/quaternius/UAL2/Universal Animation Library 2 [Standard]/Female Mannequin/Unreal-Godot/Mannequin_F.glb'
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if mannequin.is_file():
        try:
            with tempfile.TemporaryDirectory(prefix='motion-preview-',dir=destination.parent) as temporary:
                prepared=Path(temporary)/'preview.glb'
                report=append_generated_motion(mannequin,prepared,motion_path=motion_path,skeleton=skeleton,
                                               clip_name=clip_name,provenance={},in_place=False)
                data,binary=read(prepared)
                data['animations']=[clip for clip in data['animations'] if clip['name']==clip_name]
                _write_atomic(destination,data,binary)
            return {'clip_name':clip_name,'preview_root':report['preview_root'],'preview_style':'mannequin',
                    'preview_source':'Quaternius CC0 mannequin','fps':30,'duration_s':report['duration_s']}
        except (OSError,ValueError,KeyError,TypeError) as error:
            logging.getLogger(__name__).warning('Installed mannequin preview is unavailable; using the procedural mannequin: %s',error)
            result=_procedural_preview(motion_path,skeleton,destination,clip_name)
            result['preview_fallback']='installed_mannequin_unavailable'
            return result
    return _procedural_preview(motion_path,skeleton,destination,clip_name)


def _procedural_preview(motion_path,skeleton,destination,clip_name):
    """Build a neutral skinned mannequin from simple spheres and limb cylinders."""
    roots,quaternions=load_motion(motion_path,skeleton)
    names=skeleton['names'];parents=skeleton['parents'];offsets=np.asarray(skeleton['offsets'])
    neutral=np.zeros((30,3));lookup={name:i for i,name in enumerate(names)}
    for i,parent in enumerate(parents):
        if parent>=0:neutral[i]=neutral[parent]+offsets[i]
    neutral[:,1]-=min(neutral[lookup[n],1] for n in ('LeftToeBase','RightToeBase'))
    vertices=[];triangles=[];joint_ids=[]

    def sphere(center,radius,joint):
        first=len(vertices);radius=np.asarray(radius)
        for latitude in range(9):
            phi=np.pi*latitude/8
            for longitude in range(12):
                theta=2*np.pi*longitude/12
                vertices.append(center+radius*[np.sin(phi)*np.cos(theta),np.cos(phi),np.sin(phi)*np.sin(theta)])
                joint_ids.append(joint)
        for row in range(8):
            for col in range(12):
                a=first+row*12+col;b=first+row*12+(col+1)%12;c=a+12;d=b+12
                triangles.extend([(a,b,c),(b,d,c)])

    def cylinder(a,b,radius,joint):
        direction=normalize(b-a)
        u=normalize(np.cross(direction,[0,1,0] if abs(direction[1])<.9 else [1,0,0]));v=np.cross(direction,u)
        first=len(vertices)
        for center in (a,b):
            for k in range(12):
                angle=k*np.pi/6
                vertices.append(center+radius*(u*np.cos(angle)+v*np.sin(angle)));joint_ids.append(joint)
        for k in range(12):
            a0=first+k;a1=first+(k+1)%12;b0=a0+12;b1=a1+12
            triangles.extend([(a0,a1,b0),(a1,b1,b0)])

    sphere(neutral[0],[.15,.12,.11],0)
    sphere(neutral[lookup['Chest']]+[0,.09,0],[.19,.22,.115],lookup['Chest'])
    sphere(neutral[lookup['Head']]+[0,.075,0],[.095,.13,.10],lookup['Head'])
    cylinder(neutral[lookup['Neck1']],neutral[lookup['Head']],.045,lookup['Neck1'])
    for side,sign in [('Left',1),('Right',-1)]:
        for a,b,radius in [('Arm','ForeArm',.047),('ForeArm','Hand',.038),('Leg','Shin',.065),('Shin','Foot',.048)]:
            ai,bi=lookup[side+a],lookup[side+b]
            cylinder(neutral[ai],neutral[bi],radius,ai)
            sphere(neutral[ai],[radius]*3,ai)
        hand=lookup[side+'Hand'];foot=lookup[side+'Foot']
        sphere(neutral[hand]+[sign*.045,0,0],[.075,.033,.04],hand)
        sphere(neutral[foot]+[0,-.015,.05],[.055,.035,.10],foot)
    positions=np.array(vertices,dtype='<f4');indices=np.array(triangles,dtype='<u4')
    normals=np.zeros_like(positions)
    face=np.cross(positions[indices[:,1]]-positions[indices[:,0]],positions[indices[:,2]]-positions[indices[:,0]])
    for corner in range(3):np.add.at(normals,indices[:,corner],face)
    normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
    joints=np.zeros((len(positions),4),dtype='<u2');joints[:,0]=joint_ids
    weights=np.zeros((len(positions),4),dtype='<f4');weights[:,0]=1
    nodes=[{'name':name,'translation':(neutral[i] if parents[i]<0 else offsets[i]).tolist()} for i,name in enumerate(names)]
    for i,parent in enumerate(parents):
        if parent>=0:nodes[parent].setdefault('children',[]).append(i)
    nodes.append({'name':'Preview mannequin','mesh':0,'skin':0})
    data={'asset':{'version':'2.0','generator':'TRELLIS Studio procedural motion preview'},
          'scene':0,'scenes':[{'nodes':[0,30]}],'nodes':nodes,'buffers':[{'byteLength':0}],
          'bufferViews':[],'accessors':[],'materials':[{'name':'Neutral mannequin',
          'pbrMetallicRoughness':{'baseColorFactor':[.69,.76,.63,1],'metallicFactor':.08,'roughnessFactor':.5}}]}
    binary=bytearray()

    def array(values,kind,component):
        raw=np.ascontiguousarray(values);binary.extend(b'\0'*(-len(binary)%4));start=len(binary);binary.extend(raw.tobytes())
        view=len(data['bufferViews']);data['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':raw.nbytes})
        descriptor={'bufferView':view,'componentType':component,'count':len(raw),'type':kind}
        if kind=='VEC3' and values is positions:descriptor.update(min=raw.min(axis=0).tolist(),max=raw.max(axis=0).tolist())
        index=len(data['accessors']);data['accessors'].append(descriptor);return index

    attributes={'POSITION':array(positions,'VEC3',5126),'NORMAL':array(normals,'VEC3',5126),
                'JOINTS_0':array(joints,'VEC4',5123),'WEIGHTS_0':array(weights,'VEC4',5126)}
    index=array(indices.reshape(-1),'SCALAR',5125)
    data['meshes']=[{'name':'Procedural mannequin','primitives':[{'attributes':attributes,'indices':index,'material':0}]}]
    bind=np.tile(np.eye(4),(30,1,1));bind[:,:3,3]=-neutral
    inverse=array(bind.transpose(0,2,1).reshape(30,16).astype('<f4'),'MAT4',5126)
    data['skins']=[{'name':'SOMA30 preview','joints':list(range(30)),'skeleton':0,'inverseBindMatrices':inverse}]
    for i in range(30):
        for frame in range(1,len(quaternions)):
            if np.dot(quaternions[frame,i],quaternions[frame-1,i])<0:quaternions[frame,i]*=-1
    roots[:,[0,2]]-=roots[0,[0,2]]
    append_clip(data,binary,clip_name,np.arange(len(roots),dtype=np.float32)/30,
                {i:quaternions[:,i] for i in range(30)},roots,0,{'generated':True,'fps':30})
    _write_atomic(destination,data,binary)
    return {'clip_name':clip_name,'preview_root':'Hips','preview_style':'mannequin',
            'preview_source':'Procedural mannequin','fps':30,'duration_s':(len(roots)-1)/30}
