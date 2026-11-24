"""Generation plans and export receipts. Historical versions come only from asset records."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def fields(value):
    return value if isinstance(value, dict) else {}


@lru_cache(maxsize=12)
def catalogue(filename):
    return json.loads((ROOT / 'installer' / filename).read_text(encoding='utf-8'))


def capture_generation(settings, preferred=None, capability=None):
    """Persist build pins at submission, separate from revisions observed at execution."""
    engine = settings.get('workflow_id') or settings.get('engine') or 'trellis2'
    texture = settings.get('texture_method') or 'trellis'
    revision = {}
    if engine == 'high_detail_native':
        hd = catalogue('native-high-detail-manifest.json')
        revision.update(geometry_weights=hd['weights_revision'], geometry_runtime=hd['pipeline']['revision'],
                        quantization=hd['quantization']['revision'])
    if engine == 'pixal3d' or settings.get('geometry_backend') == 'pixal3d':
        revision['pixal_weights'] = catalogue('pixal3d-manifest.json')['weights_revision']
    elif engine == 'trellis2':
        revision['engine_source'] = catalogue('manifest.json')['sources']['engine']['commit']
    if settings.get('facial_head_enhancement'):
        revision['topos'] = catalogue('facial-head-manifest.json')['topos_revision']
    if str(settings.get('master_finishing','')).startswith('hi3d_'):
        revision['hi3d_runtime'] = catalogue('hi3d-manifest.json')['source']['revision']
    if texture == 'ultratex':
        if engine in ('high_detail_native', 'game_asset_native'):
            revision.update(catalogue('native-ultratex-manifest.json')['source_revisions'])
        else:
            revision.update({s['id']: s['revision'] for s in catalogue('ultratex-manifest.json')['sources']})
    elif texture == 'multiview':
        mv = catalogue('multiview-texture-manifest.json')
        revision.update(adapter=mv['adapter_revision'], base=mv['base_revision'], runtime=mv['source']['revision'])
    plan = dict(engine=engine, requested_texture=preferred or texture, selected_texture=texture, installation_pins=revision)
    if preferred and preferred != texture:
        support = fields(capability)
        plan['fallback'] = dict(stage='before_generation', requested=preferred, used=texture,
                                code=support.get('reason_code') or 'selection_adjusted',
                                reason=support.get('reason') or 'Texture method adjusted before submission')
    settings['generation_plan'] = plan


def conditions(engine, pipeline, texture):
    result = []
    if any(component in str(engine).lower() for component in ('trellis', 'pixal3d')):
        for component, filename in [('DINOv3', 'DINOv3-LICENSE.md'), ('TRELLIS', 'TRELLIS-MIT.txt')]:
            result.append(dict(component=component, document=filename,
                               sha256=hashlib.sha256((ROOT/'licenses'/filename).read_bytes()).hexdigest()))
    if texture == 'ultratex':
        license_info = catalogue('ultratex-manifest.json')['license']
        result.append(dict(component='FLUX.2 Klein Base 9B', document='FLUX.2-klein-base-9B-LICENSE.md',
                           url=license_info['url'], sha256=license_info['sha256']))
    if texture == 'multiview':
        result.append(dict(component='Stable Diffusion 2.1', license='CreativeML Open RAIL++-M',document='Stable-Diffusion-2.1-OpenRAIL++-M.txt',
                           sha256=hashlib.sha256((ROOT/'licenses/Stable-Diffusion-2.1-OpenRAIL++-M.txt').read_bytes()).hexdigest()))
    if pipeline == 'high_detail_native':
        result.append(dict(component='MeshLib', url='https://github.com/MeshInspector/MeshLib/blob/df34d41cbdbeb8343aeecdfd5755a361e5dc291d/LICENSE'))
    return result


def revisions_in(record, prefix=''):
    revisions = {}
    for key, value in fields(record).items():
        path = prefix + key
        if isinstance(value, dict):
            revisions.update(revisions_in(value, path + '.'))
        elif (isinstance(value, (str, int)) and not isinstance(value, bool)
              and (key.endswith(('revision', 'workflow_sha256')) or key == 'commit' or prefix.endswith('revisions.'))):
            revisions[path] = value
    return revisions


def export_provenance(settings, result, inherited=None):
    settings, result = fields(settings), fields(result)
    base = fields(inherited)
    workflow, finishing = fields(result.get('workflow')), fields(result.get('finishing'))
    plan = fields(settings.get('generation_plan'))
    stage = fields(fields(settings.get('workflow_options')).get('25'))
    requested = plan.get('requested_texture') or stage.get('texture_method') or settings.get('texture_method')
    if not requested and settings.get('multiview_texture_refinement'):
        requested = 'multiview'
    engine = workflow.get('engine') or result.get('engine') or base.get('used_engine')
    pipeline = result.get('pipeline_type') or base.get('pipeline')
    used = workflow.get('texture_method') or result.get('texture_method') or base.get('used_texture')
    fallbacks = list(base.get('fallbacks') or [])
    if fields(plan.get('fallback')) and plan['fallback'] not in fallbacks:
        fallbacks.append(plan['fallback'])
    for source, inferred in [(workflow.get('texture'), used),
                             (finishing.get('multiview_texture_refinement'), 'multiview'),
                             (finishing.get('ultratex_texture_refinement'), 'ultratex'),
                             (result.get('multiview_texture_refinement'), 'multiview'),
                             (result.get('ultratex_texture_refinement'), 'ultratex')]:
        receipt = fields(source)
        method = receipt.get('texture_method') or inferred
        if receipt.get('state') == 'skipped':
            used = 'trellis'
            entry = dict(stage='execution', requested=method, used=used,
                         reason=receipt.get('reason') or 'Optional texture pass skipped')
            if entry not in fallbacks:
                fallbacks.append(entry)
        elif receipt.get('state') == 'applied':
            used = method
        if receipt and (source is result.get('multiview_texture_refinement') or source is result.get('ultratex_texture_refinement')):
            requested = method
    revisions = {**fields(base.get('recorded_revisions')), **revisions_in(result)}
    pins = plan.get('installation_pins') or base.get('submission_pins') or {}
    required = conditions(engine, pipeline, used)
    if fields(result.get('facial_head_enhancement')).get('state') == 'applied':
        required.extend([
            dict(component='TOPOS',url='https://github.com/ymxbj/TOPOS/blob/581ad9e218cc7559072960ea44464014c808cef3/LICENSE'),
            dict(component='DINOv2',url='https://github.com/facebookresearch/dinov2/blob/7764ea0f912e53c92e82eb78a2a1631e92725fc8/LICENSE'),
            dict(component='MediaPipe Face Mesh',url='https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf')])
    if 'hi3d' in str(finishing.get('method','')).lower():
        required.append(dict(component='Hi3D', document='Hi3D-1.0-LICENSE.md',
                             sha256=hashlib.sha256((ROOT/'licenses/Hi3D-1.0-LICENSE.md').read_bytes()).hexdigest()))
    for prior in base.get('component_conditions') or []:
        if prior not in required:
            required.append(prior)
    return dict(schema=2, requested_engine=plan.get('engine') or settings.get('workflow_id') or
                settings.get('engine') or fields(settings.get('profile_snapshot')).get('engine') or base.get('requested_engine'),
                used_engine=engine, pipeline=pipeline, requested_texture=requested or base.get('requested_texture'),
                used_texture=used, fallback=(fallbacks[-1]['reason'] if fallbacks else None), fallbacks=fallbacks,
                restored_asset_revision=settings.get('restored_revision') or base.get('restored_asset_revision'),
                recorded_revisions=revisions, submission_pins=pins, component_conditions=required,
                missing_evidence=[name for name,value in [('engine',engine),('texture',used),('runtime_revision',
                    any(key != 'revision' for key in revisions))] if not value])
