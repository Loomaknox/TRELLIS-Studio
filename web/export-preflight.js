import {t} from './i18n.js';
import {el, field, input, select, button} from './workbench-ui.js?v=3.4.0';

const usages = [
  ['static', t('Static prop')], ['background', t('Background prop')],
  ['interactive', t('Interactive prop')], ['character', t('Character')],
  ['reference', t('Editable source')],
];
const reviewLabels = {
  review: t('To review'), retouch: t('Needs changes'), retained: t('Retained'), rejected: t('Rejected'),
};
const actions = {
  diagnostics: [t('Inspect'), 'shield'], lod: [t('Prepare LODs'), 'layers'],
  game: [t('Adjust in Game preparation'), 'cube'], print: [t('Prepare a new print copy'), 'print'],
};
const presets = {
  static: [28000, 2048, 4], background: [12000, 1024, 2],
  interactive: [28000, 2048, 6], character: [30000, 2048, 6], reference: ['', '', ''],
};

function inferredUsage(jobs, target) {
  if (target === 'print') return 'print';
  if (target === 'blender' || target === 'glb') return 'reference';
  if (jobs.length !== 1) return 'static';
  const type = jobs[0].metadata?.asset_type || jobs[0].settings?.asset_type;
  if (['humanoid', 'creature', 'animal', 'robot', 'rigged'].includes(type) || jobs[0].media?.animated) return 'character';
  if (['interactive_prop', 'door', 'collectible'].includes(type)) return 'interactive';
  if (type === 'architecture') return 'background';
  return 'static';
}

