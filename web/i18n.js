import staticFrench from './fr-static.js';
import animationFrench from './fr-animation.js';
import studioFrench from './fr-studio.js';
import controlsFrench from './fr-controls.js';
import qualityFrench from './fr-quality.js';
import workflowFrench from './fr-workflows.js';
import serverFrench from './fr-server.js';

const storageKey = 'trellis.studio.language';
const supported = value => value === 'fr' || value === 'en';

export function chooseLanguage(preference, browserLanguage = '') {
  if (supported(preference)) return preference;
  return /^fr(?:-|$)/i.test(browserLanguage) ? 'fr' : 'en';
}

function languagePreference() {
  const requested = new URLSearchParams(globalThis.location?.search).get('lang');
  if (supported(requested)) return requested;
  try {
    return globalThis.localStorage?.getItem(storageKey);
  } catch {
    return null;
  }
}

export const language = chooseLanguage(languagePreference(), globalThis.navigator?.language);
export const formatLocale = language === 'fr' ? 'fr-FR' : 'en-US';
const french = { ...staticFrench, ...studioFrench, ...animationFrench, ...controlsFrench, ...workflowFrench, ...serverFrench, ...qualityFrench };

export function t(message, values, context) {
  const key = context && Object.hasOwn(french, context + '|' + message) ? context + '|' + message : message;
  const translated = language === 'fr' && Object.hasOwn(french, key) ? french[key] : message;
  if (!values) return translated;
  return translated.replace(/\{([A-Za-z]\w*)\}/g, (match, key) =>
    Object.hasOwn(values, key) ? String(values[key]) : match);
}

export function translateStage(message) {
  if (language !== 'fr' || typeof message !== 'string') return message;
  const sampling = /^(albedo|mr) (-?\d+(?:\.\d+)?) degrees, step (\d+)\/(\d+)$/.exec(message);
  if (sampling) {
    const [, map, angle, step, total] = sampling;
    return t('{map} {angle} degrees, step {step}/{total}', {map: t(map), angle, step, total});
  }
  const preparation = /^Preparing (albedo|mr) at (-?\d+(?:\.\d+)?) degrees$/.exec(message);
  if (preparation) return t('Preparing {map} at {angle} degrees', {map: t(preparation[1]), angle: preparation[2]});
  const bake = /^Baking the (\d+)px UltraTex albedo and material maps$/.exec(message);
  if (bake) return t('Baking the {size}px UltraTex albedo and material maps', {size: bake[1]});
  return t(message);
}

export function setLanguage(value) {
  if (!supported(value) || value === language) return;
  const url = new URL(location.href);
  try {
    localStorage.setItem(storageKey, value);
    url.searchParams.delete('lang');
  } catch {
    url.searchParams.set('lang', value);
  }
  if (url.href === location.href) location.reload();
  else location.replace(url.href);
}

const textAttributes = ['title', 'aria-label', 'aria-description', 'placeholder', 'alt', 'label'];
const verbatimElements = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'CODE', 'PRE', 'TEXTAREA']);

export function localizeStatic(node) {
  if (language !== 'fr') return;
  if (node.nodeType === 3) {
    const original = node.textContent;
    const key = original.trim().replace(/\s+/g, ' ');
    const translated = Object.hasOwn(staticFrench, key) ? staticFrench[key] : t(key);
    if (translated !== key) {
      const option = node.parentElement;
      if (option?.tagName === 'OPTION' && !option.hasAttribute('value')) option.value = option.value;
      node.textContent = original.replace(/\S[\s\S]*\S|\S/, () => translated);
    }
    return;
  }
  if (node.nodeType === 1) {
    for (const attribute of textAttributes) {
      const original = node.getAttribute(attribute);
      if (!original) continue;
      const key = original.trim().replace(/\s+/g, ' ');
      const translated = Object.hasOwn(staticFrench, key) ? staticFrench[key] : t(key);
      if (translated !== key) node.setAttribute(attribute, translated);
    }
  }
  if (verbatimElements.has(node.tagName)) return;
  const content = node.tagName === 'TEMPLATE' ? node.content : node;
  for (const child of content.childNodes) localizeStatic(child);
}
