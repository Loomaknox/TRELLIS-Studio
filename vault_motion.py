"""Fit a one-hand speed vault to a TRELLIS humanoid, in Blender world metres.

Height-scaled paths are expressed as (character left, forward, up). Contact
constraints use the target's bone lengths, foot height and palm, not the
Quaternius mannequin's wrist and ankle positions.
"""
import bisect
import math
import numpy as np

from mathutils import Matrix, Quaternion, Vector


UP = Vector((0, 0, 1))


def ease(a, b, t):
    u = max(0., min(1., (t-a)/(b-a)))
    return u*u*(3.-2.*u)


def curve(keys, t):
    """Shape-preserving cubic Hermite. Flat holds have zero endpoint velocity."""
    x = [k[0] for k in keys]
    i = max(0, min(len(keys)-2, bisect.bisect_right(x,t)-1))
    dt = x[i+1]-x[i]
    u = max(0., min(1., (t-x[i])/dt))

    def slope(k):
        if k == 0 or k == len(keys)-1:
            return 0.
        a = (keys[k][1]-keys[k-1][1])/(x[k]-x[k-1])
        b = (keys[k+1][1]-keys[k][1])/(x[k+1]-x[k])
        return 0. if a*b <= 0 else 2*a*b/(a+b)

    return ((1+2*u)*(1-u)**2*keys[i][1] + u*(1-u)**2*dt*slope(i)
            + u*u*(3-2*u)*keys[i+1][1] + u*u*(u-1)*dt*slope(i+1))


def gltf(v):
    return [round(float(n),7) for n in (v.x, v.z, -v.y)]


def palm_orientation(forward, normal, aim, down):
    swing = forward.rotation_difference(aim)
    n = swing @ normal
    roll = math.atan2(aim.dot(n.cross(down)), n.dot(down))
    return Quaternion(aim,roll) @ swing


def mesh_positions(armature):
    import bpy
    for mesh in bpy.context.scene.objects:
        if mesh.type=='MESH' and mesh.find_armature()==armature:
            coords=np.empty((len(mesh.data.vertices),3),dtype=np.float32)
            mesh.data.vertices.foreach_get('co',coords.ravel())
            world=np.asarray(mesh.matrix_world)
            yield mesh, coords@world[:3,:3].T+world[:3,3]


def palm_surface(armature, wrist, center, digits, facing, height):
    """Fit a supporting plane to the open hand and locate the palmar skin."""
    tips=[]
    for bone in digits:
        points=[armature.matrix_world@b.head_local for b in [bone,*bone.children_recursive]]
        tips.extend(points)
    origin=np.array(wrist)
    plane=np.array([wrist,*tips],dtype=float)-origin
    _,_,axes=np.linalg.svd(plane-plane.mean(axis=0),full_matrices=False)
    normal=Vector(axes[-1])
    if normal.dot(facing)<0:
        normal.negate()
    forward=(center-wrist).normalized()
    forward=(forward-normal*normal.dot(forward)).normalized()
    across=forward.cross(normal).normalized()
    local_palm=wrist+(center-wrist)*.60
    candidates=[]
    for _,coords in mesh_positions(armature):
        rel=coords-origin
        along=rel@np.array(forward)
        keep=((along>height*.006)&(along<height*.145)&(np.abs(rel@np.array(across))<height*.046)
              &(np.abs(rel@np.array(normal))<height*.040))
        candidates.append(rel[keep])
    skin=np.concatenate(candidates) if candidates else np.empty((0,3))
    if len(skin)>12:
        relative=np.array(local_palm-wrist)
        central=(np.linalg.norm(skin-relative,axis=1)<height*.034)
        if central.any():
            # Pick the tangent with palm support. A slightly raised fingertip
            # is natural, a rolled hand balancing on the pinky is not.
            best=None
            for roll in (-.18,-.09,0.,.09,.18):
                for pitch in (-.24,-.16,-.08,0.,.08):
                    n=(normal+roll*across+pitch*forward).normalized()
                    depths=skin@np.array(n)
                    edge=np.quantile(depths,.999)
                    pad=np.quantile(depths[central],.97)
                    score=edge-pad+height*.006*(abs(roll)+abs(pitch+.08))
                    if best is None or score<best[0]:
                        best=score,n,edge
            _,normal,depth=best
            pad=skin[central]
            depths=pad@np.array(normal)
            close=pad[depths>=depths.max()-height*.0015]
            marker=Vector(close[np.argmin(np.linalg.norm(close-relative,axis=1))])
            local_palm=wrist+marker+normal*(depth-marker.dot(normal))
    forward=(forward-normal*normal.dot(forward)).normalized()
    return forward,normal,local_palm


