"""Derived model operations shared by the desktop and private server workspaces."""
import asyncio
import shutil
import time
import uuid

from fastapi import HTTPException
from PIL import Image

from api_contract import (
    BakedGameCopy, GenerationReferenceTextureProjection, GenerationViewTextureProjection, Identifier,
    JobAccepted, MultiViewTextureProjection, TextureProjectionRequest,
)
from generation_view_projection import (
    digest, generation_reference, generation_reference_name, inspect_generation_reference, inspect_generation_views,
)
from studio_workspace import write


REFERENCE_LABELS = {
    'prepared': 'Cutout reference',
    'conditioning': 'Generation reference',
    'input': 'Original reference',
}


def existing_file(folder, name):
    path = folder / name
    return path if path.is_file() and path.resolve().parent == folder.resolve() else None


def check_reference_sizes(paths, max_pixels):
    for index, path in enumerate(paths, start=1):
        try:
            with Image.open(path) as image:
                pixels = image.width * image.height
        except Image.DecompressionBombError:
            pixels = max_pixels + 1
        except (OSError, ValueError):
            raise HTTPException(400, f'Choose a readable reference image for view {index}.') from None
        if pixels > max_pixels:
            raise HTTPException(400, f'Resize the reference for view {index} to at most 16 megapixels.')


