"""Desktop tools for adapting tentacle chains and authoring a swim clip."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import uuid

from fastapi import HTTPException, Request

from animation_edits import publish_operation
from creature_rig import REVISION, is_creature_rig, validate_creature_bones
from creature_swim import SWIM_CLIP_NAME, swim_compatible, swim_options, validate_swim_options, write_swim
from creature_tentacles import adapt_tentacles, validate_tentacle_spacing
from lod_animations import prepare as prepare_lod_animations
from studio_import import validate_glb
from studio_workspace import read, write


async def read_options(request):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 16 * 1024:
            raise HTTPException(413, 'The creature options are too large.')
        body.extend(chunk)
    try:
        value = json.loads(body) if body else {}
    except (ValueError, RecursionError) as error:
        raise HTTPException(400, 'The creature options must be JSON.') from error
    if not isinstance(value, dict):
        raise HTTPException(400, 'The creature options must be an object.')
    return value


def swim_result(previous, report):
    animations = [item for item in previous.get('animation_set', []) if item.get('clip') != SWIM_CLIP_NAME]
    animations.append(dict(id='creature_swim', name=SWIM_CLIP_NAME, clip=SWIM_CLIP_NAME,
                           duration_s=report['duration_s'], source='TRELLIS Studio creature swim'))
    return dict(previous, revision=time.time_ns(), animation_set=animations, creature_swim=report)


def apply_swim(folder, record, options):
    source = folder / 'model.glb'
    revision = str(source.stat().st_mtime_ns)
    with TemporaryDirectory(prefix='.creature-swim-', dir=folder) as directory:
        stage = Path(directory) / uuid.uuid4().hex
        stage.mkdir()
        report = write_swim(source, stage / 'model.glb', options)
        result = swim_result(record.get('result') or {}, report)
        result['animations'] = len(validate_glb(stage / 'model.glb').get('animations', []))
        write(stage / 'settings.json', record['settings'])
        write(stage / 'result.json', result)
        files = ['model.glb', 'settings.json', 'result.json', *prepare_lod_animations(folder, stage)]
        publish_operation(folder, stage, dict(result=result, updated_files=files), revision,
                          glb_authoritative=True)
    return report


def install(app, g):
    def require_desktop():
        if g['WORKSPACE_CONFIG']:
            raise HTTPException(404, 'Creature tools are available in Studio Desktop.')

    def completed_model(identifier):
        folder = g['job_path'](identifier)
        record = g['job_record'](folder)
        if not record or record['state'] != 'done' or not record['media'].get('available'):
            raise HTTPException(409, 'Choose a completed creature model.')
        path = folder / 'model.glb'
        if not path.is_file() or path.resolve() != path:
            raise HTTPException(409, 'The creature GLB is unavailable.')
        return folder, record, path

    @app.post('/api/jobs/{identifier}/rig-tentacles')
    async def rig_tentacles(identifier: str, request: Request):
        require_desktop()
        payload = await read_options(request)
        revision = payload.get('revision')
        if set(payload) - {'revision', 'spacing_m'} or not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise HTTPException(400, 'A creature draft preview revision is required.')
        try:
            spacing = validate_tentacle_spacing(payload.get('spacing_m', .19))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        async with g['LOCK']:
            g['require_idle']()
            folder = g['job_path'](identifier)
            record = g['job_record'](folder)
            if (not record or not is_creature_rig(record['settings'])
                    or not (record['state'] == 'done' and record.get('rig_phase') == 'draft'
                            or record['state'] in ('error', 'cancelled'))):
                raise HTTPException(409, 'Select an editable creature rig draft.')
            draft = folder / 'rig-preview.json'
            source = folder / 'source.glb'
            if any(not file.is_file() or file.resolve() != file for file in (draft, source)):
                raise HTTPException(409, 'The predicted skeleton is unavailable. Create a new creature draft.')
            if g['rig_source_digest'](draft) != revision:
                raise HTTPException(409, 'The creature draft has changed. Open the current preview and try again.')
            fingerprint = record['settings'].get('rig_source_sha256')
            if fingerprint and await asyncio.to_thread(g['rig_source_digest'], source) != fingerprint:
                raise HTTPException(409, 'The rig source changed. Create a new variant from the source model.')
            try:
                proposal = await asyncio.to_thread(adapt_tentacles, source, read(draft)['bones'], spacing)
                proposal['bones'] = validate_creature_bones(proposal['bones'])
                proposal['revision'] = revision
                write(folder / 'creature-tentacles.json', proposal)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            except OSError as error:
                raise HTTPException(503, 'The tentacle proposal could not be saved.') from error
        return proposal

    @app.get('/api/jobs/{identifier}/creature-swim')
    async def creature_swim_options(identifier: str):
        require_desktop()
        _, _, path = completed_model(identifier)
        data = await asyncio.to_thread(validate_glb, path)
        compatible = swim_compatible(data)
        return dict(compatible=compatible, options=swim_options(data), clip_name=SWIM_CLIP_NAME,
                    reason='' if compatible else 'Adapt the tentacles on a creature draft to enable swimming.')

    @app.post('/api/jobs/{identifier}/creature-swim')
    async def set_creature_swim(identifier: str, request: Request):
        require_desktop()
        try:
            options = validate_swim_options(await read_options(request))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        async with g['LOCK']:
            g['require_idle']()
            g['refresh_export']()
            if identifier in g['EXPORTING']:
                raise HTTPException(409, 'Wait for the export to finish before changing the swim clip.')
            folder, record, path = completed_model(identifier)
            if not swim_compatible(await asyncio.to_thread(validate_glb, path)):
                raise HTTPException(409, 'Adapt the tentacles on a creature draft to enable swimming.')
            try:
                report = await asyncio.to_thread(apply_swim, folder, record, options)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            except OSError as error:
                raise HTTPException(503, 'Unable to save the swim clip. The previous model was preserved.') from error
        return dict(id=identifier, options=report['options'], clip_name=SWIM_CLIP_NAME,
                    duration_s=report['duration_s'])
