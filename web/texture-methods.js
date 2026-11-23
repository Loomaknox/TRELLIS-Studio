import {t} from './i18n.js';

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
  if (!singleImage) return t('Choose a single-image generation engine to use this texture method.');
  const runtime = capabilities[method];
  if (runtime?.available === true) return '';
  switch (runtime?.reason_code) {
    case 'not_installed':
      return t('Install this optional component using Repair or resume components.');
    case 'incomplete':
    case 'dependencies_missing':
      return t('This component is incomplete. Run Repair or resume components.');
    case 'gpu_unsupported':
      return t('This GPU is outside the supported hardware profile for this texture method.');
    case 'vram_insufficient':
      return t('This texture method requires at least {minimum} MiB of dedicated VRAM.', {minimum: runtime.minimum_vram_mib});
    default:
      return t(runtime?.reason || 'Unavailable');
  }
}

export function textureMethodExplanation(preferred, capabilities, singleImage) {
  const fallback = textureMethodRestriction(preferred, capabilities, singleImage);
  if (fallback) return t('{reason} Using Native PBR.', {reason: fallback});
  if (!singleImage) return '';
  return textureMethodChoices.filter(([id]) => id !== 'trellis')
    .map(([id, label]) => [t(label), textureMethodRestriction(id, capabilities, true)])
    .filter(([, reason]) => reason)
    .map(([method, reason]) => t('{method} · {reason}', {method, reason})).join(' ');
}
