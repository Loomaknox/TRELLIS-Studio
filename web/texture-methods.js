export const textureMethodChoices = [
  ['trellis', 'Native PBR'],
  ['multiview', 'Multiview refinement'],
  ['ultratex', 'UltraTex · 2K (local preview)'],
];

export const textureMethodHelp = 'Native PBR uses the generation engine’s materials. Multiview refinement harmonizes color and blends six generated views. UltraTex makes six color and roughness/metallic views in 25 steps per pass, bakes them to 2K, and uses non-commercial model weights.';

export function textureMethodOf(settings = {}) {
  return settings.texture_method ?? (settings.multiview_texture_refinement === true ? 'multiview' : 'trellis');
}

export function textureMethodAvailability(status) {
  return status.texture_methods ?? {
    multiview: status.multiview_texture_refinement,
    ultratex: status.ultratex_texture_refinement,
  };
}

export function textureMethodRestriction(method, capabilities, singleImage) {
  if (method === 'trellis') return '';
  if (!singleImage) return 'Choose a single-image generation engine to use this texture method.';
  const runtime = capabilities[method];
  const name = method === 'ultratex' ? 'UltraTex' : 'Multiview refinement';
  return runtime?.available === true ? '' : runtime?.reason || `${name} is unavailable locally.`;
}