def install(router, app, upload):
    services = app['STUDIO']

    def model(identifier):
        folder, record = services.available(identifier)
        path = existing_file(folder, 'model.glb')
        if not path:
            raise HTTPException(409, 'Choose a completed model with a GLB file.')
        return folder, record, path

    def references(folder):
        return [
            dict(id=key, label=label, url=f'/api/v1/models/{folder.name}/files/{key}.png')
            for key, label in REFERENCE_LABELS.items() if existing_file(folder, f'{key}.png')
        ]

    async def prepare_copy(folder, record, source, operation, *, options=None, projections=(), generation_views=None,
                           generation_cutout=None):
        target = app['OUTPUT'] / uuid.uuid4().hex
        label = 'Texture projection' if operation == 'texture_projection' else 'Baked game copy'
        settings = {
            **record['settings'],
            'parent_id': folder.name,
            'source_kind': operation,
            'asset_type': 'imported',
            'created': time.time(),
        }
        for key in ('finish_source_id', 'keep_finishing_source', 'bake_normals',
                    'normal_source', 'normal_source_id', 'normal_source_model_sha256',
                    'normal_source_normalization', 'repair_surface', 'hd_reconstruction', 'wtivo_reconstruction',
                    'master_finishing'):
            settings.pop(key, None)
        if operation == 'baked_game_copy':
            settings.update(triangles=options['triangles'], texture_size=options['texture_size'])
        metadata = {**record['metadata'], 'review_state': 'review', 'favorite': False}
        display = metadata.get('display_name') or settings['name']
        suffix = ' · ' + label
        metadata['display_name'] = display[:80 - len(suffix)].rstrip() + suffix
        request = dict(operation=operation, result=record.get('result') or {})
        staged_references = {}
        projection_requests = []
        for index, (reference, view_options) in enumerate(projections, start=1):
            numbered = f'-{index}' if len(projections) > 1 else ''
            name = f'projection-source{numbered}{reference.suffix.lower()}'
            staged_references[name] = reference
            projection_requests.append(dict(reference_file=name, options=view_options))
        if generation_views is not None:
            request['generation_views'] = generation_views
        elif len(projection_requests) > 1:
            request['views'] = projection_requests
        elif projection_requests:
            request.update(projection_requests[0])
        else:
            request['options'] = options

        def stage():
            target.mkdir()
            retained = generation_views
            if retained is None and record['settings'].get('engine') == 'pixal3d':
                _, retained = inspect_generation_views(folder, source, record['settings'], True, '')
            if generation_cutout is not None:
                request['generation_reference'] = dict(source_sha256=digest(source),
                                                       reference_sha256=digest(generation_cutout))
            shutil.copy2(source, target / 'source.glb')
            for key in REFERENCE_LABELS:
                path = existing_file(folder, f'{key}.png')
                if path:
                    shutil.copy2(path, target / path.name)
            for name, reference in staged_references.items():
                shutil.copy2(reference, target / name)
            if retained is not None:
                request['retained_generation_views'] = retained
                for view in retained['views']:
                    role = view['role']
                    if role != 'front':
                        shutil.copy2(generation_reference(folder, role), target / generation_reference_name(role))
            if generation_views is not None:
                for view in generation_views['views']:
                    role = view['role']
                    shutil.copy2(generation_reference(folder, role),
                                 target / generation_reference_name(role, staged=True))
            write(target / 'settings.json', settings)
            write(target / 'metadata.json', metadata)
            write(target / 'finishing-request.json', request)
            write(target / 'status.json', dict(state='queued', stage=label, progress=0, operation=operation))

        try:
            await asyncio.to_thread(stage)
            app['launch_worker'](target, 'model_finishing_worker.py', source_id=folder.name)
        except (OSError, ValueError):
            if target.is_dir() and target.resolve() == target and target.parent == app['OUTPUT']:
                await asyncio.to_thread(shutil.rmtree, target, ignore_errors=True)
            raise HTTPException(500, 'Could not prepare the derived model. Check available disk space.') from None
        return dict(id=target.name, state='queued', status_url=f'/api/v1/jobs/{target.name}')

    @router.get('/models/{identifier}/texture-projection', tags=['Models'],
                summary='Check support for texture projection on a static model')
    async def projection_options(identifier: Identifier):
        from texture_projection import MAX_REFERENCE_PIXELS, inspect_texture_projection
        folder, record, source = model(identifier)
        support = await asyncio.to_thread(inspect_texture_projection, source)
        calibrated, _ = await asyncio.to_thread(inspect_generation_views, folder, source, record['settings'],
                                                support['supported'], support['reason'])
        aligned, _ = await asyncio.to_thread(inspect_generation_reference, folder, record,
                                              support['supported'], support['reason'], MAX_REFERENCE_PIXELS)
        return {**support, 'references': references(folder), 'max_views': 2,
                'views': ['front', 'back', 'left', 'right', 'top', 'bottom', 'custom'],
                'camera_projections': ['orthographic', 'perspective'],
                'linked_selection': True, 'mask_shapes': ['ellipse', 'rectangle', 'polygon'],
                'generation_views': calibrated, 'generation_reference': aligned}

    @router.post('/models/{identifier}/texture-projection', tags=['Models'], status_code=202,
                 response_model=JobAccepted, summary='Project manual or saved generation views onto a linked copy')
    async def project(identifier: Identifier, recipe: TextureProjectionRequest):
        from texture_projection import MAX_REFERENCE_PIXELS, inspect_texture_projection, normalize_projection_options
        if isinstance(recipe, GenerationViewTextureProjection):
            async with app['LOCK']:
                app['require_idle']()
                folder, record, source = model(identifier)
                support = await asyncio.to_thread(inspect_texture_projection, source)
                calibrated, provenance = await asyncio.to_thread(inspect_generation_views, folder, source,
                                                                   record['settings'], support['supported'], support['reason'])
                if not calibrated['supported']:
                    raise HTTPException(400, calibrated['reason'])
                return await prepare_copy(folder, record, source, 'texture_projection', generation_views=provenance)
        views = recipe.views if isinstance(recipe, MultiViewTextureProjection) else [recipe]
        try:
            options = [normalize_projection_options(
                view.model_dump(mode='json', exclude={'reference', 'upload_id', 'method'}, exclude_none=True))
                for view in views]
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        async with app['LOCK']:
            app['require_idle']()
            folder, record, source = model(identifier)
            support = await asyncio.to_thread(inspect_texture_projection, source)
            if not support['supported']:
                raise HTTPException(400, support['reason'])
            if isinstance(recipe, GenerationReferenceTextureProjection):
                aligned, cutout = await asyncio.to_thread(inspect_generation_reference, folder, record,
                                                           support['supported'], support['reason'], MAX_REFERENCE_PIXELS)
                if cutout is None:
                    raise HTTPException(400, aligned['reason'])
                return await prepare_copy(folder, record, source, 'texture_projection',
                                          projections=[(cutout, options[0])], generation_cutout=cutout)
            paths = []
            for view in views:
                if view.upload_id:
                    reference, _ = upload(view.upload_id, 'image')
                    reference = existing_file(reference.parent, reference.name)
                else:
                    reference = existing_file(folder, f'{view.reference}.png')
                if not reference or reference.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
                    raise HTTPException(400, 'Choose an available reference image first.')
                paths.append(reference)
            if len(paths) > 1:
                await asyncio.to_thread(check_reference_sizes, paths, MAX_REFERENCE_PIXELS)
            return await prepare_copy(folder, record, source, 'texture_projection',
                                      projections=list(zip(paths, options, strict=True)))

    @router.get('/models/{identifier}/baked-game-copy', tags=['Models'],
                summary='Check support for a reduced and baked copy of the selected master')
    async def game_options(identifier: Identifier):
        from baked_game_copy import inspect_baked_game_copy
        _, record, source = model(identifier)
        support = await asyncio.to_thread(inspect_baked_game_copy, source)
        humanoid = ((record['metadata'].get('asset_type') or record['settings'].get('asset_type')) == 'humanoid'
                    and 'humanoid' in support.get('profiles', ('humanoid',)))
        return {**support, 'humanoid': humanoid, 'default_triangles': 14000 if humanoid else 28000}

    @router.post('/models/{identifier}/baked-game-copy', tags=['Models'], status_code=202,
                 response_model=JobAccepted, summary='Make a reduced copy with materials baked from the selected master')
    async def make_game_copy(identifier: Identifier, recipe: BakedGameCopy):
        from baked_game_copy import inspect_baked_game_copy, normalize_game_copy_options
        try:
            options = normalize_game_copy_options(recipe.model_dump(mode='json'))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        async with app['LOCK']:
            app['require_idle']()
            folder, record, source = model(identifier)
            support = await asyncio.to_thread(inspect_baked_game_copy, source)
            if not support['supported']:
                raise HTTPException(400, support['reason'])
            if not support.get('ready', True):
                raise HTTPException(503, 'Install Blender and PyMeshLab to create a baked game copy.')
            if options['profile'] not in support.get('profiles', ('object', 'humanoid')):
                raise HTTPException(400, 'Choose Object or use an upright, frontal T-pose for the humanoid profile.')
            return await prepare_copy(folder, record, source, 'baked_game_copy', options=options)
