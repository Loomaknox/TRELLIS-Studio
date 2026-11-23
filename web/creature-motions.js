import {t} from './i18n.js';

export function createCreatureMotions({api, canEdit, apply}) {
  const $ = id => document.getElementById(id);
  const panel = $('creatureMotionPanel');
  const form = $('creatureMotionForm');
  const fields = $('creatureMotionFields');
  const status = $('creatureMotionPanelNotice');
  const retry = $('creatureMotionReload');
  const selector = $('creatureMotionKind');
  const name = $('creatureMotionName');
  const submit = $('creatureMotionAdd');
  const swimFields = $('creatureMotionSwimFields');
  const commonFields = ['duration_s', 'amplitude', 'cycles'];
  const swimmingFields = ['phase_lag', 'travel_m'];
  let target = null, options = null, modelVersion = null, loading = null, submitting = null;

  function chosen() {
    return options?.motions.find(motion => motion.id === selector.value);
  }

  function syncControls() {
    const motion = chosen();
    const blocked = !target || !canEdit(target) || Boolean(submitting || loading);
    const swim = motion?.id === 'swim';
    fields.disabled = blocked;
    swimFields.hidden = !swim;
    swimFields.disabled = !swim;
    $('creatureMotionDescription').textContent = motion ? t(motion.description) : '';
    const reason = $('creatureMotionReason');
    reason.hidden = !motion || motion.available;
    reason.textContent = reason.hidden ? '' : t(motion.reason || 'The selected rig does not support this motion.');
    const supported = options && options.available !== false && options.rig_supported !== false
      && options.creation_available !== false;
    submit.disabled = blocked || !supported || !motion?.available || !options?.revision;
    submit.querySelector('span').textContent = t(submitting ? 'Adding motion…' : 'Add motion');
  }

  function configure(next, preserve) {
    const previous = preserve ? selector.value : '';
    selector.replaceChildren(...next.motions.map(motion => new Option(
      motion.available ? t(motion.name) : t('{motion} (unavailable)', {motion: t(motion.name)}), motion.id,
    )));
    const preferred = next.motions.find(motion => motion.id === previous)
      || next.motions.find(motion => motion.id === next.defaults?.motion && motion.available)
      || next.motions.find(motion => motion.available) || next.motions[0];
    selector.value = preferred?.id || '';
    for (const field of [...commonFields, ...swimmingFields]) {
      const input = form.elements.namedItem(field);
      const [min, max] = next.limits?.[field] || [];
      if (Number.isFinite(min) && Number.isFinite(max)) {
        input.min = min;
        input.max = max;
      }
      const value = next.defaults?.[field];
      if ((!preserve || !input.validity.valid) && Number.isFinite(value)) input.value = value;
    }
    form.hidden = !next.motions.length;
  }

  async function load(version) {
    if (!target) return;
    const request = {id: target.id};
    loading = request;
    modelVersion = version;
    retry.hidden = true;
    status.textContent = t('Checking the selected rig…');
    syncControls();
    try {
      const data = await api(`/api/jobs/${encodeURIComponent(request.id)}/creature-motions`, {cache: 'no-store'});
      if (loading !== request) return;
      if (!Array.isArray(data.motions)) throw Error('Creature motion options are unavailable.');
      configure(data, Boolean(options));
      options = data;
      if (data.available === false || data.rig_supported === false || !data.motions.some(motion => motion.available)) {
        status.textContent = t(data.reason || 'This rig has no compatible creature motions.');
      } else {
        status.textContent = data.creation_available === false ? t(data.creation_reason || 'Motion creation is unavailable.') : '';
      }
    } catch (error) {
      if (loading !== request) return;
      form.hidden = true;
      status.textContent = t(error.message);
      retry.hidden = false;
    } finally {
      if (loading === request) {
        loading = null;
        syncControls();
      }
    }
  }

  selector.onchange = syncControls;
  retry.onclick = () => load(modelVersion);
  form.onsubmit = async event => {
    event.preventDefault();
    if (panel.hidden || !target || submit.disabled || !form.reportValidity()) return;
    const job = target;
    const motion = chosen();
    const recipe = {revision: options.revision, motion: motion.id};
    if (name.value.trim()) recipe.name = name.value.trim();
    const parameters = motion.id === 'swim' ? [...commonFields, ...swimmingFields] : commonFields;
    for (const field of parameters) recipe[field] = form.elements.namedItem(field).valueAsNumber;
    submitting = job.id;
    retry.hidden = true;
    syncControls();
    try {
      const result = await apply(job, recipe);
      if (target?.id === job.id && !result.ok) retry.hidden = false;
    } catch (error) {
      if (target?.id === job.id) {
        status.textContent = t(error.message);
        retry.hidden = false;
      }
    } finally {
      if (submitting === job.id) submitting = null;
      syncControls();
    }
  };

  return {
    update(job, visible) {
      panel.hidden = !visible;
      if (target?.id !== job?.id) {
        form.reset();
        form.hidden = true;
        retry.hidden = true;
        status.textContent = '';
        selector.replaceChildren();
        options = modelVersion = loading = null;
      }
      target = job;
      if (!visible) return;
      const version = JSON.stringify([job.media?.animation_revision, job.result?.revision]);
      if (job.state === 'done' && submitting !== job.id && version !== modelVersion) void load(version);
      syncControls();
    },
  };
}