export function createExportPreflight({api, onAction, onChange}) {
  const root = el('section', 'export-preflight');
  root.setAttribute('aria-label', t('Export checks'));
  const head = el('div', 'export-check-head');
  const state = el('span', 'export-check-state', t('Check pending'));
  state.setAttribute('role', 'status');
  head.append(el('h4', '', t('Export checks')), state);
  const usage = select(usages, 'static');
  const usageField = field(t('Asset use'), usage);
  const budgets = el('details', 'export-check-budgets');
  const budgetSummary = el('summary', '', t('Budget and expectations'));
  const controls = el('div', 'export-check-fields');
  const maxTriangles = input('number', '', {min: 1, max: 50000000, step: 1});
  const maxTextures = input('number', '', {min: 1, max: 32768, step: 1});
  const maxMaterials = input('number', '', {min: 1, max: 10000, step: 1});
  const expectedHeight = input('number', '', {min: 0.000001, step: 'any'});
  const heightLabel = field(t('Expected height (m)'), expectedHeight);
  const pivot = select([['any', t('No target')], ['ground', t('Bottom centre')], ['center', t('Geometric centre')]], 'any');
  const collider = input('checkbox', '');
  const colliderField = field(t('Require a collision proxy'), collider);
  const triangleField = field(t('LOD 0 · max triangles'), maxTriangles);
  const textureField = field(t('Max texture edge (px)'), maxTextures);
  const materialField = field(t('Max materials'), maxMaterials);
  const pivotField = field(t('Expected pivot'), pivot);
  controls.append(triangleField, textureField, materialField, heightLabel, pivotField, colliderField);
  const detailLevels = el('details', 'export-check-levels');
  const lodControls = el('div', 'export-check-fields');
  const lods = Array.from({length: 4}, (_, i) => {
    const control = input('number', '', {min: 1, max: 50000000, step: 1});
    lodControls.append(field(t('LOD {level} · max triangles', {level: i + 1}), control));
    return control;
  });
  detailLevels.append(el('summary', '', t('Lower detail levels')), lodControls);
  budgets.append(budgetSummary, controls, detailLevels);
  const hint = el('p', 'export-check-hint', t('Blank fields have no limit. Your review status is reported separately.'));
  const results = el('div', 'export-check-results');
  const bypass = el('button', 'secondary export-check-bypass', t('Continue without measured checks'));
  bypass.type = 'button';
  bypass.hidden = true;
  root.append(head, usageField, budgets, hint, results, bypass);

  let jobs = [];
  let target = 'blender';
  let key = null;
  let report = null;
  let busy = false;
  let skipped = false;
  let token = 0;

  const number = control => control.value === '' ? null : control.valueAsNumber;
  const scale = () => target === 'print' ? 1000 : target === 'unreal' ? 100 : 1;
  const engineTarget = () => target === 'unity' || target === 'unreal';
  const budget = () => ({
    usage: target === 'print' ? 'print' : usage.value,
    max_triangles: number(maxTriangles),
    max_texture_edge: target === 'print' ? null : number(maxTextures),
    max_materials: target === 'print' ? null : number(maxMaterials),
    max_lod_triangles: target === 'print' ? [] : lods.map(number),
    expected_height_m: expectedHeight.value === '' ? null : number(expectedHeight) / scale(),
    pivot: target === 'print' ? 'any' : pivot.value,
    require_collision: engineTarget() && collider.checked,
  });

  function clearResult() {
    ++token;
    report = null;
    busy = false;
    skipped = false;
    results.replaceChildren();
    bypass.hidden = true;
    state.textContent = t('Check pending');
    state.className = 'export-check-state';
  }

  function applyPreset() {
    const [triangles, texture, materials] = presets[usage.value] ?? presets.reference;
    maxTriangles.value = target === 'print' ? '' : triangles;
    maxTextures.value = texture;
    maxMaterials.value = materials;
    lods.forEach(control => { control.value = ''; });
    pivot.value = ['static', 'background', 'interactive'].includes(usage.value) ? 'ground' : 'any';
    collider.checked = usage.value === 'interactive';
  }

  function renderReport() {
    let attention = 0;
    for (const model of report.models) {
      const job = jobs.find(entry => entry.id === model.id);
      const group = el('details', 'export-check-model');
      const warnings = model.checks.filter(row => row.status === 'attention').length;
      attention += warnings;
      group.open = report.models.length === 1;
      const label = warnings ? t('{count} to inspect', {count: warnings}) : t('Checks measured');
      group.append(el('summary', warnings ? 'attention' : '', `${model.name} · ${label}`));
      group.append(el('p', 'export-check-review', t('Visual review · {review}', {review: reviewLabels[model.human_review] || t('To review')})));
      const rows = el('ul', 'export-check-rows');
      for (const check of model.checks) {
        const row = el('li', check.status);
        const description = el('span');
        description.append(el('strong', '', t(check.label)), el('small', '', t(check.detail_key || check.detail, check.detail_values)));
        row.append(description);
        const action = actions[check.action];
        if (check.status === 'attention' && action && job) {
          row.append(button(...action, 'secondary', () => onAction(check.action, job)));
        }
        rows.append(row);
      }
      group.append(rows);
      results.append(group);
    }
    state.textContent = attention ? t('{count} to inspect', {count: attention}) : t('Checks measured');
    state.classList.toggle('attention', attention > 0);
    state.classList.toggle('checked', attention === 0);
  }

  function setSelection(selected, destination, active) {
    root.hidden = !active;
    if (!active) return;
    const nextKey = JSON.stringify([destination, selected.map(job => [job.id, job.result?.revision])]);
    if (key === nextKey) return;
    key = nextKey;
    jobs = selected;
    target = destination;
    clearResult();
    usage.value = inferredUsage(jobs, target);
    usageField.hidden = target === 'print';
    detailLevels.hidden = textureField.hidden = materialField.hidden = pivotField.hidden = target === 'print';
    colliderField.hidden = !engineTarget();
    heightLabel.firstChild.textContent = t('Expected height ({unit})', {unit: scale() === 1000 ? 'mm' : scale() === 100 ? 'cm' : 'm'});
    expectedHeight.value = '';
    applyPreset();
  }

  function reset() {
    key = null;
    clearResult();
  }

  async function run() {
    const fields = [maxTriangles, maxTextures, maxMaterials, expectedHeight, ...lods];
    const invalid = fields.find(control => !control.closest('[hidden]') && !control.validity.valid);
    if (invalid) {
      budgets.open = true;
      if (lods.includes(invalid)) detailLevels.open = true;
      invalid.reportValidity();
      return;
    }
    const own = ++token;
    const payload = {ids: jobs.map(job => job.id), target, budget: budget()};
    busy = true;
    results.replaceChildren();
    bypass.hidden = true;
    state.textContent = t('Measuring…');
    onChange();
    try {
      const measured = await api('/api/exports/preflight', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
      });
      if (own !== token) return;
      report = measured;
      renderReport();
      if (root.closest('dialog')?.open) head.scrollIntoView({block: 'nearest'});
    } catch (error) {
      if (own !== token) return;
      state.textContent = t('Check unavailable');
      state.classList.add('attention');
      results.append(el('p', 'export-check-hint', t(error.message)));
      bypass.hidden = false;
      if (root.closest('dialog')?.open) bypass.scrollIntoView({block: 'nearest'});
    } finally {
      if (own === token) {
        busy = false;
        onChange();
      }
    }
  }

  usage.onchange = () => { applyPreset(); clearResult(); onChange(); };
  budgets.addEventListener('input', () => { clearResult(); onChange(); });
  bypass.onclick = () => {
    skipped = true;
    state.textContent = t('Check skipped');
    bypass.hidden = true;
    onChange();
  };
  return {
    root, setSelection, reset, run,
    get needsCheck() { return !root.hidden && !report && !skipped; },
    get busy() { return busy; },
    get exportData() {
      if (root.hidden || !report) return undefined;
      return {
        budget: report.budget,
        source_hashes: Object.fromEntries(report.models.map(model => [model.id, model.source_glb_sha256])),
      };
    },
  };
}
