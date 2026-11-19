"""One generation per process: release CUDA and RAM fully after each object."""
from pathlib import Path
import gc, hashlib, json, os, sys, time, traceback

ROOT = Path(__file__).resolve().parent
JOB = Path(sys.argv[1]).resolve()
settings = json.loads((JOB / 'settings.json').read_text(encoding='utf-8'))
requested_resolution = int(settings.get('resolution',512))
os.environ.update({
    'ATTN_BACKEND': 'sdpa', 'SPARSE_ATTN_BACKEND': 'xformers',
    'TRELLIS_NO_REMBG': '1', 'TRELLIS_UV_RASTERIZER': 'torch',
    'TRELLIS_MAX_RESOLUTION': str(requested_resolution), 'HF_HUB_OFFLINE': '1',
    'HF_HUB_DISABLE_TELEMETRY': '1', 'TRANSFORMERS_OFFLINE': '1',
    'U2NET_HOME': str(ROOT / 'models' / 'rembg'),
    'HF_HOME': str(ROOT / 'models' / 'hf'),
    'TORCH_HOME': str(ROOT / 'models' / 'torch'),
    'PYTORCH_CUDA_ALLOC_CONF': 'garbage_collection_threshold:0.65',
    'TORCHDYNAMO_DISABLE': '1', 'OPENCV_IO_ENABLE_OPENEXR': '1',
    'PYTHONUTF8': '1',
})
sys.path[:0] = [str(ROOT), str(ROOT / 'engine'), str(ROOT / 'engine' / 'o-voxel')]
os.chdir(ROOT / 'engine')
from generation_options import (options_for_job, sampler_options, export_options, configure_simplifier,
                                DENSE_MASTER, MASTER_FINISHING_METHODS, MASTER_FINISHING_TRIANGLES,
                                TRIANGLE_MIN, validate_hd_reconstruction)
from gpu_runtime import configure_attention, select_gpu
from hi3d_runtime import HI3D_METHODS, hi3d_source_status
from studio_workspace import write

select_gpu(ROOT)
options = options_for_job(settings)
started = time.time()

def status(state, stage, progress, **extra):
    record = dict(state=state, stage=stage, progress=progress, elapsed=round(time.time()-started, 1), **extra)
    tmp = JOB / 'status.tmp'
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    tmp.replace(JOB / 'status.json')
    print(f'STAGE {progress}% {stage}', flush=True)

def generate_source(torch):
    status('running', 'Preparing image', 3)
    from PIL import Image, ImageOps
    reviewed = 'reference_edits' in settings
    if reviewed:
        with Image.open(JOB / 'conditioning.png') as prepared:
            image = prepared.convert('RGB')
    else:
        with Image.open(JOB / 'input.png') as original:
            image = ImageOps.exif_transpose(original).convert('RGBA')
        if settings.get('remove_bg') and image.getchannel('A').getextrema()[0] == 255:
            from rembg import new_session, remove
            session = new_session('u2net', providers=['CPUExecutionProvider'])
            image = remove(image, session=session)
            del session
            gc.collect()
        image.save(JOB / 'prepared.png')
    status('running', 'Loading model weights', 8)
    from api_spz.core.state_manage import _apply_patches
    _apply_patches()
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    from studio_pipeline import prepare_pipeline_config
    config_folder,pipeline_kind=prepare_pipeline_config(ROOT,JOB,requested_resolution)
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(str(config_folder))
    pipeline.cuda()
    if settings.get('keep_finishing_source') and not reviewed:
        prepare_image = pipeline.preprocess_image
        def record_conditioning(image):
            prepared = prepare_image(image)
            prepared.save(JOB / 'conditioning.png')
            return prepared
        pipeline.preprocess_image = record_conditioning
    for method, stage, percent in [
        ('get_cond', 'Analysing image', 16),
        ('sample_sparse_structure', 'Building volume', 24),
        ('sample_shape_slat', 'Generating geometry', 39),
        ('sample_tex_slat', 'Generating materials', 58),
        ('decode_and_cleanup', 'Extracting mesh', 73),
    ]:
        original = getattr(pipeline, method)
        def wrap(*args, _original=original, _stage=stage, _percent=percent, **kwargs):
            status('running', _stage, _percent)
            if _stage=='Generating materials' and options['texture_seed']>=0:
                torch.manual_seed(options['texture_seed'])
            return _original(*args, **kwargs)
        setattr(pipeline, method, wrap)
    samplers = sampler_options(options)
    print('GENERATION_OPTIONS '+json.dumps(options,ensure_ascii=False),flush=True)
    shape, texture, resolution = pipeline.run(
        image, seed=settings['seed'], pipeline_type=pipeline_kind, return_before_decode=True,
        preprocess_image=not reviewed,
        sparse_structure_sampler_params=samplers['structure'],
        shape_slat_sampler_params=samplers['shape'], tex_slat_sampler_params=samplers['texture'],
    )
    mesh = pipeline.decode_and_cleanup(shape, texture, resolution)[0]
    del shape, texture, pipeline
    gc.collect()
    torch.cuda.empty_cache()
    return dict(vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs.cpu(),
                coords=mesh.coords.cpu(), attr_layout=mesh.layout,
                voxel_size=float(mesh.voxel_size), resolution=int(resolution)), pipeline_kind


