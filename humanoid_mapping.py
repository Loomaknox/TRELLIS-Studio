"""Conservative geometric humanoid mapping shared by authored motion tools."""


def infer_positions(positions, parents, low, high):
    """Infer a conservative upright humanoid map from Y-up world joint heads.

    This CPU-only counterpart is used by animation transfer without importing
    Blender. Ambiguous, branched central chains and short/twisted limb chains
    are rejected instead of being treated as a generic humanoid.
    """
    import numpy as np

    points = {name: np.asarray(point, dtype=float) for name, point in positions.items()}
    height = float(high[1] - low[1])
    if not .05 < height < 100 or not points:
        return {}
    if any(point.shape != (3,) or not np.isfinite(point).all() for point in points.values()):
        return {}
    children = {name: [] for name in points}
    for name, parent in parents.items():
        if name in points and parent in children:
            children[parent].append(name)
    roots = [name for name in points if parents.get(name) not in points]
    if len(roots) != 1:
        return {}
    root = roots[0]
    center = points[root][0]

    def length(parent, child):
        return float(np.linalg.norm(points[child] - points[parent]))

    def main_child(name):
        options = children[name]
        return max(options, key=lambda child: length(name, child)) if options else None

    def ancestors(name):
        result = []
        while name in points:
            if name in result:
                raise ValueError('Cyclic skeleton hierarchy.')
            result.append(name)
            name = parents.get(name)
        return result

    try:
        mapping = {}
        for side, sign in [('left', 1), ('right', -1)]:
            for kind in ('leg', 'arm'):
                candidates = []
                for name, head in points.items():
                    child = main_child(name)
                    if child is None:
                        continue
                    grandchild = main_child(child)
                    if grandchild is None:
                        continue
                    vector = points[child] - head
                    next_vector = points[grandchild] - points[child]
                    if sign*(head[0]-center) < height*.025 or np.linalg.norm(vector) < height*.065:
                        continue
                    if kind == 'leg':
                        if not (low[1]+height*.32 < head[1] < low[1]+height*.68 and vector[1] < -height*.14 and next_vector[1] < -height*.13):
                            continue
                        score = abs((head[1]-low[1])/height-.54)+abs(head[0]-center)/height*.2
                    else:
                        if not (low[1]+height*.57 < head[1] < low[1]+height*.90 and abs(head[0]-center) > height*.07 and sign*vector[0] > height*.065 and abs(vector[1]) < height*.23 and sign*next_vector[0] > height*.06):
                            continue
                        score = abs(head[0]-center)/height+abs(vector[1])/height
                    candidates.append((score, name, child))
                candidates.sort()
                if not candidates or (len(candidates) > 1 and abs(candidates[0][0]-candidates[1][0]) < .005):
                    return {}
                _, upper, lower = candidates[0]
                mapping[side+'_'+kind] = upper
                mapping[side+('_shin' if kind == 'leg' else '_forearm')] = lower
            for source, destination in [('shin','foot'), ('forearm','hand')]:
                child = main_child(mapping[side+'_'+source])
                if child is None:
                    return {}
                mapping[side+'_'+destination] = child
            toe = main_child(mapping[side+'_foot'])
            clavicle = parents.get(mapping[side+'_arm'])
            if toe is None or clavicle not in points:
                return {}
            mapping[side+'_toe'] = toe
            mapping[side+'_clavicle'] = clavicle
        root = next(name for name in ancestors(mapping['left_leg']) if name in ancestors(mapping['right_leg']))
        mapping['root'] = root
        chest = next(name for name in ancestors(mapping['left_clavicle']) if name in ancestors(mapping['right_clavicle']))
        central = []
        current = root
        while True:
            candidates = [name for name in children[current]
                          if name not in mapping.values() and abs(points[name][0]-center) < height*.06 and points[name][1]-points[current][1] > height*.01]
            if not candidates:
                break
            if len(candidates) != 1:
                return {}
            current = candidates[0]
            central.append(current)
            if len(central) > 12:
                return {}
        if len(central) < 5 or chest not in central or central.index(chest) < 2:
            return {}
        mapping.update(spine_1=central[0], spine_2=central[1], spine=chest, neck=central[-2], head=central[-1])
        if len(set(mapping.values())) != len(mapping):
            return {}
        return mapping
    except (KeyError, StopIteration, ValueError):
        return {}

def infer(arm,low,high):
    bones=list(arm.data.bones);height=high.z-low.z
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
                    if not (low.z+height*.57<h.z<low.z+height*.9 and abs(h.x-cx)>height*.07 and sign*v.x>height*.065 and abs(v.z)<height*.23 and sign*(ct.x-ch.x)>height*.06):continue
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

    return mapping
