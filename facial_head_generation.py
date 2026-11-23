"""Opt-in geometry-first facial enhancement, followed by a single material inference."""
import gc
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from facial_head_geometry import face_landmarks, fit_relief, read_topos


def _body_surface(root, job, image, reviewed, options, seed, status):
    import torch
    from api_spz.core.state_manage import _apply_patches
    from generation_options import sampler_options
    from studio_pipeline import prepare_pipeline_config
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    _apply_patches()
    config, kind = prepare_pipeline_config(root, job, 1024)
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(str(config))
    pipeline.cuda()
    torch.manual_seed(seed)
    if not reviewed:
        image = pipeline.preprocess_image(image)
        image.save(job / 'conditioning.png')
    samplers = sampler_options(options)
    pipeline.image_cond_model.to(pipeline.device)
    low = pipeline._cast_cond(pipeline.get_cond([image], 512))
    high = pipeline._cast_cond(pipeline.get_cond([image], 1024))
    pipeline.image_cond_model.cpu()
    torch.cuda.empty_cache()
    status('running', 'Building volume', 24)
    coords = pipeline.sample_sparse_structure(low, 32, 1, samplers['structure'])
    status('running', 'Generating geometry', 39)
    shape, resolution = pipeline.sample_shape_slat_cascade(low, high,
        pipeline.models['shape_slat_flow_model_512'], pipeline.models['shape_slat_flow_model_1024'],
        512, 1024, coords, samplers['shape'])
    del coords, low, high
    shape._spatial_cache.clear()
    torch.cuda.empty_cache()
    decoder = pipeline.models['shape_slat_decoder']
    if pipeline.low_vram:
        decoder.low_vram = True
        decoder.from_latent.to(pipeline.device)
        decoder.output_layer.to(pipeline.device)
    meshes, subs = pipeline.decode_shape_slat(shape, resolution)
    vertices = meshes[0].vertices.detach().cpu().numpy()
    faces = meshes[0].faces.detach().cpu().numpy()
    return vertices, faces, pipeline.pbr_attr_layout, int(resolution), kind


def portrait_conditioning(pipeline, cond, subject, pixels, detection, portrait, resolution):
    """Blend spatial DINO patches inside the face, retaining body and prefix tokens."""
    import torch
    import torch.nn.functional as F

    extractor = pipeline.image_cond_model
    config = extractor.model.config
    patch = config.patch_size
    full_grid, close_grid = resolution // patch, 512 // patch
    tokens = cond['cond']
    prefix = tokens.shape[1] - full_grid**2
    if prefix != 1 + config.num_register_tokens:
        raise ValueError('Unsupported TRELLIS image encoder layout for facial guidance.')
    left, top, right, bottom = subject.getchannel('A').point(lambda value: 255 if value >= 205 else 0).getbbox()
    frame = max(right - left - 1, bottom - top - 1)
    # The native preprocessing centres a square on the silhouette. Token centres
    # below are expressed in the same original-image coordinates as MediaPipe.
    centers = (np.arange(full_grid) + .5) / full_grid - .5
    yy, xx = np.meshgrid(centers * frame + (top + bottom - 1) / 2,
                        centers * frame + (left + right - 1) / 2, indexing='ij')
    xy = np.stack((xx, yy), axis=-1)
    lo, hi = pixels.min(0), pixels.max(0)
    radial = np.linalg.norm((xy - (lo + hi) / 2) / np.maximum((hi - lo) / 2, 1.), axis=-1)
    indices = np.flatnonzero(radial.ravel() < 1.)
    if not len(indices):
        raise ValueError('The source face is too small to guide the material encoder.')
    box = np.asarray(detection['crop_box'], dtype=float)
    if box.shape != (4,) or np.any(box[2:] <= box[:2]):
        raise ValueError('Invalid portrait crop.')
    grid = (xy.reshape(-1, 2)[indices] - box[:2]) / (box[2:] - box[:2]) * 2 - 1
    with Image.open(portrait) as closeup:
        close = pipeline.get_cond([closeup.convert('RGB')], 512, include_neg_cond=False)['cond']
    if close.shape[1] - close_grid**2 != prefix:
        raise ValueError('Unexpected portrait conditioning layout.')
    spatial = close[:, prefix:].transpose(1, 2).reshape(1, -1, close_grid, close_grid)
    coordinates = torch.as_tensor(grid, dtype=torch.float32, device=spatial.device)[None, None]
    sampled = F.grid_sample(spatial.float(), coordinates, padding_mode='border', align_corners=False)[0, :, 0, :].T
    weights = np.clip((1 - radial.ravel()[indices]) * 4, 0, 1) * .65
    selection = torch.as_tensor(indices + prefix, device=tokens.device)
    w = torch.as_tensor(weights[:, None], dtype=tokens.dtype, device=tokens.device)
    tokens[:, selection] = torch.lerp(tokens[:, selection], sampled.to(tokens.dtype)[None], w)
    return cond


