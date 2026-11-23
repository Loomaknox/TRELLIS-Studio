import {formatLocale, t} from './i18n.js';

const swimFields = [
  ['duration_s', 'Swim loop duration (s)', 2, 12, .1, 5.2],
  ['pulses', 'Pulses per loop', 1, 4, 1, 2],
  ['bell_amplitude', 'Bell contraction (°)', 0, 26, 1, 16],
  ['tentacle_amplitude', 'Tentacle bend (°)', 0, 22, 1, 12],
  ['phase_lag', 'Delay to the tips (s)', 0, 1.2, .05, .45],
  ['body_travel_m', 'Vertical travel (m)', 0, .35, .01, .17],
];

export function createSwimFields(container) {
  const inputs = swimFields.map(([key, caption, min, max, step, initial]) => {
    const label = document.createElement('label');
    const input = document.createElement('input');
    label.className = 'field';
    label.textContent = t(caption);
    input.type = 'number';
    input.name = key;
    input.min = min;
    input.max = max;
    input.step = step;
    input.value = initial;
    input.required = true;
    label.append(input);
    container.append(label);
    return input;
  });
  return {
    set(options = {}) {
      inputs.forEach((input, index) => {input.value = options[input.name] ?? swimFields[index][5];});
    },
    get() {
      if (!inputs.every(input => input.reportValidity())) return null;
      return Object.fromEntries(inputs.map(input => [input.name, input.valueAsNumber]));
    },
    enable(enabled) {
      inputs.forEach(input => {input.disabled = !enabled;});
    },
  };
}

export function isCreatureRig(job) {
  return job?.settings?.rig_options?.mode === 'creature' || Boolean(job?.result?.creature_rig);
}

export function isCreatureRigDraft(job) {
  return isCreatureRig(job) && (job.rig_phase === 'draft'
    || (job.settings?.creature_phase === 'final' && ['error', 'cancelled'].includes(job.state))
    || (!job.rig_phase && !job.media?.available));
}

export function hasTentacleRig(bones) {
  if (!bones?.length) return false;
  const byName = new Map(bones.map(bone => [bone.name, bone]));
  if (byName.get('racine')?.parent !== null) return false;
  const chains = new Map();
  for (const bone of bones) {
    const match = /^tentacule_(\d{2,3})_(\d{2,3})$/.exec(bone.name);
    if (!match) continue;
    const branch = Number(match[1]), step = Number(match[2]);
    if (!chains.has(branch)) chains.set(branch, new Map());
    const numbered = chains.get(branch);
    if (numbered.has(step)) return false;
    numbered.set(step, bone);
  }
  if (chains.size < 2) return false;
  for (const [branch, numbered] of chains) {
    let parent = byName.get(`ombrelle_${String(branch).padStart(2, '0')}`);
    if (parent?.parent !== 'racine') return false;
    for (let step = 1; step <= numbered.size; step++) {
      const segment = numbered.get(step);
      if (segment?.parent !== parent.name) return false;
      parent = segment;
    }
  }
  return true;
}

function descendants(bones, name) {
  const names = new Set([name]);
  for (let size = 0; size !== names.size;) {
    size = names.size;
    for (const bone of bones) if (names.has(bone.parent)) names.add(bone.name);
  }
  return names;
}

function samePosition(a, b) {
  return Math.hypot(...a.map((value, axis) => value - b[axis])) < 1e-6;
}

export function moveBonePoint(bones, bone, point, position, connected) {
  const previous = bone[point];
  if (connected) {
    for (const adjacent of bones) {
      if (adjacent === bone) continue;
      if (adjacent.name !== bone.parent && adjacent.parent !== bone.name
          && (bone.parent === null || adjacent.parent !== bone.parent)) continue;
      for (const endpoint of ['head', 'tail']) {
        if (samePosition(adjacent[endpoint], previous)) adjacent[endpoint] = [...position];
      }
    }
  }
  bone[point] = [...position];
}

