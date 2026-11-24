export function singleImageCapability(status, method) {
  return status.generation_methods?.[method] ?? (method === 'pixal3d_single'
    ? status.pixal3d?.single_image : status.ready === undefined ? null : {ready: status.ready, message: status.message});
}

export function pixalRestriction(runtime, preset, finishing) {
  const cap = singleImageCapability(runtime, 'pixal3d_single');
  if (!cap?.ready) return cap?.message || 'Install Pixal3D Single image.';
  if (preset === 'figure_master') return 'Figure Master uses TRELLIS.2 Single image. Choose another profile for Pixal3D.';
  if (finishing?.startsWith('hi3d_')) return 'Hi3D requires a supported TRELLIS.2 single-image resolution.';
  return '';
}

export function reprojectionRestriction(runtime, engine) {
  if (!['pixal3d_single', 'pixal3d'].includes(engine)) return 'Face reprojection requires Pixal3D.';
  const capability=engine==='pixal3d' ? runtime.generation_methods?.pixal3d ?? runtime.pixal3d : singleImageCapability(runtime,engine);
  if(!capability?.ready)return capability?.message || 'This Pixal3D mode needs its optional runtime.';
  const detector=runtime.pixal3d?.face_projection;
  return detector?.ready?'':detector?.message || 'Face reprojection is unavailable.';
}

export function faceRestriction(capability, {engine, type, resolution, texture, finishing}) {
  if (!capability?.ready) return capability?.reason || 'Install the optional face reconstruction component.';
  if (engine !== 'trellis2' || type !== 'humanoid' || Number(resolution) !== 1024)
    return 'Choose TRELLIS.2 Single image, a humanoid and 1024 resolution for face enhancement.';
  if (texture !== 'trellis' || !['', 'direct', 'none'].includes(finishing || ''))
    return 'Choose Native PBR and direct or standard mesh finishing for face enhancement.';
  return '';
}

// Fixed workflows supply their own engine and options. Pixal supplies its own sampler.
export function batchSpecification(row, workflow) {
  const {file, url, ...spec} = row;
  if (workflow) {
    const {name, profile_id, height_m, priority, workflow_options} = spec;
    return {name, profile_id, height_m, priority, workflow_options};
  }
  if (spec.master_finishing === 'none') delete spec.triangles;
  if (spec.engine === 'pixal3d_single') spec.advanced_settings = {};
  return spec;
}
