"""Retarget authored humanoid rotations, timing and contacts onto a fitted rig."""
from pathlib import Path
import bpy,math,itertools
from mathutils import Vector,Quaternion
from retarget_catalogue import BY_ID
from studio_import import animation_recipe

ROOT=Path(__file__).resolve().parent

def source_map(pack):
    if pack=='UAL1':
        result=dict(root='DEF-hips',spine_1='DEF-spine.001',spine_2='DEF-spine.002',spine='DEF-spine.003',neck='DEF-neck',head='DEF-head')
        for side,suffix in [('left','L'),('right','R')]:
            for semantic,bone in [('clavicle','shoulder'),('arm','upper_arm'),('forearm','forearm'),('hand','hand'),('leg','thigh'),('shin','shin'),('foot','foot'),('toe','toe')]:result[side+'_'+semantic]='DEF-'+bone+'.'+suffix
    elif pack=='UAL2':
        result=dict(root='pelvis',spine_1='spine_01',spine_2='spine_02',spine='spine_03',neck='neck_01',head='Head')
        for side,suffix in [('left','l'),('right','r')]:
            for semantic,bone in [('clavicle','clavicle'),('arm','upperarm'),('forearm','lowerarm'),('hand','hand'),('leg','thigh'),('shin','calf'),('foot','foot'),('toe','ball')]:result[side+'_'+semantic]=bone+'_'+suffix
    else:
        raise ValueError(f'Unknown animation source pack: {pack}')
    return result

def drive_forearm_twists(target, mapping, twists, rest, rest_heads, *, fraction=0.5):
    """Bake the proximal forearm helpers' share of the wrist's axial rotation."""
    for side, name in twists.items():
        hand = mapping[side + '_hand']
        forearm = mapping[side + '_forearm']
        world_axis = (rest_heads[hand] - rest_heads[forearm]).normalized()
        axis = rest[hand].inverted() @ world_axis
        rotation = target.pose.bones[hand].rotation_quaternion
        projected = Vector((rotation.x, rotation.y, rotation.z)).dot(axis)
        if rotation.w < 0:
            projected = -projected
        angle = 2 * math.atan2(projected, abs(rotation.w)) * fraction
        target.pose.bones[name].rotation_quaternion = Quaternion(rest[name].inverted() @ world_axis, angle)


def body_helper_drivers(target, mapping, helpers, rest, rest_heads, *, expressive=False):
    if not helpers:
        return []
    from rig_expert_blender import EXPERT_HELPER_SOURCES

    sources = EXPERT_HELPER_SOURCES
    if expressive:
        from rig_expert_blender import EXPRESSIVE_HELPER_SOURCES, EXPRESSIVE_TWIST_PROXIMAL, EXPRESSIVE_TWIST_DISTAL
        sources = {**sources, **EXPRESSIVE_HELPER_SOURCES}

    drivers = []
    for role, name in helpers.items():
        parent_role, source_role, kind = sources[role]
        parent, source = mapping[parent_role], mapping[source_role]
        span = (rest_heads[source] - rest_heads[parent]).normalized()
        axis = rest[source].inverted() @ span
        basis = rest[name].inverted() @ rest[source]
        fraction = 0.5
        if expressive and kind == 'twist':
            fraction = EXPRESSIVE_TWIST_DISTAL if role in EXPRESSIVE_HELPER_SOURCES else EXPRESSIVE_TWIST_PROXIMAL
        drivers.append((target.pose.bones[name], target.pose.bones[source], axis,
                        basis, basis.inverted(), kind, fraction))
    return drivers


def drive_body_helpers(drivers):
    """Share the selected part of each joint's rotation with its weighted helper."""
    neutral = Quaternion()
    for helper, source, axis, basis, inverse_basis, kind, fraction in drivers:
        rotation = source.rotation_quaternion.normalized()
        axial = axis * Vector((rotation.x, rotation.y, rotation.z)).dot(axis)
        twist = Quaternion((rotation.w, axial.x, axial.y, axial.z))
        twist = twist.normalized() if twist.magnitude > 1e-8 else neutral
        correction = twist if kind == 'twist' else rotation @ twist.conjugated()
        helper.rotation_quaternion = neutral.slerp((basis @ correction @ inverse_basis).normalized(), fraction)