def save_finishing_source(torch, source):
    # Cache the decoded surface before the first simplification.
    status('running', 'Saving reusable finishing source', 77)
    cpu_source = {
        key: value.detach().cpu().contiguous() if isinstance(value, torch.Tensor) else value
        for key, value in source.items()
    }
    pending = JOB / 'raw_state.pending.pt'
    try:
        torch.save(cpu_source, pending)
        pending.replace(JOB / 'raw_state.pt')
    finally:
        pending.unlink(missing_ok=True)


def load_finishing_source(torch, identifier):
    import re
    if not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Invalid finishing source.')
    folder = JOB.parent / identifier
    if folder.resolve().parent != JOB.parent:
        raise ValueError('Invalid finishing source directory.')
    # Both the Studio and the original local pilot use only tensors, scalars and slices.
    with torch.serialization.safe_globals([slice]):
        return torch.load(folder / 'raw_state.pt', map_location='cpu', weights_only=True)


def hi3d_reference(source_id, source_resolution):
    folder = JOB
    if source_id:
        from studio_workspace import ID
        if not isinstance(source_id, str) or not ID.fullmatch(source_id):
            raise ValueError('Invalid Hi3D finishing source.')
        folder = JOB.parent / source_id
        if folder.resolve() != folder:
            raise ValueError('Invalid Hi3D finishing source directory.')
    capability = hi3d_source_status(folder, source_resolution, require_cache=bool(source_id))
    if not capability['available']:
        raise ValueError(capability['reason'])
    return folder / 'prepared.png'