export function addBoneChain(bones, parent, segments, split = false) {
  const names = new Set(bones.map(bone => bone.name));
  let serial = 1;
  function nextName() {
    let name;
    do {name = `branch_${serial++}`;} while (names.has(name));
    names.add(name);
    return name;
  }
  const start = split ? parent.head : parent.tail;
  const direction = parent.tail.map((value, axis) => value - parent.head[axis]);
  const point = i => start.map((value, axis) => value + direction[axis] * i / segments);
  const following = split ? bones.filter(bone => bone.parent === parent.name && samePosition(bone.head, parent.tail)) : [];
  if (split) parent.tail = point(1);
  let previous = parent.name, first = null;
  for (let i = split ? 1 : 0; i < segments; i++) {
    const bone = {name: nextName(), parent: previous, head: point(i), tail: point(i + 1)};
    bones.push(bone);
    first ??= bone.name;
    previous = bone.name;
  }
  for (const bone of following) bone.parent = previous;
  return first ?? parent.name;
}

export function createCreatureRigEditor({api, viewer, startJob, getJob, isBusy, onVisibility, onComplete}) {
  const $ = id => document.getElementById(id);
  const panel = $('creatureRigEditor');
  const form = $('creatureRigForm');
  const boneSelect = $('creatureBone');
  const parentSelect = $('creatureBoneParent');
  const name = $('creatureBoneName');
  const joins = $('creatureMoveJoined');
  const segments = $('creatureChainSegments');
  const motion = $('creatureMotion');
  const status = $('creatureRigStatus');
  const retry = $('creatureReloadDraft');
  const places = {head: $('creaturePlaceStart'), tail: $('creaturePlaceEnd')};
  const tentacles = $('creatureTentacles');
  const adapt = $('creatureAdaptTentacles');
  const spacing = $('creatureTentacleSpacing');
  const tentacleStatus = $('creatureTentacleStatus');
  const counts = $('creatureTentacleCounts');
  const swimContainer = $('creatureDraftSwimFields');
  const swim = createSwimFields(swimContainer);
  const swimOption = motion.querySelector('option[value="swim"]');
  const fields = {};
  for (const endpoint of ['head', 'tail']) {
    const layout = document.getElementById('creatureBone' + (endpoint === 'head' ? 'Head' : 'Tail'));
    fields[endpoint] = [...'XYZ'].map((axis, index) => {
      const label = document.createElement('label');
      const input = document.createElement('input');
      label.textContent = axis;
      input.type = 'number';
      input.step = 'any';
      input.required = true;
      input.setAttribute('aria-label', t(endpoint === 'head' ? 'Bone start {axis}' : 'Bone end {axis}', {axis}));
      input.addEventListener('change', () => {
        const bone = currentBone();
        if (!bone || !input.validity.valid || !Number.isFinite(input.valueAsNumber)) return;
        const position = [...bone[endpoint]];
        position[index] = input.valueAsNumber;
        movePoint(endpoint, position);
      });
      label.append(input);
      layout.append(label);
      return input;
    });
  }

  let target = null;
  let active = false;
  let loading = null;
  let draft = null;
  let saving = false;
  let adapting = null;
  let tentacleAvailable = false;
  let swimAvailable = false;
  let placement = null;
  const currentBone = () => draft?.bones.find(bone => bone.name === draft.selection);

  function option(value) {
    const element = document.createElement('option');
    element.value = value;
    element.textContent = value;
    return element;
  }

  function setPlacement(endpoint) {
    placement = endpoint;
    for (const [point, button] of Object.entries(places)) {
      button.setAttribute('aria-pressed', String(point === endpoint));
    }
    viewer?.place(endpoint);
    $('creaturePlacementHint').hidden = !endpoint;
  }

  function updatePoints() {
    const bone = currentBone();
    if (!bone) return;
    for (const [endpoint, inputs] of Object.entries(fields)) {
      inputs.forEach((input, index) => {
        if (document.activeElement !== input) input.value = Number(bone[endpoint][index].toPrecision(8));
      });
    }
    if (active && target === getJob()?.id) {
      viewer?.show(draft.bones, bone.name, (endpoint, position) => movePoint(endpoint, position, true),
        () => setPlacement(null));
    }
    const canPlace = Boolean(viewer?.active) && !isBusy() && !adapting && !saving;
    if (placement && !canPlace) setPlacement(null);
    for (const button of Object.values(places)) button.disabled = !canPlace;
  }

  function movePoint(endpoint, position, fromViewer = false) {
    const bone = currentBone();
    if (!bone || isBusy() || adapting || saving) return;
    if (!fromViewer && !position.every(Number.isFinite)) return;
    moveBonePoint(draft.bones, bone, endpoint, position, joins.checked);
    updatePoints();
  }

  function updateForm(rebuild = false) {
    const bone = currentBone();
    if (!bone) return;
    setPlacement(null);
    if (rebuild) boneSelect.replaceChildren(...draft.bones.map(item => option(item.name)));
    boneSelect.value = bone.name;
    const excluded = descendants(draft.bones, bone.name);
    const root = option('');
    root.textContent = t('Root bone');
    parentSelect.replaceChildren(...(bone.parent === null ? [root] : draft.bones.filter(item => !excluded.has(item.name)).map(item => option(item.name))));
    parentSelect.value = bone.parent ?? '';
    parentSelect.disabled = bone.parent === null;
    $('creatureRemoveBranch').disabled = bone.parent === null;
    name.value = bone.name;
    name.setCustomValidity('');
    $('creatureBoneCount').textContent = t(draft.bones.length === 1 ? '{count} bone' : '{count} bones', {count: draft.bones.length});
    updatePoints();
    updateControls();
  }

  function updateControls() {
    const localBusy = Boolean(adapting || saving);
    retry.disabled = localBusy;
    if (placement && (isBusy() || localBusy)) setPlacement(null);
    tentacles.hidden = !tentacleAvailable || !draft || draft.id !== target;
    adapt.disabled = isBusy() || localBusy;
    spacing.disabled = localBusy;
    $('creatureSkeletonEditFields').disabled = localBusy;
    $('creatureResetDraft').disabled = localBusy;
    $('creatureCompleteRig').disabled = isBusy() || localBusy;
    for (const button of Object.values(places)) button.disabled = isBusy() || localBusy || !viewer?.active;
    motion.disabled = localBusy;
    const canSwim = swimAvailable && hasTentacleRig(draft?.bones);
    swimOption.disabled = !canSwim;
    swimOption.hidden = !canSwim;
    if (!canSwim && motion.value === 'swim') motion.value = 'test';
    const swimming = canSwim && motion.value === 'swim';
    swimContainer.hidden = !swimming;
    swim.enable(swimming && !localBusy);
    $('creatureMotionHint').hidden = swimming;
  }

  function renderTentacleCounts() {
    const chains = draft?.chains || [];
    counts.hidden = !chains.length;
    const rows = chains.map((chain, index) => {
      const row = document.createElement('tr');
      const name = document.createElement('th');
      const length = document.createElement('td');
      const segments = document.createElement('td');
      name.scope = 'row';
      name.textContent = t('Tentacle {number}', {number: index + 1});
      length.textContent = chain.length_m.toLocaleString(formatLocale, {maximumFractionDigits: 2}) + ' m';
      segments.textContent = chain.segments.toLocaleString(formatLocale);
      row.append(name, length, segments);
      return row;
    });
    counts.tBodies[0].replaceChildren(...rows);
  }

  function reportTentacles() {
    tentacleStatus.textContent = [
      ...(draft.chains.length ? [t('Counts from the automatic proposal.')] : []),
      ...draft.warnings.map(warning => t(warning)),
    ].join(' ');
  }

  function selectRoot() {
    draft.selection = draft.bones.find(bone => bone.parent === null)?.name ?? draft.bones[0].name;
  }

  for (const [point, button] of Object.entries(places)) {
    button.onclick = () => setPlacement(placement === point ? null : point);
  }
  retry.onclick = () => {
    if (!active || !target) return;
    draft = null;
    loading = null;
    retry.hidden = true;
    setPlacement(null);
    viewer?.close();
    sync(getJob(), true, {tentacles: tentacleAvailable, swim: swimAvailable});
  };
  motion.onchange = updateControls;
  adapt.onclick = async () => {
    if (!active || !draft || draft.id !== target || adapt.disabled || !spacing.reportValidity()) return;
    const request = {id: draft.id, draft};
    adapting = request;
    updateControls();
    tentacleStatus.textContent = t('Measuring tentacles…');
    try {
      const proposal = await api(`/api/jobs/${encodeURIComponent(draft.id)}/rig-tentacles`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({revision: draft.revision, spacing_m: spacing.valueAsNumber}),
      });
      if (adapting !== request || target !== request.id || draft !== request.draft) return;
      draft.warnings = proposal.warnings ?? [];
      if (proposal.bones?.length && proposal.chains?.length) {
        draft.bones = structuredClone(proposal.bones);
        draft.revision = proposal.revision ?? draft.revision;
        draft.chains = proposal.chains;
        selectRoot();
        if (motion.value === 'test' && swimAvailable && hasTentacleRig(draft.bones)) {
          swimOption.disabled = false;
          motion.value = 'swim';
        }
        updateForm(true);
      } else if (!draft.warnings.length) {
        draft.warnings = ['No distinct tentacle chains were detected.'];
      }
      renderTentacleCounts();
      reportTentacles();
    } catch (error) {
      if (adapting === request) tentacleStatus.textContent = t(error.message);
    } finally {
      if (adapting === request) {
        adapting = null;
        updateControls();
      }
    }
  };

  boneSelect.onchange = () => {draft.selection = boneSelect.value; updateForm();};
  parentSelect.onchange = () => {currentBone().parent = parentSelect.value; updateForm();};
  name.oninput = () => name.setCustomValidity('');
  name.onchange = () => {
    const bone = currentBone();
    if (!bone) return;
    const next = name.value.trim();
    if (next === bone.name) {name.value = bone.name; return;}
    if (!next || new TextEncoder().encode(next).length > 63 || /\p{C}/u.test(next)
        || draft.bones.some(item => item.name === next)) {
      name.setCustomValidity(t('Enter a unique bone name within 63 UTF-8 bytes.'));
      name.reportValidity();
      return;
    }
    for (const child of draft.bones) if (child.parent === bone.name) child.parent = next;
    bone.name = next;
    draft.selection = next;
    updateForm(true);
  };

  function makeChain(split) {
    const bone = currentBone();
    const count = segments.valueAsNumber;
    if (!bone || !segments.reportValidity()) return;
    if (split && count < 2) {status.textContent = t('Use at least two segments to split a bone.'); return;}
    if (draft.bones.length + count - Number(split) > draft.limit) {
      status.textContent = t('This draft can contain up to {count} bones.', {count: draft.limit});
      return;
    }
    if (samePosition(bone.head, bone.tail)) {status.textContent = t('Move the start and end apart before extending this bone.'); return;}
    const first = addBoneChain(draft.bones, bone, count, split);
    draft.selection = split ? bone.name : first;
    status.textContent = '';
    updateForm(true);
  }

  $('creatureAddBranch').onclick = () => makeChain(false);
  $('creatureSplitBone').onclick = () => makeChain(true);
  $('creatureRemoveBranch').onclick = () => {
    const bone = currentBone();
    if (!bone?.parent) return;
    const removed = descendants(draft.bones, bone.name);
    draft.selection = bone.parent;
    draft.bones = draft.bones.filter(item => !removed.has(item.name));
    status.textContent = '';
    updateForm(true);
  };
  $('creatureResetDraft').onclick = () => {
    draft.bones = structuredClone(draft.predicted);
    draft.chains = [];
    draft.warnings = [];
    selectRoot();
    status.textContent = '';
    renderTentacleCounts();
    reportTentacles();
    updateForm(true);
  };

  form.onsubmit = async event => {
    event.preventDefault();
    if (!active || !draft || draft.id !== target || isBusy() || saving || adapting) return;
    const job = getJob();
    if (job?.id !== draft.id) return;
    if (draft.bones.some(bone => samePosition(bone.head, bone.tail))) {
      status.textContent = t('Every bone needs a different start and end.');
      return;
    }
    const body = {revision: draft.revision, bones: draft.bones, motion: motion.value};
    if (body.motion === 'swim') {
      body.swim = swim.get();
      if (!body.swim) return;
    }
    saving = true;
    retry.hidden = true;
    updateControls();
    status.textContent = t('Queuing skin weights…');
    try {
      const result = await api(`/api/jobs/${encodeURIComponent(job.id)}/rig-complete`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      onComplete?.();
      close();
      draft = null;
      await startJob(result.id, {rig: true});
    } catch (error) {
      status.textContent = t(error.message);
      retry.hidden = false;
    } finally {
      saving = false;
      updateControls();
    }
  };

  function close() {
    setPlacement(null);
    if (active) onVisibility(false);
    active = false;
    target = null;
    loading = null;
    adapting = null;
    tentacles.hidden = true;
    panel.hidden = true;
    viewer?.close();
  }

  function sync(job, enabled, capabilities = {}) {
    tentacleAvailable = capabilities.tentacles === true;
    swimAvailable = capabilities.swim === true;
    if (!enabled || !isCreatureRigDraft(job) || !['done', 'error', 'cancelled'].includes(job.state)) {
      close();
      return false;
    }
    if (target !== job.id) {
      if (target) close();
      target = job.id;
      retry.hidden = true;
      status.textContent = '';
      panel.hidden = false;
      active = true;
      onVisibility(true);
    }
    updateControls();
    if (draft?.id === target) {
      form.hidden = false;
      updatePoints();
    } else if (!loading && retry.hidden) {
      form.hidden = true;
      const request = {id: target};
      loading = request;
      status.textContent = t('Loading the proposed skeleton…');
      api(`/api/jobs/${encodeURIComponent(request.id)}/rig-preview`, {cache: 'no-store'}).then(data => {
        if (request !== loading || target !== request.id) return;
        if (!data.ready || data.aligned_to_model !== true || !data.revision || !data.bones?.length) {
          throw Error('The editable skeleton is unavailable.');
        }
        const bones = structuredClone(data.edited_bones ?? data.adapted_bones ?? data.bones);
        draft = {id: request.id, revision: data.revision, bones, predicted: data.bones,
          limit: data.max_bones ?? 512, chains: data.chains ?? [], warnings: data.warnings ?? []};
        selectRoot();
        spacing.value = data.spacing_m ?? .19;
        joins.checked = true;
        segments.value = 3;
        swimOption.disabled = !swimAvailable || !hasTentacleRig(bones);
        motion.value = data.motion ?? (draft.chains.length && !swimOption.disabled ? 'swim' : 'test');
        swim.set(data.swim);
        form.hidden = false;
        status.textContent = t('Check joint placement before calculating skin weights.');
        renderTentacleCounts();
        reportTentacles();
        updateForm(true);
      }).catch(error => {
        if (loading === request) {
          status.textContent = t(error.message);
          retry.hidden = false;
        }
      }).finally(() => {
        if (loading === request) loading = null;
      });
    }
    return true;
  }

  return {sync, close};
}