def blend_crouch_pose(idle, crouched, weight, finger_parents=()):
    pose = {
        role: dict(rotation=joint['rotation'].slerp(crouched[role]['rotation'], weight),
                   head=joint['head'].lerp(crouched[role]['head'], weight))
        for role, joint in idle.items() if role in crouched
    }
    # Blend each finger relative to its parent. World-space shortest arcs can
    # go opposite ways on adjacent joints even when both endpoint poses are valid.
    for role, parent in finger_parents:
        if role not in pose or parent not in pose:
            continue
        from_local = idle[parent]['rotation'].inverted() @ idle[role]['rotation']
        to_local = crouched[parent]['rotation'].inverted() @ crouched[role]['rotation']
        pose[role]['rotation'] = pose[parent]['rotation'] @ from_local.slerp(to_local, weight)
    return pose


def author(scene,target,target_mapping,requests,height,*,profile=None):
    packs={};original_actions=set(bpy.data.actions);original_objects=set(bpy.data.objects)
    base_mapping=target_mapping.copy()
    twists = profile['twists'] if profile else {}
    body_helpers = profile.get('body_helpers', {}) if profile else {}
    expressive = profile is not None and profile['profile'] == 'expressive'
    forearm_fraction = 0.5
    if expressive:
        from rig_expert_blender import EXPRESSIVE_TWIST_PROXIMAL
        forearm_fraction = EXPRESSIVE_TWIST_PROXIMAL
    for request in requests:
        recipe=BY_ID.get(request['id'])
        if not recipe or recipe['source_pack'] in packs:continue
        before=set(bpy.data.actions);objects=set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(ROOT/recipe['source_model']))
        source=next(o for o in set(bpy.data.objects)-objects if o.type=='ARMATURE')
        actions={a.name:a for a in set(bpy.data.actions)-before}
        # glTF import may suffix an action already present from the target.
        for action in list(actions.values()):
            base=action.name.rsplit('.',1)[0] if action.name[-3:].isdigit() else action.name
            actions.setdefault(base,action)
        smap=source_map(recipe['source_pack'])
        target_map=base_mapping.copy()
        for side in ('left','right'):
            if side+'_hand' not in target_map:continue
            target_hand=target.data.bones[target_map[side+'_hand']];source_hand=source.data.bones[smap[side+'_hand']]
            source_roots=list(source_hand.children)
            if profile:
                if not profile['articulated_fingers']:continue
                target_roots=[target.data.bones[target_map[f'{side}_finger_{i}_0']] for i in range(5)]
            else:
                target_roots=list(target_hand.children)
            if len(target_roots)!=5 or len(source_roots)!=5:continue
            tpoints=[target.matrix_world@b.head_local-target.matrix_world@target_hand.head_local for b in target_roots]
            spoints=[source.matrix_world@b.head_local-source.matrix_world@source_hand.head_local for b in source_roots]
            tscale=max(sum(p.length for p in tpoints)/5,.001);sscale=max(sum(p.length for p in spoints)/5,.001)
            permutation=min(itertools.permutations(range(5)),key=lambda indices:sum((tpoints[i]/tscale-spoints[indices[i]]/sscale).length_squared for i in range(5)))
            for finger,index in enumerate(permutation):
                tb=target_roots[finger];sb=source_roots[index]
                for segment in range(3):
                    key=side+'_finger_'+str(finger)+'_'+str(segment);target_map[key]=tb.name;target_mapping[key]=tb.name;smap[key]=sb.name
                    if segment == 2 or not tb.children or not sb.children:break
                    if profile:tb=target.data.bones[target_map[f'{side}_finger_{finger}_{segment + 1}']]
                    else:tb=max(tb.children,key=lambda b:b.length)
                    sb=max(sb.children,key=lambda b:b.length)
        packs[recipe['source_pack']]=(source,actions,smap,target_map)
    target.animation_data_clear();target.animation_data_create()
    rest={b.name:(target.matrix_world@b.matrix_local).to_quaternion() for b in target.data.bones}
    rest_heads={b.name:target.matrix_world@b.head_local for b in target.data.bones}
    helper_drivers = body_helper_drivers(target,base_mapping,body_helpers,rest,rest_heads,expressive=expressive)
    ordered=list(target.data.bones);ordered.sort(key=lambda b:len(b.parent_recursive))
    authored=[]
    def reset_pose():
        for p in target.pose.bones:p.rotation_mode='QUATERNION';p.rotation_quaternion=Quaternion();p.location=Vector();p.scale=Vector((1,1,1))
    def capture(source,smap,frame):
        scene.frame_set(math.floor(frame),subframe=frame-math.floor(frame));bpy.context.view_layer.update()
        return {key:dict(rotation=(source.matrix_world@source.pose.bones[name].matrix).to_quaternion(),head=source.matrix_world@source.pose.bones[name].head) for key,name in smap.items() if name in source.pose.bones}
    def activate(source,action):
        source.animation_data_create();source.animation_data.action=action
        if action.slots:source.animation_data.action_slot=action.slots[0]
    for request in requests:
        recipe=BY_ID.get(request['id'])
        if not recipe:
            authored.append(dict(id=request['id'],name=request['id'],duration_s=request['duration'],source='Legacy animation preserved'))
            continue
        source,actions,smap,mapping=packs[recipe['source_pack']]
        finger_parents = []
        if recipe.get('composite') == 'crouch' and profile and profile['articulated_fingers']:
            source_roles = {name: role for role, name in smap.items()}
            for role, name in smap.items():
                if '_finger_' in role:
                    parent = source.data.bones[name].parent
                    if parent and parent.name in source_roles:
                        finger_parents.append((role, source_roles[parent.name]))
        src_rest={key:(source.matrix_world@source.data.bones[name].matrix_local).to_quaternion() for key,name in smap.items() if name in source.data.bones}
        src_heads={key:source.matrix_world@source.data.bones[name].head_local for key,name in smap.items() if name in source.data.bones}
        src_action=actions[recipe['source_clip']];activate(source,src_action)
        start,end=src_action.frame_range;source_duration=(end-start)/24;duration=request['duration'];frames=round(duration*24)
        cycles=max(1,round(duration/max(source_duration,.001))) if recipe['loop'] else 1
        action_name='TS_'+request['id']+'_'+str(duration)+'s'
        for existing in list(original_actions):
            previous = animation_recipe(existing.name)
            if previous and previous['id'] == request['id']:
                original_actions.remove(existing)
                bpy.data.actions.remove(existing)
        action=bpy.data.actions.new(action_name);action.use_fake_user=True;target.animation_data.action=action
        # Leg length controls root displacement and ankle targets, not head size.
        ratios=[]
        for side in ('left','right'):
            ratios.append((rest_heads[mapping[side+'_leg']]-rest_heads[mapping[side+'_foot']]).length/(src_heads[side+'_leg']-src_heads[side+'_foot']).length)
        scale=sum(ratios)/len(ratios)
        for frame in range(frames+1):
            u=frame/frames;phase=u*cycles
            source_frame=start+(end-start)*(phase%1 if u<1 and recipe['loop'] else 1 if recipe['loop'] else u)
            activate(source,src_action);pose=capture(source,smap,source_frame)
            if recipe.get('composite')=='jump':
                if u<.3:name,progress='Jump_Start',u/.3
                elif u<.65:name,progress='Jump_Loop',(u-.3)/.35
                else:name,progress='Jump_Land',(u-.65)/.35
                act=actions[name];activate(source,act);a,b=act.frame_range;pose=capture(source,smap,a+(b-a)*progress)
            elif recipe.get('composite')=='crouch':
                act=actions['Idle_Loop'];activate(source,act);idle=capture(source,smap,act.frame_range[0])
                act=actions['Crouch_Idle_Loop'];activate(source,act);down=capture(source,smap,act.frame_range[0])
                weight=min(1,u/.3,(1-u)/.3);weight=weight*weight*(3-2*weight)
                pose=blend_crouch_pose(idle,down,weight,finger_parents)
            reset_pose();desired={};target_to_semantic={name:key for key,name in mapping.items()}
            for b in ordered:
                key=target_to_semantic.get(b.name)
                parent_rest=rest[b.parent.name] if b.parent else target.matrix_world.to_quaternion()
                parent_pose=desired[b.parent.name] if b.parent else target.matrix_world.to_quaternion()
                if key in pose and key in src_rest:
                    world=pose[key]['rotation']@src_rest[key].inverted()@rest[b.name]
                    if any(key.endswith('_'+part) for part in ('arm','forearm','hand','leg','shin')):
                        axis=world@Vector((0,1,0));source_axis=pose[key]['rotation']@Vector((0,1,0))
                        world=axis.rotation_difference(source_axis)@world
                else:world=parent_pose@parent_rest.inverted()@rest[b.name]
                desired[b.name]=world
                target.pose.bones[b.name].rotation_quaternion=rest[b.name].inverted()@parent_rest@parent_pose.inverted()@world
            root=target.pose.bones[mapping['root']]
            displacement=(pose['root']['head']-src_heads['root'])*scale
            if recipe['loop'] or request['id'] in ('crouch','jump'):displacement.x=0;displacement.y=0
            root.location=(target.matrix_world.to_3x3()@root.bone.matrix_local.to_3x3()).inverted()@displacement
            bpy.context.view_layer.update()
            # Two-bone leg solve retains source knee planes and scaled ankle lift.
            for side in ('left','right'):
                thigh=target.pose.bones[mapping[side+'_leg']];shin=target.pose.bones[mapping[side+'_shin']];foot=target.pose.bones[mapping[side+'_foot']]
                hip=target.matrix_world@thigh.head
                source_vector=pose[side+'_foot']['head']-pose[side+'_leg']['head']
                goal=hip+source_vector*scale
                goal.z=rest_heads[mapping[side+'_foot']].z+(pose[side+'_foot']['head'].z-src_heads[side+'_foot'].z)*scale
                l1=(rest_heads[mapping[side+'_shin']]-rest_heads[mapping[side+'_leg']]).length;l2=(rest_heads[mapping[side+'_foot']]-rest_heads[mapping[side+'_shin']]).length
                direction=goal-hip;distance=min(max(direction.length,.001),l1+l2-.00001);direction.normalize()
                bend=pose[side+'_shin']['head']-pose[side+'_leg']['head'];bend-=direction*bend.dot(direction)
                if bend.length<.001:bend=Vector((0,-1,0));bend-=direction*bend.dot(direction)
                bend.normalize();cosine=max(-1,min(1,(l1*l1+distance*distance-l2*l2)/(2*l1*distance)))
                knee=hip+direction*l1*cosine+bend*l1*math.sqrt(max(0,1-cosine*cosine))
                for bone,vector in ((thigh,knee-hip),(shin,goal-knee)):
                    current=desired[bone.name];axis=current@Vector((0,1,0));world=axis.rotation_difference(vector.normalized())@current
                    parent_rest=rest[bone.parent.name] if bone.parent else target.matrix_world.to_quaternion();parent_pose=desired[bone.parent.name] if bone.parent else target.matrix_world.to_quaternion()
                    bone.rotation_quaternion=rest[bone.name].inverted()@parent_rest@parent_pose.inverted()@world;desired[bone.name]=world
                # Keep the foot orientation from the authored clip after the leg solve.
                world=desired[foot.name];foot.rotation_quaternion=rest[foot.name].inverted()@rest[foot.parent.name]@desired[foot.parent.name].inverted()@world
            drive_forearm_twists(target, mapping, twists, rest, rest_heads, fraction=forearm_fraction)
            drive_body_helpers(helper_drivers)
            for name in set(mapping.values()):
                p=target.pose.bones[name];p.keyframe_insert('rotation_quaternion',frame=frame,group=p.name)
            root.keyframe_insert('location',frame=frame,group=root.name)
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:key.interpolation='LINEAR'
        authored.append(dict(id=request['id'],name=recipe['name'],clip=action_name,duration_s=frames/24,
                             source=f"{recipe['author']} · {recipe['license']} · retarget",
                             source_clip=recipe['source_clip'],cycles=cycles,foot_ik=True))
    # Source rigs and their actions are never exported onto the target.
    source_actions=set()
    for source,actions,_,_ in packs.values():source.animation_data_clear();source_actions.update(actions.values())
    for obj in set(bpy.data.objects)-original_objects:bpy.data.objects.remove(obj,do_unlink=True)
    for action in source_actions:
        if action.name in bpy.data.actions:bpy.data.actions.remove(action)
    scene.frame_set(0)
    return authored