def finish_mesh(torch, source, source_id=None):
    status('running', 'Finishing mesh and baking textures', 83)
    hd_reconstruction = settings.get('hd_reconstruction', False)
    validate_hd_reconstruction(hd_reconstruction, preset=settings.get('preset'), resolution=int(source['resolution']),
                               repair_surface=settings.get('repair_surface', False),
                               refinish=settings.get('source_kind') == 'refinish')
    from wtivo_runtime import reconstruct, validate_wtivo_recipe
    wtivo = settings.get('wtivo_reconstruction', False)
    master_finishing = settings.get('master_finishing')
    hi3d_resolution = HI3D_METHODS.get(master_finishing)
    refinish = settings.get('source_kind') == 'refinish'
    triangle_ceiling = settings['triangles']
    source_resolution = int(source['resolution'])
    if master_finishing is not None and (
            master_finishing not in MASTER_FINISHING_METHODS or not (refinish or settings.get('preset') == DENSE_MASTER)
            or (not hi3d_resolution and source_resolution < 1024)
            or not TRIANGLE_MIN <= triangle_ceiling <= MASTER_FINISHING_TRIANGLES
            or wtivo != (master_finishing == 'wtivo_1024') or hd_reconstruction != (master_finishing == 'studio_768')
            or any(settings.get(key) for key in ('adaptive_finishing', 'repair_surface', 'bake_normals'))):
        raise ValueError('Invalid HD Master Finishing recipe.')
    validate_wtivo_recipe(wtivo, int(source['resolution']), refinish=refinish, inline_master=bool(master_finishing),
                          hd_reconstruction=hd_reconstruction, repair_surface=settings.get('repair_surface', False),
                          adaptive=settings.get('adaptive_finishing', False), budget_preset=settings.get('budget_preset'))
    wtivo_report = None
    trim_report = None
    hi3d_report = None
    if hi3d_resolution:
        from hi3d_runtime import reconstruct as refine_hi3d

        if (settings.get('engine', 'trellis2') != 'trellis2'
                or settings.get('view_mode', 'single') != 'single'
                or source.get('coordinate_system', 'z_up') != 'z_up'):
            raise ValueError('Hi3D requires a native TRELLIS.2 single-image source.')
        reference = hi3d_reference(source_id, source_resolution)
        status('running', f'Refining the decoded surface with Hi3D {hi3d_resolution}', 84)
        for key in ('vertices', 'faces'):
            source[key] = source[key].detach().cpu()
        gc.collect()
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        rebuilt_vertices, rebuilt_faces, hi3d_report = refine_hi3d(
            ROOT, JOB, reference, source['vertices'].numpy(), source['faces'].numpy(),
            hi3d_resolution, triangle_ceiling, source_resolution=source_resolution)
        status('running', 'Baking native materials onto the refined mesh', 87)
    if wtivo:
        status('running', 'Reconstructing the surface with WTiVo 1024', 84)
        torch.cuda.empty_cache()
        rebuilt_vertices, rebuilt_faces, wtivo_report = reconstruct(
            ROOT, JOB, source['vertices'].cpu().numpy(), source['faces'].cpu().numpy())
        if master_finishing:
            from master_mesh import trim_wtivo_master
            status('running', 'Trimming the dense WTiVo surface in Blender', 84)
            rebuilt_vertices, rebuilt_faces, trim_report = trim_wtivo_master(
                ROOT, JOB, rebuilt_vertices, rebuilt_faces, triangle_ceiling)
        status('running', 'Finishing the WTiVo master' if master_finishing else 'Reducing and baking the WTiVo mesh', 84)
    import cumesh
    import o_voxel
    configure_simplifier(cumesh, options)
    # All paths use the same bundled exporter, including installations with older
    # engines. This keeps validated finishing controls and provenance consistent.
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location('o_voxel._studio_postprocess',
        ROOT / 'runtime' / 'engine-overrides' / 'o_voxel' / 'postprocess.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    export = module.to_glb
    export_kwargs = export_options(options)
    if master_finishing:
        export_kwargs['master_finishing'] = True
    if wtivo or hi3d_report:
        replacement_vertices = torch.from_numpy(rebuilt_vertices)
        replacement_faces = torch.from_numpy(rebuilt_faces)
        if hi3d_report and len(replacement_faces) > hi3d_report['triangle_target']:
            replacement_mesh = cumesh.CuMesh()
            replacement_mesh.init(replacement_vertices.cuda(), replacement_faces.cuda())
            replacement_mesh.simplify(hi3d_report['triangle_target'], verbose=True)
            replacement_vertices, replacement_faces = replacement_mesh.read()
            del replacement_mesh
        export_kwargs.update(remesh=False, repair_holes=False,
                             reconstructed_mesh=(replacement_vertices, replacement_faces))
    adaptive = settings.get('adaptive_finishing') is True and not hd_reconstruction
    adaptive_master = adaptive and settings.get('source_kind') != 'refinish'
    repair_surface = settings.get('repair_surface') is True
    if adaptive:
        from adaptive_finishing import choose_master_mesh, choose_mesh
        export_kwargs['adaptive_mesh'] = choose_master_mesh if adaptive_master else choose_mesh
        if not adaptive_master and not repair_surface:
            export_kwargs.update(remesh=False, repair_holes=False)
        if not repair_surface:
            status('running', 'Measuring detail against the master mesh', 84)
    if hd_reconstruction:
        export_kwargs['repair_surface'] = True
        status('running', 'Reconstructing the HD surface at 768', 84)
    elif repair_surface:
        export_kwargs['repair_surface'] = True
        status('running', 'Reconstructing the surface to close holes', 84)
    vertices, faces = source['vertices'].cuda(), source['faces'].cuda()
    if not wtivo and not master_finishing and (not adaptive or adaptive_master) and options['pre_simplify'] and len(faces) > 2000000:
        mesh = cumesh.CuMesh()
        mesh.init(vertices, faces)
        mesh.simplify(2000000)
        vertices, faces = mesh.read()
        del mesh
        torch.cuda.empty_cache()
    result = export(
        vertices=vertices, faces=faces, attr_volume=source['attr_volume'], coords=source['coords'],
        attr_layout=source['attr_layout'], voxel_size=source['voxel_size'],
        aabb=[[-0.5]*3, [0.5]*3], decimation_target=settings['triangles'],
        texture_size=settings['texture_size'], **export_kwargs, verbose=True,
    )
    result.metadata['finishing'].update(
        native_triangles=len(source['faces']), decoded_resolution=int(source['resolution']),
        requested_generation_resolution=requested_resolution,
        pre_simplified=len(faces) != len(source['faces']),
    )
    if hd_reconstruction:
        result.metadata['finishing']['hd_reconstruction'] = True
    if wtivo_report is not None:
        result.metadata['finishing']['wtivo_reconstruction'] = wtivo_report
    if hi3d_report is not None:
        result.metadata['finishing'].update(method=master_finishing, hi3d_refinement=hi3d_report)
        trim_report = dict(method='Hi3D', output_triangles=len(result.faces),
                           triangle_target=hi3d_report['triangle_target'])
    if master_finishing:
        result.metadata['finishing']['master_finishing'] = dict(
            method=master_finishing,
            triangle_ceiling=hi3d_report['triangle_target'] if hi3d_report else triangle_ceiling,
            trim=trim_report or dict(method='CuMesh', output_triangles=len(result.faces)))
    if source.get('coordinate_system') == 'y_up':
        # Pixal3D is already Y-up. Undo O-Voxel's Z-up to Y-up export conversion.
        result.apply_transform([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
    bounds = result.bounds
    height = max(float(bounds[1,1]-bounds[0,1]), 1e-6)
    center = [(bounds[0,0]+bounds[1,0])/2, bounds[0,1], (bounds[0,2]+bounds[1,2])/2]
    scale = settings['height_m'] / height
    # Record the exact final transform for later high-to-low donor alignment.
    # It maps the unscaled Y-up finishing mesh to the exported world coordinates.
    normalization = dict(
        scale=float(scale), translation=[float(-coordinate * scale) for coordinate in center],
        coordinate_system='y_up',
    )
    if hi3d_report and source_id:
        from normal_bake import checked_normalization
        from studio_workspace import read

        try:
            original = read(JOB.parent / source_id / 'result.json', {})
            if original.get('height_m') == settings['height_m']:
                normalization = checked_normalization(original['finishing']['normalization'])
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            # Early cached generations may predate saved world transforms.
            pass
    result.metadata['finishing']['normalization'] = normalization
    if hi3d_report:
        result.vertices *= normalization['scale']
        result.vertices += normalization['translation']
    else:
        result.vertices -= center
        result.vertices *= scale
    pending = JOB / 'model.pending.glb'
    try:
        result.export(pending)
        if settings.get('bake_normals'):
            from normal_bake import bake_master_normals, prepare_parent_normal_source
            status('running', 'Transferring master detail to the normal map', 93)
            normal_source = settings.get('normal_source', 'decoded')
            if normal_source == 'parent':
                donor, provenance = prepare_parent_normal_source(
                    JOB.parent, settings.get('normal_source_id'), settings.get('finish_source_id'),
                    result.metadata['finishing']['normalization'], source['voxel_size'],
                    settings.get('normal_source_model_sha256'), settings.get('normal_source_normalization'),
                )
                normal_report = bake_master_normals(pending, donor, 1., [0., 0., 0.], settings['texture_size'])
                normal_report['donor'] = provenance
            elif normal_source == 'decoded':
                normal_report = bake_master_normals(
                    pending, source, scale, [-coordinate * scale for coordinate in center], settings['texture_size'],
                )
                normal_report['donor'] = dict(kind='decoded', id=settings.get('finish_source_id', JOB.name))
            else:
                raise ValueError('Choose the decoded source or a verified HD parent for normal baking.')
            result.metadata['normal_bake'] = normal_report
        pending.replace(JOB / 'model.glb')
    finally:
        pending.unlink(missing_ok=True)
    return result


def project_requested_face():
    if settings.get('engine') != 'pixal3d' or not settings.get('reproject_face'):
        return None
    status('running', 'Reprojecting the original face', 96)
    try:
        from pixal3d_runtime import verified_face_detector
        detector = verified_face_detector(ROOT)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return {'state': 'skipped', 'reason': 'The verified face detector is unavailable.'}
    try:
        from face_projection import reproject_face
        report = reproject_face(JOB / 'model.glb', JOB / 'input.png', detector)
    except Exception:
        # The optional pass must preserve the successful model and surface failures in its log.
        traceback.print_exc()
        return {'state': 'skipped', 'reason': 'Face reprojection failed. Original texture kept.'}
    print('FACE_PROJECTION ' + json.dumps(report, ensure_ascii=False), flush=True)
    return report


def preserve_master_generation_views(source_id, result):
    if settings.get('engine') != 'pixal3d':
        return
    from generation_view_projection import inspect_generation_views, save_generation_views, verify_generation_view_inputs
    folder = JOB.parent / source_id
    original = folder / 'model.glb'
    capability, provenance = inspect_generation_views(folder, original, settings, True, '')
    if provenance is None:
        print(capability['reason'], flush=True)
        return
    try:
        # Verify that the references copied into this variant still match the saved cameras.
        verify_generation_view_inputs(JOB, original, provenance)
        save_generation_views(JOB, result.metadata['finishing']['normalization'], provenance['views'],
                              camera_model=provenance.get('camera_model'))
    except (OSError, ValueError) as error:
        print(f'Unable to preserve calibrated generation views: {error}', flush=True)


def main():
    import torch
    torch.set_num_threads(6)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable in this environment.')
    configure_attention(torch)
    torch.cuda.reset_peak_memory_stats()
    source_id = settings.get('finish_source_id') if settings.get('source_kind') == 'refinish' else None
    if source_id:
        status('running', 'Loading cached geometry and materials', 10)
        from api_spz.core.state_manage import _apply_patches
        _apply_patches()
        source = load_finishing_source(torch, source_id)
        pipeline_kind = settings.get('pipeline_type')
    else:
        source, pipeline_kind = generate_source(torch)
        if settings.get('keep_finishing_source'):
            save_finishing_source(torch, source)
    resolution = source['resolution']
    result = finish_mesh(torch, source, source_id)
    face_report = project_requested_face()
    if source_id and settings.get('master_finishing'):
        preserve_master_generation_views(source_id, result)
    with (JOB / 'model.glb').open('rb') as model_file:
        result.metadata['finishing']['model_sha256'] = hashlib.file_digest(model_file, 'sha256').hexdigest()
    stats = dict(name=settings['name'], height_m=settings['height_m'], seed=settings['seed'],
                 triangles=len(result.faces), vertices=len(result.vertices), raw_triangles=len(source['faces']),
                 engine='Pixal3D' if settings.get('engine') == 'pixal3d' else 'TRELLIS.2',
                 dimensions_m=result.extents.tolist(), resolution=resolution,
                 requested_resolution=requested_resolution, pipeline_type=pipeline_kind,
                 texture_size=settings['texture_size'], generation_options=options,
                 sampler_options=sampler_options(options), settings_version=2,
                 neural_inferences=0 if source_id else 1,
                 peak_vram_gib=round(torch.cuda.max_memory_allocated()/1024**3, 2),
                 peak_reserved_gib=round(torch.cuda.max_memory_reserved()/1024**3, 2),
                 seconds=round(time.time()-started, 1))
    if face_report is not None:
        stats['face_projection'] = face_report
    if source_id:
        stats['finish_source_id'] = source_id
    if 'adaptive_finishing' in result.metadata:
        stats['adaptive_finishing'] = result.metadata['adaptive_finishing']
    if 'surface_repair' in result.metadata:
        stats['surface_repair'] = result.metadata['surface_repair']
    if 'finishing' in result.metadata:
        stats['finishing'] = result.metadata['finishing']
    if 'normal_bake' in result.metadata:
        report = result.metadata['normal_bake']
        stats['normal_bake'] = report
        stats['vertices'] += report['tangent_vertex_splits']
    write(JOB / 'result.json', stats)
    status('done', 'Finishing variant ready' if source_id else 'Model ready', 100, result=stats)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        traceback.print_exc()
        message = str(error)
        finishing = settings.get('source_kind') == 'refinish'
        if 'out of memory' in message.lower():
            if settings.get('master_finishing'):
                message = 'Insufficient GPU memory for HD Master Finishing. Try a smaller texture size or Studio 768.'
            else:
                message = ('Insufficient GPU memory. Reduce the triangle budget or texture size, then try again.'
                           if finishing else 'Insufficient GPU memory. Reduce 3D resolution (1536 → 1024 → 512) or texture size (4K → 2K), then try again.')
        stage = 'Finishing failed' if finishing else 'Generation failed'
        status('error', stage, 0, error=message[:1400])
        sys.exit(1)