def generate(root, job, settings, image, reviewed, options, status):
    import torch
    from facial_head_runtime import infer_head
    from generation_options import sampler_options
    from reference_preparation import _cropped
    from retexture_runtime import pipeline_config
    from retexture_worker import infer

    if (settings.get('resolution') != 1024 or settings.get('engine', 'trellis2') != 'trellis2'
            or settings.get('texture_method') not in (None, '', 'trellis')
            or any(settings.get(k) for k in ('multiview_texture_refinement', 'retexture_after_refinement', 'reproject_face'))):
        raise ValueError('Facial enhancement requires single-image TRELLIS.2 at 1024 with native materials.')
    config = pipeline_config(root, verify_encoder=True)
    with TemporaryDirectory(prefix='facial-head-', dir=job) as temporary, torch.inference_mode():
        work = Path(temporary)
        with Image.open(job / 'prepared.png') as cutout:
            edit = settings.get('reference_edits', {}).get('front', {})
            subject = _cropped(cutout.convert('RGBA'), edit.get('crop'), 'front')
        subject_path = work / 'subject.png'
        subject.save(subject_path)
        status('running', 'Estimating facial landmarks and head geometry', 6)
        files = infer_head(root, subject_path, work, settings['seed'])
        detection = json.loads(Path(files['landmarks_json']).read_text(encoding='utf8'))
        pixels = face_landmarks(detection, subject)
        donor, donor_faces = read_topos(files['head_obj'])
        status('running', 'Loading model weights', 12)
        vertices, faces, layout, decoded_res, kind = _body_surface(root, job, image, reviewed, options, settings['seed'], status)
        gc.collect()
        torch.cuda.empty_cache()
        status('running', 'Fitting the facial surface and eye sockets', 51)
        vertices, faces, eyes, changed, target, quality = fit_relief(vertices, faces, donor, donor_faces, pixels, subject, detection['iris_rgb'])
        (work / 'pipeline.json').write_text(json.dumps(config), encoding='utf8')
        seed = options['texture_seed'] if options['texture_seed'] >= 0 else settings['seed']
        status('running', 'Generating materials', 58)
        coords, attrs = infer(work, job / 'conditioning.png', vertices, faces,
                dict(seed=seed, sampler=sampler_options(options)['texture']),
                condition_transform=lambda pipeline, cond, resolution: portrait_conditioning(
                    pipeline, cond, subject, pixels, detection, files['portrait'], resolution))
        from facial_head_color import prepare_face_material
        guide = prepare_face_material(vertices, faces, target, pixels, subject)
    report = dict(state='applied', method='TOPOS-DiT', landmarks=478, eyes=2, material_inferences=1,
                  modified_vertices=changed, shape_resolution=decoded_res, material_resolution=1024,
                  deformation_quality=quality,
                  iris_color_source=detection.get('iris_color_source', []))
    return dict(vertices=torch.from_numpy(vertices), faces=torch.from_numpy(faces),
                coords=torch.as_tensor(coords[:, 1:]).contiguous(), attr_volume=torch.as_tensor(attrs).half(),
                voxel_size=1/1024, attr_layout=layout, resolution=1024,
                facial_eye_nodes=eyes, facial_head_enhancement=report, face_material_guide=guide), kind
