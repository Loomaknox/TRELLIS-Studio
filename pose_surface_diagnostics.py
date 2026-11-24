"""Bounded measurements on the triangles and skin actually delivered in a GLB."""
import numpy as np
from scipy.spatial import cKDTree

from glb_data import accessor, node_transforms


def spread(count, maximum):
    return np.linspace(0, count - 1, min(count, maximum), dtype=int)


class Surface:
    def __init__(self, doc, binary, node_id, primitive, number, vertex_limit):
        node = doc['nodes'][node_id]
        attrs = primitive['attributes']
        count = doc['accessors'][attrs['POSITION']]['count']
        if not count or primitive.get('mode', 4) != 4 or primitive.get('targets') or 'EXT_mesh_gpu_instancing' in node.get('extensions', {}):
            raise ValueError('Unsupported primitive')
        self.node = node_id
        self.name = f"{node.get('name') or 'Mesh'} [{node_id}/{number}]"
        indexed = 'indices' in primitive
        corners = doc['accessors'][primitive['indices']]['count'] if indexed else count
        face_ids = spread(corners // 3, 160)
        face_rows = (face_ids[:, None] * 3 + np.arange(3)).ravel()
        tri = accessor(doc, binary, primitive['indices'], face_rows).ravel() if indexed else face_rows
        self.rows = np.union1d(spread(count, vertex_limit), tri).astype(int)
        self.faces = np.searchsorted(self.rows, tri).reshape(-1, 3)
        self.points = np.column_stack((accessor(doc, binary, attrs['POSITION'], self.rows), np.ones(len(self.rows))))
        self.joints = []
        self.bad = np.zeros(len(self.rows), dtype=bool)
        self.weights = None
        if 'skin' not in node:
            return
        skin = doc['skins'][node['skin']]
        self.joints = skin['joints']
        self.inverse = (accessor(doc, binary, skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
                        if 'inverseBindMatrices' in skin else np.broadcast_to(np.eye(4), (len(self.joints), 4, 4)))
        sets = sorted(int(k[7:]) for k in attrs if k.startswith('JOINTS_'))
        if not sets or len(sets) > 8:
            raise ValueError('Unsupported skin')
        joint = np.concatenate([accessor(doc, binary, attrs[f'JOINTS_{s}'], self.rows) for s in sets], axis=1)
        weight = np.concatenate([accessor(doc, binary, attrs[f'WEIGHTS_{s}'], self.rows) for s in sets], axis=1)
        bad_index = (joint < 0) | (joint >= len(self.joints))
        self.bad = (bad_index & (weight > 0)).any(1) | (~np.isfinite(weight)).any(1) | (weight < 0).any(1) | (np.abs(weight.sum(1)-1) > .015)
        self.indices = np.clip(joint, 0, len(self.joints)-1).astype(int)
        self.weights = np.where(np.isfinite(weight) & (weight >= 0) & ~bad_index, weight, 0)

    def posed(self, matrices, rows):
        p = self.points[rows]
        if self.weights is None:
            return np.einsum('tij,sj->tsi', matrices[self.node][:, :3], p)
        palette = np.stack([matrices[j] @ inv for j, inv in zip(self.joints, self.inverse)], axis=1)
        weights = self.weights[rows]
        total = weights.sum(1)
        result = np.zeros((len(palette), len(p), 3))
        for i in range(weights.shape[1]):
            valid = weights[:, i] > 0
            if valid.any():
                matrices_i = palette[:, self.indices[rows, i][valid], :3]
                result[:, valid] += np.einsum('tsij,sj->tsi', matrices_i, p[valid]) * weights[valid, i][None, :, None]
        result /= np.maximum(total, 1e-12)[None, :, None]
        if (total == 0).any():
            result[:, total == 0] = np.einsum('tij,sj->tsi', matrices[self.node][:, :3], p[total == 0])
        return result

    def role_weight(self, indices):
        mapped = [i for i, j in enumerate(self.joints) if j in indices]
        return (np.isin(self.indices, mapped) * self.weights).sum(1)


def read_surfaces(doc, binary, vertex_limit=2048):
    surfaces, skipped = [], 0
    for i, node in enumerate(doc.get('nodes', [])):
        if 'mesh' not in node:
            continue
        for p, prim in enumerate(doc['meshes'][node['mesh']]['primitives']):
            try:
                if len(surfaces) >= 32:
                    raise ValueError('Primitive limit')
                surfaces.append(Surface(doc, binary, i, prim, p, vertex_limit))
            except (KeyError, IndexError, ValueError, TypeError):
                skipped += 1
    ids = set(j for s in surfaces for j in [s.node, *s.joints])
    _, rest = node_transforms(doc)
    return surfaces, {j: rest(j)[None] for j in ids}, skipped


def weight_findings(surfaces, rest, lookup, mapping):
    distal = {}
    for side in ('left', 'right'):
        distal[side] = {lookup[name] for role, name in mapping.items() if name in lookup and
                        role.startswith(side+'_') and any(token in role for token in ('shin','foot','toe','hand','finger'))}
    findings = []
    for s in surfaces:
        if s.weights is None:
            continue
        crossed = (s.role_weight(distal['left']) > .18) & (s.role_weight(distal['right']) > .18)
        for mask, code in ((s.bad, 'invalid_weight'), (crossed, 'opposite_limb_weight')):
            rows = np.flatnonzero(mask)
            if not len(rows):
                continue
            idx = rows[spread(len(rows), 32)]
            findings.append(dict(code=code, primitive=s.name, count=len(rows), vertex_ids=s.rows[idx].tolist(),
                                 locations_m=s.posed(rest, idx)[0].tolist()))
    return findings


def crossings(primitives, scale):
    from model_diagnostics import _edge_crossings
    groups = [(s.name, p[s.faces]) for s, p in primitives if len(s.faces)]
    if len(groups) < 2:
        return None
    groups.sort(key=lambda item: item[0])
    worst = None
    for i, (first, a) in enumerate(groups[:-1]):
        lo, hi = a.min((0,1)), a.max((0,1))
        for second, b in groups[i+1:]:
            if (lo > b.max((0,1))).any() or (hi < b.min((0,1))).any():
                continue
            k = min(12, len(b))
            right = cKDTree(b.mean(1)).query(a.mean(1), k=k)[1].ravel()
            left = np.arange(len(a)).repeat(k)
            aa, bb = a[left], b[right]
            possible = ((aa.max(1) >= bb.min(1)) & (bb.max(1) >= aa.min(1))).all(1)
            aa, bb = aa[possible], bb[possible]
            if not len(aa):
                continue
            hit = _edge_crossings(aa, bb, scale*1e-8) | _edge_crossings(bb, aa, scale*1e-8)
            count = int(hit.sum())
            if count and (worst is None or count > worst['pairs']):
                first_hit = np.flatnonzero(hit)[0]
                worst = dict(primitives=[first,second], pairs=count, location_m=aa[first_hit].mean(0).tolist(),
                             triangles_m=[aa[first_hit].tolist(), bb[first_hit].tolist()])
    return worst


def inspect_surfaces(doc, binary, mapping, *, animated=True):
    from animation_diagnostics import read_tracks, world_matrices
    surfaces, rest, skipped = read_surfaces(doc, binary)
    lookup = {node.get('name'): i for i, node in enumerate(doc.get('nodes', []))}
    report = dict(sampled_primitives=len(surfaces), skipped_primitives=skipped,
                  face_limit_per_primitive=160, checked_clips=0, skipped_clips=0,
                  weights=weight_findings(surfaces, rest, lookup, mapping))
    if not surfaces:
        return report
    vertices = [(s,s.posed(rest, np.arange(len(s.rows)))[0]) for s in surfaces]
    extent = max(float(np.ptp(np.concatenate([p for _,p in vertices]),axis=0).max()),1e-6)
    hit = crossings(vertices, extent)
    if hit:
        report['worst_crossing'] = dict(clip=None, time_s=0, **hit)
    animations = doc.get('animations', []) if animated else []
    for idx, clip in enumerate(animations):
        if idx >= 12:
            report['skipped_clips'] += 1
            continue
        tracks, partial, errors = read_tracks(doc, binary, clip)
        if not tracks or partial or errors:
            report['skipped_clips'] += 1
            continue
        times = np.linspace(0,max(keys[-1] for keys, _, _ in tracks.values()),9)
        matrices = world_matrices(doc['nodes'], tracks, rest.keys(), times)
        posed = [(s, s.posed(matrices, np.arange(len(s.rows)))) for s in surfaces]
        report['checked_clips'] += 1
        for frame, time in enumerate(times):
            hit = crossings([(s,p[frame]) for s,p in posed], extent)
            if hit and hit['pairs'] > report.get('worst_crossing',{}).get('pairs',0):
                report['worst_crossing'] = dict(clip=clip.get('name', f'Animation {idx+1}'), clip_index=idx, time_s=float(time), **hit)
    return report


def contact_probes(doc, binary, mapping, contact, cache):
    """Bind physical skin points to anatomical regions using the exported weights."""
    if 'surfaces' not in cache:
        cache['surfaces'] = read_surfaces(doc, binary, vertex_limit=16384)
    surfaces, rest, _ = cache['surfaces']
    lookup = {n.get('name'): i for i,n in enumerate(doc['nodes'])}
    regions = {side+'_sole': {lookup[mapping[k]] for joint in ('foot','toe')
                               if (k:=side+'_'+joint) in mapping and mapping[k] in lookup}
               for side in ('left','right')}
    if contact and contact.get('bone') in lookup:
        regions['palm'] = {lookup[contact['bone']]}
    probes = {}
    for role, joints in regions.items():
        cache_key = (role, tuple(sorted(joints)),tuple(contact.get('palm_bind',())) if role=='palm' else None)
        if cache_key in cache:
            probes[role] = cache[cache_key]
            continue
        cap = 128 if role=='palm' else 48
        candidates = []
        for s in surfaces:
            if not joints or s.weights is None:
                continue
            rows = np.flatnonzero((s.role_weight(joints) >= .55) & ~s.bad)
            if not len(rows):
                continue
            bind = s.posed(rest, rows)[0]
            if role == 'palm':
                if 'palm_bind' not in contact:
                    continue
                distance = np.linalg.norm(bind - contact['palm_bind'], axis=1)
            else:
                distance = bind[:, 1]
            for at in np.argsort(distance)[:cap]:
                candidates.append((float(distance[at]), s, int(rows[at]), bind[at]))
        if candidates:
            best = sorted(candidates, key=lambda x:x[0])[:cap]
            if role=='palm':
                best=[entry for entry in best if entry[0]<=.07]
                if not best:
                    continue
            groups = {s:np.array([r for _, obj,r,_ in best if obj is s]) for _,s,_,_ in best}
            probes[role] = (groups, min(p[1] for _,_,_,p in best))
            cache[cache_key] = probes[role]
    return probes


def skin_contacts(doc, binary, tracks, clip, mapping, rate, recipe, cache):
    from animation_diagnostics import world_matrices
    extras = clip.get('extras') or {}
    contact = extras.get('trellis_contact') if isinstance(extras,dict) else None
    box = extras.get('trellis_obstacle') if isinstance(extras,dict) else None
    if not isinstance(contact,dict) or not isinstance(box,dict) or box.get('type') != 'box':
        contact, box = None,None
    if not tracks or not (contact or mapping and recipe):
        return {}
    duration = max(t[-1] for t,_,_ in tracks.values())
    if not np.isfinite(duration) or duration <= 0:
        return {}
    probes = contact_probes(doc, binary, mapping or {}, contact, cache)
    if not probes:
        return {}
    times = np.linspace(0,duration,min(1200,max(2,int(np.ceil(duration*rate))+1)))
    if contact:
        interval = contact['interval_s']
        times = np.union1d(times, np.clip(interval,0,duration))
    curves = {key:[] for key in probes}
    joint_ids = {j for groups,_ in probes.values() for s in groups for j in [s.node,*s.joints]}
    for start in range(0,len(times),24):
        matrices = world_matrices(doc['nodes'],tracks,joint_ids,times[start:start+24])
        for role,(groups,_) in probes.items():
            curves[role].append(np.concatenate([s.posed(matrices,rows) for s,rows in groups.items()],axis=1))
    floor = min((base for key,(_,base) in probes.items() if key.endswith('sole')),default=0)
    report = dict(samples=len(times), reference_floor_m=float(floor), regions={})
    for role, chunks in curves.items():
        surface = np.concatenate(chunks)
        if role == 'palm':
            target = np.asarray(contact['palm_target'])
            inside = (times>=interval[0]) & (times<=interval[1])
            if not inside.any():
                continue
            # The part of the skin touching the box can change as the wrist rotates.
            dist = np.linalg.norm(surface - target,axis=2)
            at = int(np.argmax(np.where(inside,dist.min(1),-1)))
            idx = int(dist[at].argmin())
            result = dict(region=role, metric='palm_target_distance', distance_m=float(dist[at,idx]),
                          contact_interval_s=interval, time_s=float(times[at]), location_m=surface[at,idx].tolist())
            center, size = np.asarray(box['center']), np.asarray(box['size'])
            travel = np.asarray(box['travel'],float)
            travel /= max(np.linalg.norm(travel),1e-12)
            side = np.cross([0.,1.,0.],travel)
            rel = surface-center
            overlap = inside[:,None] & (np.abs(rel@side)<=size[0]/2) & (np.abs(rel@travel)<=size[2]/2)
            depth = np.where(overlap,np.maximum(0,size[1]/2-rel[:,:,1]),0.)
            f,v = np.unravel_index(depth.argmax(),depth.shape)
            result.update(box_penetration_m=float(depth[f,v]), box_time_s=float(times[f]))
            if 'palm_offset' in contact:
                from animation_diagnostics import world_positions
                joint=next(i for i,n in enumerate(doc['nodes']) if n.get('name')==contact['bone'])
                marker=world_positions(doc['nodes'],tracks,{'palm':joint},times,{'palm':contact['palm_offset']})['palm']
                marker_error=np.linalg.norm(marker-target,axis=1)
                f=int(np.argmax(np.where(inside,marker_error,-1)))
                result.update(marker_distance_m=float(marker_error[f]),marker_time_s=float(times[f]))
        else:
            lowest = surface[:,:,1].argmin(1)
            heights = surface[np.arange(len(times)),lowest,1]-floor
            f = int(heights.argmin())
            result = dict(region=role, metric='floor_penetration', distance_m=max(0.,float(-heights[f])),
                          time_s=float(times[f]), location_m=surface[f,lowest[f]].tolist(),
                          airborne_samples=int((heights>.025).sum()))
            # A grounded heel can move for an in-place treadmill loop. Only report
            # sliding where authored root travel or a two-foot crouch supplies an anchor.
            root_name = (mapping or {}).get('root')
            rid = next((i for i,n in enumerate(doc['nodes']) if n.get('name')==root_name),None)
            travel = 0 if rid is None else np.linalg.norm(np.diff(world_matrices(
                doc['nodes'],tracks,[rid],times[[0,-1]])[rid][:,[0,2],3],axis=0))
            if travel>.10 or (recipe or {}).get('id')=='crouch':
                # Use the same material point at consecutive times and require actual contact twice.
                previous = lowest[:-1]
                p = surface[np.arange(len(times)-1),previous]
                q = surface[np.arange(1,len(times)),previous]
                planted = (p[:,1]<=floor+.012) & (q[:,1]<=floor+.012) & (np.abs(q[:,1]-p[:,1])<=.10*np.diff(times))
                # Ignore instantaneous floor crossings during take-off or landing.
                edges=np.flatnonzero(np.diff(np.r_[False,planted,False]))
                for first,last in edges.reshape(-1,2):
                    if times[last]-times[first]<.05:
                        planted[first:last]=False
                speed = np.where(planted,np.linalg.norm((q-p)[:,[0,2]],axis=1)/np.diff(times),0)
                at = int(speed.argmax())
                result.update(max_support_speed_m_s=float(speed[at]), support_time_s=float(times[at+1]))
        report['regions'][role] = result
    return report