class Pose:
    """Small FK working set. Avoid evaluating the full skinned mesh for each IK joint."""
    def __init__(self, model, authored, offset, tilt):
        self.model = model
        self.rotation = {name:tilt @ value if name in model.body else model.rest[name]
                         for name,value in authored.items()}
        self.position = {model.root:model.heads[model.root]+offset}
        self.local = {}
        for name, parent in model.parents.items():
            if parent:
                self.local[name] = self.rotation[parent].inverted() @ self.rotation[name]

    def point(self, name):
        if name not in self.position:
            parent = self.model.parents[name]
            if parent is None:
                return self.model.heads[name]
            delta = self.model.rest[parent].inverted() @ (self.model.heads[name]-self.model.heads[parent])
            self.position[name] = self.point(parent) + self.rotation[parent] @ delta
        return self.position[name]

    def rotate(self, name, desired):
        self.rotation[name] = desired
        for child in self.model.children[name]:
            self.position.pop(child,None)
            self.rotate(child,desired @ self.local[child])

    def ik(self, upper, lower, end, goal, pole, end_rotation, *, continuous=True):
        from retarget_motions import leg_chain_goal
        a, b, c = (self.point(n) for n in (upper,lower,end))
        # At a folded elbow or knee the pole can momentarily be parallel to
        # the hip–ankle/shoulder–wrist line. Transport the last bend plane
        # onto this frame and limit the roll about the limb, not its reach.
        axis=(goal-a).normalized()
        previous=self.model.planes.get(upper)
        if continuous and axis.length_squared>.5:
            projected=pole-axis*pole.dot(axis)
            if previous:
                old_axis,old_pole=previous
                carried=(old_axis.rotation_difference(axis)@old_pole).normalized()
                if projected.length>.03:
                    wanted=projected.normalized()
                    turn=math.atan2(axis.dot(carried.cross(wanted)),carried.dot(wanted))
                    limit=self.model.plane_step*min(1.,projected.length/.35)
                    pole=Quaternion(axis,max(-limit,min(limit,turn)))@carried
                else:
                    pole=carried
            else:
                if projected.length<.001:
                    projected=(b-a)-axis*(b-a).dot(axis)
                pole=projected.normalized()
            self.model.planes[upper]=(axis,pole)
        mid, tip = leg_chain_goal(a,goal,pole,c-a,(b-a).length,(c-b).length)
        for start, child, target in ((upper,lower,mid),(lower,end,tip)):
            direction = self.point(child)-self.point(start)
            desired = target-self.point(start)
            if min(direction.length_squared,desired.length_squared)>1e-12:
                self.rotate(start,direction.rotation_difference(desired) @ self.rotation[start])
        self.rotate(end,end_rotation)


# Sole trajectories in world space across the obstacle. Holds give each takeoff
# and landing a planted phase. The left knee leads, the right boot follows.
FOOT_PATHS = {
    'left': [
        (.27,.08,.50,.10),(.33,.11,.58,.16),(.40,.19,.70,.33),
        (.46,.31,.87,.49),(.51,.38,1.03,.57),(.55,.36,1.20,.58),
        (.60,.26,1.41,.43),(.65,.14,1.55,.19),(.70,.07,1.59,0.),
        (.76,.07,1.59,0.),(.82,.06,1.68,.08)],
    'right': [
        (.27,-.055,.665,.075),(.32,-.055,.715,0.),(.365,-.055,.715,0.),
        (.40,.035,.705,.20),(.45,.16,.745,.43),(.49,.24,.845,.54),
        (.54,.29,1.04,.55),(.59,.27,1.22,.55),(.635,.20,1.40,.41),
        (.69,.09,1.57,.24),(.75,-.03,1.72,.15),(.815,-.05,1.91,0.),
        (.85,-.05,1.91,0.)]
}


