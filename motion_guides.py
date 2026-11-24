"""Preserve or revalidate authored scene guides on the final, sampled GLB."""
import numpy as np

from animation_diagnostics import read_tracks, world_positions
from glb_data import node_transforms, read
from studio_import import rewrite_animation_names, validate_glb


def retime_guide(box, contact, doc, binary, clip, report, height):
    options = report['options']
    if options['mode'] == 'in_place' or options['distance']:
        return {}, 'root_changed'
    if not isinstance(box, dict) or not isinstance(contact, dict):
        return {}, 'unverified'
    first, last = report['source_interval_s']
    try:
        start, end = contact['interval_s']
        start, end = max(first, start), min(last, end)
        if end <= start:
            return {}, 'trimmed'
        tracks, partial, errors = read_tracks(doc, binary, clip)
        if partial or errors or not tracks:
            return {}, 'unverified'
        duration = max(float(track[0][-1]) for track in tracks.values())
        scale = duration / (last-first)
        start, end = (start-first)*scale, (end-first)*scale
        indices = {node.get('name'): i for i, node in enumerate(doc['nodes'])}
        root = indices[report['root_bone']]
        palm = indices[contact['bone']]
        offset = contact.get('palm_offset')
        if 'palm_bind' in contact:
            _, world = node_transforms(doc)
            offset = np.linalg.solve(world(palm), [*contact['palm_bind'], 1])[:3].tolist()
        if offset is None:
            return {}, 'unverified'
        times = np.linspace(start, end, max(2, int(np.ceil((end-start)*192))+1))
        points = world_positions(doc['nodes'], tracks, {'palm': palm}, times, {'palm': offset})
        error = float(np.max(np.linalg.norm(points['palm'] - contact['palm_target'], axis=1)))
        if not np.isfinite(error) or error > height*.015:
            return {}, 'unverified'
        ends = world_positions(doc['nodes'], tracks, {'root': root}, np.array([0., duration]))['root']
        updated_box = {**box, 'heading': box.get('heading',box['travel']), 'travel': (ends[1]-ends[0]).tolist()}
        updated_contact = {**contact, 'palm_offset': offset, 'interval_s': [start, end], 'max_sample_error_m': error}
        updated_contact.pop('max_key_error_m', None)
        return {'obstacle': updated_box, 'contact': updated_contact}, 'verified'
    except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError, np.linalg.LinAlgError):
        return {}, 'unverified'


def sync_guides(stage, result):
    report = result['motion_report']
    old_name, new_name = report['options']['clip'], report['clip']
    fields = ('obstacle','contact')
    source = validate_glb(stage/'source.glb')
    recipes = result.get('animation_set', [])
    hints = {item.get('clip'): {key: item[key] for key in fields if key in item} for item in recipes}
    for clip in source.get('animations', []):
        extra = clip.get('extras', {})
        if isinstance(extra, dict):
            old = hints.setdefault(clip.get('name'), {})
            old.update({key: extra['trellis_'+key] for key in fields if 'trellis_'+key in extra})
    if not any(hints.values()):
        return
    path = stage/'model.glb'
    doc, binary = read(path)
    edited = next((clip for clip in doc.get('animations', []) if clip.get('name') == new_name), None)
    if edited is None:
        raise ValueError('The edited animation is missing from its exported GLB.')
    guide = hints.pop(old_name, {})
    if guide:
        guide, status = retime_guide(guide.get('obstacle'), guide.get('contact'), doc, binary, edited,
                                     report, result['height_m'])
        report['obstacle_contact_status'] = status
        for item in recipes:
            if item.get('clip') == old_name:
                for key in fields:
                    item.pop(key, None)
                item.update(guide)
        hints[new_name] = {key: guide.get(key) for key in fields}
    # Blender may drop animation extras on sibling actions during re-export.
    restored = {name: {'trellis_'+key: value for key, value in data.items()}
                for name, data in hints.items() if data}
    rewrite_animation_names(path, path, {}, clip_extras=restored)
