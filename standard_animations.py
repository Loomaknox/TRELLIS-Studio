"""Authored humanoid library retargeting in a private Blender process.

Geometric bone mapping is deliberately conservative. A non-humanoid keeps its
UniRig skeleton, without attaching inappropriate walk/run/crouch clips.
"""
from pathlib import Path
import bpy, json, math, sys
from mathutils import Vector, Quaternion
sys.path.insert(0,str(Path(__file__).resolve().parent))
from retarget_motions import author as author_natural_motions
from rig_landmarks import RIG_PROFILES
from studio_import import blender_animation_source, rewrite_animation_names

def export_result(job, arm, meshes, preserved_names, result):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in [arm, *meshes]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = arm
    output = job / 'model.glb'
    args = dict(filepath=str(output), export_format='GLB', use_selection=True,
                export_animations=True, export_skins=True, export_animation_mode='ACTIONS',
                export_force_sampling=True, export_frame_range=False,
                export_anim_single_armature=True, export_rest_position_armature=True,
                export_yup=True)
    supported = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
    if 'FINISHED' not in bpy.ops.export_scene.gltf(**{k:v for k,v in args.items() if k in supported}):
        raise ValueError('Exporting the animated model failed.')
    rewrite_animation_names(output, output, preserved_names)
    for action in bpy.data.actions:
        if action.name in preserved_names:
            action['studio_original_clip_name'] = preserved_names[action.name]
    bpy.ops.file.pack_all()
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(job / 'model.blend'))
    (job / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print('ANIMATION_SET', json.dumps(result, ensure_ascii=False), flush=True)


job=Path(sys.argv[sys.argv.index('--')+1]);work=job/'rig-work'
settings=json.loads((job/'settings.json').read_text(encoding='utf-8'))
options = settings.get('rig_options') or {}
creature = options.get('mode') == 'creature'
bpy.ops.wm.read_factory_settings(use_empty=True)
import_source = work/'blender-input.glb'
preserved_names = blender_animation_source(work/'rigged.glb', import_source)
import_args = dict(filepath=str(import_source))
if creature and 'disable_bone_shape' in bpy.ops.import_scene.gltf.get_rna_type().properties.keys():
    import_args['disable_bone_shape'] = True
bpy.ops.import_scene.gltf(**import_args)
scene=bpy.context.scene;scene.render.fps=24;scene.frame_start=0
arms=[o for o in scene.objects if o.type=='ARMATURE']
if len(arms)!=1: raise ValueError('This tool requires one skeleton per model.')
arm=arms[0];bones=list(arm.data.bones)
meshes=[o for o in scene.objects if o.type=='MESH']
arm.data.pose_position='REST';bpy.context.view_layer.update()
if creature:
    display_shapes = {bone.custom_shape for bone in arm.pose.bones if bone.custom_shape}
    for obj in display_shapes.intersection(meshes):
        meshes.remove(obj)
        bpy.data.objects.remove(obj, do_unlink=True)
else:
    for obj in list(meshes):
        if obj.name.startswith('Icosphere') and len(obj.data.vertices)==42 and not any(m.type=='ARMATURE' for m in obj.modifiers):
            meshes.remove(obj);bpy.data.objects.remove(obj,do_unlink=True)
if not meshes:
    raise ValueError('The rig contains no skinned mesh.')
points=[o.matrix_world@Vector(c) for o in meshes for c in o.bound_box]
low=Vector(tuple(min(p[i] for p in points) for i in range(3)))
high=Vector(tuple(max(p[i] for p in points) for i in range(3)));height=high.z-low.z
arm.data.pose_position='POSE';bpy.context.view_layer.update()
if height<=0 and not creature: raise ValueError('The character height is invalid.')
if creature:
    from creature_motion import author_creature_motion
    recipe = json.loads((job / 'creature-edit.json').read_text(encoding='utf-8'))
    if recipe.get('motion') == 'swim':
        recipe['motion'] = 'none'  # The swim clip is added directly to the exported GLB.
    clips, motion = author_creature_motion(scene, arm, recipe)
    result = dict(
        bones=len(arm.data.bones), vertices=sum(len(o.data.vertices) for o in meshes),
        triangles=sum(len(p.vertices)-2 for o in meshes for p in o.data.polygons),
        height_m=height, animation_set=clips, humanoid_mapping={},
        animation_warning=motion['warning'], creature_motion=motion, rigged=True,
        limitations='Procedural creature motion previews. Review deformation and contacts for the intended animation.',
    )
    export_result(job, arm, meshes, preserved_names, result)
    sys.exit(0)

world={b.name:(arm.matrix_world@b.head_local,arm.matrix_world@b.tail_local) for b in bones}
roots=[b for b in bones if not b.parent]
mapping={};warning=''
try:
    if len(roots)!=1: raise ValueError('The skeleton has multiple roots.')
    root=roots[0];cx=world[root.name][0].x
    def limb(sign,kind):
        candidates=[]
        for b in bones:
            h,t=world[b.name];v=t-h
            if sign*(h.x-cx)<height*.025 or v.length<height*.065: continue
            children=[c for c in b.children if (world[c.name][1]-world[c.name][0]).length>height*.065]
            if not children: continue
            c=max(children,key=lambda c:(world[c.name][1]-world[c.name][0]).length)
            ch,ct=world[c.name]
            if kind=='leg':
                if not (low.z+height*.32<h.z<low.z+height*.68 and v.z<-height*.14 and ct.z<ch.z-height*.13):continue
                score=abs((h.z-low.z)/height-.54)+abs(h.x-cx)/height*.2
            else:
                if not (low.z+height*.57<h.z<low.z+height*.9 and abs(h.x-cx)>height*.07 and sign*v.x>height*.065 and abs(v.z)<height*.23 and sign*(ct.x-ch.x)>height*.04):continue
                score=abs(h.x-cx)/height+abs(v.z)/height
            candidates.append((score,b,c))
        if not candidates: raise ValueError('Humanoid limbs could not be identified with enough confidence.')
        _,upper,lower=min(candidates,key=lambda x:x[0]);return upper,lower
    for label,sign in [('left',1),('right',-1)]:
        for kind in ('arm','leg'):
            upper,lower=limb(sign,kind)
            mapping[label+'_'+kind]=upper.name;mapping[label+'_'+('forearm' if kind=='arm' else 'shin')]=lower.name
        shin=arm.data.bones[mapping[label+'_shin']]
        if shin.children:mapping[label+'_foot']=max(shin.children,key=lambda b:b.length).name
    if len(set(mapping.values()))!=len(mapping): raise ValueError('The limb mapping is ambiguous.')
    left_parent=arm.data.bones[mapping['left_leg']].parent
    right_parents=[arm.data.bones[mapping['right_leg']],*arm.data.bones[mapping['right_leg']].parent_recursive]
    while left_parent and left_parent not in right_parents:left_parent=left_parent.parent
    if left_parent:root=left_parent
    mapping['root']=root.name
    for side in ('left','right'):
        upper=arm.data.bones[mapping[side+'_arm']]
        if upper.parent and upper.parent.name!=root.name:mapping[side+'_clavicle']=upper.parent.name
        forearm=arm.data.bones[mapping[side+'_forearm']]
        if forearm.children:mapping[side+'_hand']=max(forearm.children,key=lambda b:b.length).name
        foot=arm.data.bones.get(mapping.get(side+'_foot',''))
        if foot and foot.children:mapping[side+'_toe']=max(foot.children,key=lambda b:b.length).name

    central=[b for b in bones if abs(world[b.name][0].x-cx)<height*.12 and world[b.name][0].z>world[root.name][0].z+height*.04]
    if central:
        mapping['spine']=min(central,key=lambda b:abs(world[b.name][0].z-(world[root.name][0].z+height*.14))).name
        mapping['head']=max(central,key=lambda b:world[b.name][0].z).name
        head=arm.data.bones[mapping['head']]
        chain=[b for b in reversed(head.parent_recursive) if b!=root and abs(world[b.name][0].x-cx)<height*.12]
        if len(chain)>=4:
            mapping['spine_1']=chain[0].name;mapping['spine_2']=chain[1].name;mapping['spine']=chain[2].name;mapping['neck']=chain[-1].name


except ValueError as error:
    warning=str(error);mapping={}

profile = settings.get('existing_rig_profile')
if profile is not None:
    from rig_profiles_blender import validate_profile_mapping
    if not isinstance(profile, dict) or profile.get('profile') not in RIG_PROFILES:
        raise ValueError('The stored rig profile is unsupported.')
    mapping = validate_profile_mapping(arm, settings.get('existing_humanoid_mapping'), profile['profile'])
    twists = {side: mapping[side + '_forearm_twist'] for side in ('left', 'right')
              if side + '_forearm_twist' in mapping}
    if profile['profile'] in ('expert', 'expressive'):
        from rig_expert_blender import EXPERT_HELPER_SOURCES, EXPRESSIVE_HELPER_SOURCES

        sources = (EXPERT_HELPER_SOURCES if profile['profile'] == 'expert'
                   else {**EXPERT_HELPER_SOURCES, **EXPRESSIVE_HELPER_SOURCES})
        body_helpers = {role: mapping[role] for role in sources}
        if profile.get('body_helpers') != body_helpers:
            raise ValueError('The stored body helpers do not match the selected skeleton profile.')
    if (profile.get('joint_count') != len(mapping) or profile.get('twists') != twists
            or type(profile.get('articulated_fingers')) is not bool
            or profile['articulated_fingers'] != ('left_finger_0_0' in mapping)
            or profile.get('max_influences') != 4):
        raise ValueError('The stored rig profile does not match the model skeleton.')
    warning = ''
elif options.get('profile', 'auto') != 'auto':
    from rig_profiles_blender import RigidHandsRecommended, apply_profile
    try:
        mapping, profile = apply_profile(arm, meshes, mapping, options['profile'], options.get('articulated_fingers', False))
    except ValueError as error:
        rejection = {'message': str(error)}
        if isinstance(error, RigidHandsRecommended):
            rejection['details'] = error.details
        (work/'rig-profile-error.json').write_text(json.dumps(rejection), encoding='utf-8')
        raise
    warning = ''

rest={p.name:(p.location.copy(),p.rotation_quaternion.copy(),p.scale.copy()) for p in arm.pose.bones}
for p in arm.pose.bones:p.rotation_mode='QUATERNION'
def reset():
    for p in arm.pose.bones:p.location=Vector();p.rotation_quaternion=Quaternion();p.scale=Vector((1,1,1))
def rotate(name,axis,degrees):
    p=arm.pose.bones[name];basis=arm.matrix_world.to_3x3()@p.bone.matrix_local.to_3x3()
    return Quaternion((basis.inverted()@Vector(axis)).normalized(),math.radians(degrees))
def apply(name,axis,degrees):arm.pose.bones[name].rotation_quaternion=rotate(name,axis,degrees)@arm.pose.bones[name].rotation_quaternion
def drop_arm(name,sign):
    b=arm.data.bones[name];h,t=world[name];direction=(t-h).normalized()
    target=Vector((sign*.22,0,-.98)).normalized();q=direction.rotation_difference(target)
    basis=(arm.matrix_world.to_3x3()@b.matrix_local.to_3x3()).to_quaternion()
    arm.pose.bones[name].rotation_quaternion=basis.inverted()@q@basis

requests=settings.get('animation_clips',[])
if 'regenerate_ids' in settings:requests=[r for r in requests if r['id'] in settings['regenerate_ids']]
authored=[]
if mapping and requests:
    authored=author_natural_motions(scene,arm,mapping,requests,height,profile=profile)
elif not mapping:
    warning+=' Humanoid joints could not be identified confidently.'
if 'previous_animation_set' in settings:
    replaced={r['id'] for r in requests};authored=[r for r in settings['previous_animation_set'] if r['id'] not in replaced]+authored
result=dict(bones=len(arm.data.bones),vertices=sum(len(o.data.vertices) for o in meshes),triangles=sum(len(p.vertices)-2 for o in meshes for p in o.data.polygons),
            height_m=height,animation_set=authored,humanoid_mapping=mapping,animation_warning=warning,
            limitations='Authored humanoid motions retargeted to this rig. Review contacts, proportions, clothing and transitions on each character.',rigged=True)
if profile is not None:
    result['rig_profile'] = profile
    result['rig_skipped_clips'] = settings.get('rig_skipped_clips', [])
export_result(job, arm, meshes, preserved_names, result)