class VaultMotion:
    start_contact = .432
    end_contact = .555
    travel = 2.24

    def __init__(self,target,mapping,rest,heads,height,floor):
        self.target, self.mapping, self.rest, self.heads, self.h = target,mapping,rest,heads,height
        required = [s+'_'+part for s in ('left','right') for part in ('arm','forearm','hand','leg','shin','foot')]
        if not all(mapping.get(key) in heads for key in required):
            raise ValueError('A side vault requires both hands, arms, feet and legs on a humanoid rig.')
        self.root = mapping['root']
        self.body = {self.root, *(b.name for b in target.data.bones[self.root].children_recursive)}
        self.parents = {b.name:(b.parent.name if b.parent else None) for b in target.data.bones}
        self.children = {b.name:[c.name for c in b.children] for b in target.data.bones}
        hip = .5*(heads[mapping['left_leg']]+heads[mapping['right_leg']])
        lr = heads[mapping['left_arm']]-heads[mapping['right_arm']]
        lr.z = 0.
        self.left = lr.normalized()
        self.forward = self.left.cross(UP).normalized()
        if self.forward.length<.9:
            raise ValueError('The shoulder line is degenerate for this side vault.')
        self.origin = Vector((hip.x,hip.y,floor))
        self.box = self.pos(0.,1.12,.20)
        self.palm = self.pos(-.18,1.105,.40)
        hand = mapping['right_hand']
        wrist = heads[hand]
        digits = target.data.bones[hand].children
        roots = [heads[b.name] for b in digits]
        if len(roots)>=4:
            thumb = min(roots,key=lambda p:(p-wrist).length)
            knuckles = [p for p in roots if p!=thumb]
            center = sum(knuckles,Vector())/len(knuckles)
            direction = (center-wrist).normalized()
            across = thumb-center
            facing = across.cross(direction).normalized()
            if facing.length<.8:
                raise ValueError('The supporting palm cannot be located on this rig.')
            direction,normal,self.rest_palm=palm_surface(target,wrist,center,
                [b for b in digits if heads[b.name]!=thumb],facing,height)
        else:
            direction = (target.matrix_world@target.data.bones[hand].tail_local-wrist).normalized()
            normal = -UP + direction*direction.dot(UP)
            if normal.length<.1:
                normal = self.forward-direction*self.forward.dot(direction)
            normal.normalize()
            center = wrist+direction*height*.055
            self.rest_palm = wrist+(center-wrist)*.62+normal*(height*.008)
        self.palm_local = rest[hand].inverted()@(self.rest_palm-wrist)
        aim = (self.forward-.22*self.left).normalized()
        self.hand_rotation = palm_orientation(direction,normal,aim,-UP) @ rest[hand]
        self.wrist_goal = self.palm-self.hand_rotation@self.palm_local
        self.max_contact_error = 0.
        self.support = {}
        self.strides = {}
        self.soles = self.measure_soles()
        self.planes = {}
        self.baked_poses = []

    def measure_soles(self):
        """Heel, forefoot and side edges of each shoe in ankle bind space."""
        low_points = []
        self.skin_samples={s:[] for s in ('left','right')}
        for mesh,coords in mesh_positions(self.target):
            low_points.append(coords[coords[:,2]<self.origin.z+.045*self.h])
            for side in ('left','right'):
                foot=self.heads[self.mapping[side+'_foot']]
                radius=np.linalg.norm(coords[:,:2]-np.array(foot)[:2],axis=1)
                other=self.heads[self.mapping[('left' if side=='right' else 'right')+'_foot']]
                ids=np.flatnonzero((coords[:,2]<self.origin.z+.105*self.h)&(radius<.20*self.h)
                    &(radius<=np.linalg.norm(coords[:,:2]-np.array(other)[:2],axis=1)))
                ids=ids[::max(1,len(ids)//1800)]
                if not len(ids):
                    continue
                groups={}
                for j,idx in enumerate(ids):
                    weights=[(mesh.vertex_groups[g.group].name,g.weight) for g in mesh.data.vertices[int(idx)].groups
                             if g.weight>0 and mesh.vertex_groups[g.group].name in self.rest]
                    total=sum(w for _,w in weights)
                    for name,w in weights:
                        groups.setdefault(name,[]).append((j,w/total))
                packed={}
                for name,pairs in groups.items():
                    ix=np.array([j for j,_ in pairs])
                    weights=np.array([w for _,w in pairs])
                    offsets=(coords[ids[ix]]-np.array(self.heads[name]))@np.asarray(self.rest[name].to_matrix())
                    packed[name]=ix,weights,offsets
                used=np.array(sorted({j for pairs in groups.values() for j,_ in pairs}),dtype=int)
                if len(used):
                    self.skin_samples[side].append((len(ids),packed,used))
        points=np.concatenate(low_points) if low_points else np.empty((0,3))
        soles={}
        for side in ('left','right'):
            name=self.mapping[side+'_foot']
            dif=points-np.array(self.heads[name])
            nearby=dif[np.linalg.norm(dif[:,:2],axis=1)<self.h*.18]
            # The medial halves of closely spaced feet can touch in the bind pose.
            opposite=self.mapping[('right' if side=='left' else 'left')+'_foot']
            other=np.array(self.heads[opposite]-self.heads[name])
            nearby=nearby[np.linalg.norm(nearby[:,:2],axis=1)<=np.linalg.norm(nearby[:,:2]-other[:2],axis=1)]
            if len(nearby):
                front=nearby@np.array(self.forward)
                across=nearby@np.array(self.left)
                edges=[]
                for f in np.array_split(np.argsort(front),4):
                    for group in np.array_split(f[np.argsort(across[f])],2):
                        if len(group):
                            edges.append(Vector(nearby[group[np.argmin(nearby[group,2])]]))
            else:
                edges=[UP*(self.origin.z-self.heads[name].z)]
            soles[side]=[self.rest[name].inverted()@edge for edge in edges]
        return soles

    def sole_height(self, pose, side):
        low=math.inf
        for count,groups,used in self.skin_samples[side]:
            world_z=np.zeros(count)
            for name,(ix,weights,offsets) in groups.items():
                z=np.asarray(pose.rotation[name].to_matrix())[2]
                world_z[ix]+=weights*(pose.point(name).z+offsets@z)
            low=min(low,float(world_z[used].min()))
        return low

    def interpolate(self, a, b, t):
        """glTF interpolates parent-local rotations, including between planted keys."""
        p=object.__new__(Pose)
        p.model=self
        p.rotation={}
        p.position={self.root:a.point(self.root).lerp(b.point(self.root),t)}
        for name in a.rotation:
            parent=self.parents[name]
            if parent:
                qa=a.rotation[parent].inverted()@a.rotation[name]
                qb=b.rotation[parent].inverted()@b.rotation[name]
                p.rotation[name]=p.rotation[parent]@qa.slerp(qb,t)
            else:
                p.rotation[name]=a.rotation[name].slerp(b.rotation[name],t)
        return p

    def correct_ground(self):
        """Lift only a penetrating shoe, based on its actual skin weights.

        Two bracketing keys share the correction if interpolation dips under
        the floor. The hip's airborne path and the supporting arm stay intact.
        """
        poses=self.baked_poses
        changed=set()
        for _ in range(3):
            lift={s:[0.]*len(poses) for s in self.soles}
            for i,p in enumerate(poses):
                samples=[(p,(i,))]
                if i:
                    samples.extend((self.interpolate(poses[i-1],p,t),(i-1,i)) for t in (.25,.5,.75))
                for pose,keys in samples:
                    for side in self.soles:
                        delta=self.origin.z-self.sole_height(pose,side)
                        if delta>.0008*self.h:
                            for key in keys:
                                lift[side][key]=max(lift[side][key],delta+.0015*self.h)
            if not any(max(row) for row in lift.values()):
                break
            for side,row in lift.items():
                upper,lower,foot=(self.mapping[side+'_'+j] for j in ('leg','shin','foot'))
                for key,dz in enumerate(row):
                    if dz:
                        p=poses[key]
                        # Preserve children (in particular toe roll) as solved
                        # before this small, world-vertical leg IK adjustment.
                        p.local={n:p.rotation[pa].inverted()@p.rotation[n] for n,pa in self.parents.items() if pa}
                        p.ik(upper,lower,foot,p.point(foot)+UP*dz,p.point(lower)-p.point(upper),
                             p.rotation[foot],continuous=False)
                        changed.update((upper,lower,foot))
        if changed:
            from retarget_motions import continuous_rotation
            previous={}
            for key,p in enumerate(poses):
                for name in changed:
                    parent=self.parents[name]
                    q=self.rest[name].inverted()@self.rest[parent]@p.rotation[parent].inverted()@p.rotation[name]
                    q=continuous_rotation(q,previous.get(name))
                    previous[name]=q
                    bone=self.target.pose.bones[name]
                    bone.rotation_quaternion=q
                    bone.keyframe_insert('rotation_quaternion',frame=key,group=name)

    def prepare_support(self, poses, src_heads, scale):
        from retarget_motions import foot_support_offsets
        self.plane_step=math.radians(12)*72/(len(poses)-1)
        for side in ('left','right'):
            foot, toe = side+'_foot', side+'_toe'
            samples = [pose[foot]['head']*scale + self.forward*(self.h*self.travel*i/(len(poses)-1))
                       for i,pose in enumerate(poses)]
            sole = [pose.get(toe,pose[foot])['head'].z*scale for pose in poses]
            self.support[side] = foot_support_offsets(samples,sole,self.h,cyclic=False,in_place=False)
            self.strides[side]=[( (pose[foot]['head']-pose[side+'_leg']['head'])*scale,
                                 (pose[foot]['head'].z-src_heads[foot].z)*scale) for pose in poses]

    def pos(self, side, forward, up):
        return self.origin + self.h*(side*self.left+forward*self.forward+up*UP)

    def apply(self,t,authored,base_offset):
        h = self.h
        hop = curve([(0,0),(.235,0),(.315,-.045),(.36,-.018),(.445,.098),
                     (.505,.139),(.55,.135),(.615,.075),(.69,-.06),(.75,-.035),(.84,0),(1,0)],t)
        lateral = curve([(0,0),(.25,0),(.36,.005),(.48,.12),(.55,.18),(.65,.14),(.78,.01),(.86,0),(1,0)],t)
        accent = ease(.27,.465,t)*(1-ease(.555,.77,t))
        jog = (1-accent)*base_offset.dot(UP)
        offset = self.forward*(h*self.travel*t)+self.left*(lateral*h)+UP*(hop*h+jog)
        roll = curve([(0,0),(.255,0),(.37,13),(.435,49),(.50,69),
                      (.55,68),(.60,53),(.685,21),(.78,0),(1,0)],t)
        tilt = Quaternion(self.forward,math.radians(roll)) @ Quaternion(self.left,math.radians(13*accent))
        p = Pose(self,authored,offset,tilt)
        # Lift the extended fingers clear before swinging the arm past the far
        # edge. Blending straight from the planted palm into the running pose
        # would pull the fingertips through the lid on the first release frame.
        armblend = ease(.265,.397,t)*(1-ease(.628,.76,t))
        release = ease(self.end_contact,.635,t)
        approach = 1-ease(.380,self.start_contact,t)
        wrist_goal = self.wrist_goal + h*(release*(.17*UP+.13*self.forward)+approach*(.105*UP-.12*self.forward))
        right_arm,right_fore,right_hand = (self.mapping['right_'+role] for role in ('arm','forearm','hand'))
        reach = .945*((self.heads[right_fore]-self.heads[right_arm]).length +
                      (self.heads[right_hand]-self.heads[right_fore]).length)
        to_hand = wrist_goal-p.point(right_arm)
        # Shift the weight of the body onto the hand before planting. A short
        # forearm needs extra trunk drop; an unreachable wrist would slide.
        if armblend and to_hand.length>reach:
            offset += armblend*to_hand.normalized()*(to_hand.length-reach)
            p = Pose(self,authored,offset,tilt)
        # Torso inclines into the planted arm; keep eyes naturally nearer the horizon.
        head = self.mapping.get('head')
        if head:
            p.rotate(head,p.rotation[head].slerp(authored[head],.48*accent))
        for side in ('left','right'):
            arm,fore,hand = (self.mapping[side+'_'+key] for key in ('arm','forearm','hand'))
            if side=='right':
                goal = p.point(hand).lerp(wrist_goal,armblend)
                rot = p.rotation[hand].slerp(self.hand_rotation,armblend)
                pole = (-self.left*.75-self.forward*.45+UP*.12)
                if armblend>0:
                    p.ik(arm,fore,hand,goal,pole,rot)
                if self.start_contact<=t<=self.end_contact:
                    err=(p.point(hand)+p.rotation[hand]@self.palm_local-self.palm).length
                    self.max_contact_error=max(self.max_contact_error,err)
                for b in self.target.data.bones[hand].children_recursive:
                    parent=self.parents[b.name]
                    straight=p.rotation[parent]@self.rest[parent].inverted()@self.rest[b.name]
                    p.rotate(b.name,p.rotation[b.name].slerp(straight,armblend))
            elif accent>0:
                hand_target=p.point(arm)+h*(.23*self.left+.125*self.forward+.105*UP)
                swing=(p.point(fore)-p.point(arm)).normalized()
                pole=swing.lerp((.45*self.left-.85*self.forward-.4*UP).normalized(),accent)
                p.ik(arm,fore,hand,p.point(hand).lerp(hand_target,accent),pole,p.rotation[hand])

        for side, path in FOOT_PATHS.items():
            upper,lower,foot = (self.mapping[side+'_'+key] for key in ('leg','shin','foot'))
            weight = ease(.235,.32,t)*(1-ease(.76,.86,t))
            loc = [curve([(key[0],key[j]) for key in path],t) for j in (1,2,3)]
            ankle_height = self.heads[foot].z-self.origin.z
            goal = self.pos(*loc)+UP*ankle_height
            lift = ease(.37,.47,t)*(1-ease(.61,.705,t))
            pitch = Quaternion(self.left,math.radians(-10 if side=='left' else -20)*lift)
            # Natural ankle roll follows the swing while the heel stays level at floor contact.
            flat = pitch @ Quaternion(self.forward,math.radians(16*lift)) @ self.rest[foot]
            tuck = ease(.345,.40,t)*(1-ease(.49,.55,t)) if side=='right' else 0.
            vault_pole=(self.forward*(1-.68*tuck)+self.left*(.2+.67*lift+.65*tuck)+UP*(.12+.30*tuck))
            leg_pole=(p.point(lower)-p.point(upper)).normalized().lerp(vault_pole.normalized(),weight)
            frame=round(t*(len(self.support[side])-1))
            stride,z=self.strides[side][frame]
            authored_goal=p.point(upper)+stride+self.support[side][frame]
            authored_goal.z=self.heads[foot].z+z
            dest=authored_goal.lerp(goal,weight)
            rotation=p.rotation[foot].slerp(flat,weight)
            # Account for the tip of an angled boot, not just the ankle joint.
            sole=min((rotation@point).z for point in self.soles[side])
            dest.z=max(dest.z,self.origin.z-sole+.002*h)
            p.ik(upper,lower,foot,dest,leg_pole,rotation)
            toe=self.mapping.get(side+'_toe')
            if toe and weight:
                flat_toe=rotation@self.rest[foot].inverted()@self.rest[toe]
                p.rotate(toe,p.rotation[toe].slerp(flat_toe,weight))

        rest, target = self.rest, self.target
        for name in self.mapping.values():
            parent = self.parents[name]
            parent_r = rest[parent] if parent else target.matrix_world.to_quaternion()
            parent_p = p.rotation[parent] if parent else target.matrix_world.to_quaternion()
            target.pose.bones[name].rotation_quaternion = rest[name].inverted() @ parent_r @ parent_p.inverted() @ p.rotation[name]
        self.baked_poses.append(p)
        return offset

    def metadata(self,duration):
        if self.max_contact_error > self.h*.015:
            print(f'Side vault maximum planted palm offset: {self.max_contact_error:.3f} m',flush=True)
            raise ValueError('The right palm cannot reach the crate on this rig.')
        return dict(obstacle=dict(type='box',center=gltf(self.box),size=[.96*self.h,.40*self.h,.28*self.h],
                                   travel=gltf(self.forward*self.h*self.travel)),
                    contact=dict(side='right',bone=self.mapping['right_hand'],palm_target=gltf(self.palm),
                                 palm_bind=gltf(self.rest_palm),
                                 interval_s=[self.start_contact*duration,self.end_contact*duration],
                                 max_key_error_m=self.max_contact_error))


def gltf_palm_offset(doc, contact):
    """Express the bind-pose marker in the exported wrist node's actual basis."""
    nodes = doc['nodes']
    idx = next(i for i,n in enumerate(nodes) if n.get('name')==contact['bone'])
    parents = {child:i for i,n in enumerate(nodes) for child in n.get('children',[])}
    transform = Matrix.Identity(4)
    while True:
        node = nodes[idx]
        if 'matrix' in node:
            m=node['matrix']
            local=Matrix([m[i:i+4] for i in range(0,16,4)]).transposed()
        else:
            x,y,z,w=node.get('rotation',[0,0,0,1])
            local=Matrix.LocRotScale(Vector(node.get('translation',[0,0,0])),Quaternion((w,x,y,z)),
                                    Vector(node.get('scale',[1,1,1])))
        transform = local @ transform
        if idx not in parents:
            break
        idx=parents[idx]
    return list(transform.inverted() @ Vector(contact['palm_bind']))
