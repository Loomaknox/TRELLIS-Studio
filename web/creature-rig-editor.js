export function isCreatureRig(job) {
  return job?.settings?.rig_options?.mode === 'creature' || Boolean(job?.result?.creature_rig);
}

export function isCreatureRigDraft(job) {
  return isCreatureRig(job) && (job.rig_phase === 'draft'
    || (job.settings?.creature_phase === 'final' && ['error', 'cancelled'].includes(job.state)));
}

const endpoints = ['head', 'tail'];
const defaultMotion = 'test';
const samePoint = (a, b) => Math.hypot(...a.map((value, axis) => value - b[axis])) < 1e-6;

export function descendants(bones, name) {
  const children = new Map();
  for (const bone of bones) {
    if (!children.has(bone.parent)) children.set(bone.parent, []);
    children.get(bone.parent).push(bone.name);
  }
  const names = new Set([name]);
  for (const parent of names) {
    for (const child of children.get(parent) || []) names.add(child);
  }
  return names;
}

export function moveBonePoint(bones, bone, endpoint, position, connected) {
  const previous = bone[endpoint];
  if (connected) {
    for (const neighbor of bones) {
      if (neighbor === bone) continue;
      const related = neighbor.name === bone.parent || neighbor.parent === bone.name
        || (bone.parent !== null && neighbor.parent === bone.parent);
      if (related) for (const point of endpoints) {
        if (samePoint(neighbor[point], previous)) neighbor[point] = [...position];
      }
    }
  }
  bone[endpoint] = [...position];
}

export function addBoneChain(bones, parent, segments, split = false) {
  const names = new Set(bones.map(bone => bone.name));
  const start = split ? parent.head : parent.tail;
  const axis = parent.tail.map((value, index) => value - parent.head[index]);
  const point = index => start.map((value, coordinate) => value + axis[coordinate] * index / segments);
  const attached = split
    ? bones.filter(bone => bone.parent === parent.name && samePoint(bone.head, parent.tail)) : [];
  if (split) parent.tail = point(1);
  let previous = parent.name;
  let first = null;
  let serial = 1;
  for (let index = split ? 1 : 0; index < segments; index++) {
    while (names.has(`branch_${serial}`)) serial++;
    const name = `branch_${serial++}`;
    bones.push({name, parent: previous, head: point(index), tail: point(index + 1)});
    first ??= name;
    previous = name;
  }
  for (const bone of attached) bone.parent = previous;
  return first;
}

export function createCreatureRigEditor({api, viewer, startJob, isBusy, onVisibility}) {
  const $ = id => document.getElementById(id);
  const panel = $('creatureRigEditor');
  const form = $('creatureRigForm');
  const selection = $('creatureBone');
  const parent = $('creatureBoneParent');
  const name = $('creatureBoneName');
  const connected = $('creatureMoveJoined');
  const segments = $('creatureChainSegments');
  const motion = $('creatureMotion');
  const status = $('creatureRigStatus');
  const add = $('creatureAddBranch');
  const split = $('creatureSplitBone');
  const remove = $('creatureRemoveBranch');
  const retry = $('creatureReloadDraft');
  const places = {head: $('creaturePlaceStart'), tail: $('creaturePlaceEnd')};
  const vectors = {};
  let target = null, draft = null, loading = null, saving = null, placement = null;

  for (const [endpoint, field] of [['head', 'creatureBoneHead'], ['tail', 'creatureBoneTail']]) {
    vectors[endpoint] = [...'XYZ'].map(axis => {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'number';
      input.step = 'any';
      input.required = true;
      label.append(axis, input);
      $(field).append(label);
      input.onchange = () => {
        const position = vectors[endpoint].map(value => value.valueAsNumber);
        if (position.every(Number.isFinite)) move(endpoint, position);
      };
      return input;
    });
  }

  const option = (value, label = value) => new Option(label, value);
  const currentBone = () => draft?.bones.find(bone => bone.name === selection.value);
  const locked = () => Boolean(saving || isBusy());

  function setPlacement(endpoint) {
    placement = endpoint;
    for (const point of endpoints) places[point].setAttribute('aria-pressed', String(point === endpoint));
    viewer?.place(endpoint);
    $('creaturePlacementHint').hidden = !endpoint;
  }

  function refreshControls() {
    const bone = currentBone();
    if (!bone) return;
    const busy = locked();
    $('creatureBoneFields').disabled = busy;
    motion.disabled = busy;
    const count = segments.valueAsNumber;
    const fits = Number.isInteger(count) && count >= 1 && count <= 64 && !samePoint(bone.head, bone.tail);
    add.disabled = !fits || draft.bones.length + count > draft.limit;
    split.disabled = !fits || count < 2 || draft.bones.length + count - 1 > draft.limit;
    remove.disabled = bone.parent === null;
    parent.disabled = bone.parent === null;
    for (const point of endpoints) places[point].disabled = busy || !viewer?.active;
    $('creatureCompleteRig').disabled = busy;
    $('creatureResetDraft').disabled = busy;
  }

  function refreshViewer() {
    const bone = currentBone();
    if (!bone) return;
    if (locked()) {
      setPlacement(null);
      viewer?.close();
    } else {
      viewer?.show(draft.bones, bone.name, move, () => setPlacement(null));
    }
    refreshControls();
  }

  function showBone(selected) {
    selection.replaceChildren(...draft.bones.map(bone => option(bone.name)));
    selection.value = selected || draft.bones.find(bone => bone.parent === null)?.name || draft.bones[0].name;
    const bone = currentBone();
    if (!bone) return;
    const excluded = descendants(draft.bones, bone.name);
    parent.replaceChildren(...(bone.parent === null
      ? [option('', 'Root bone')]
      : draft.bones.filter(other => !excluded.has(other.name)).map(other => option(other.name))));
    parent.value = bone.parent ?? '';
    name.value = bone.name;
    name.setCustomValidity('');
    $('creatureBoneCount').textContent = `${draft.bones.length} / ${draft.limit} bones`;
    setPlacement(null);
    syncPoints(bone);
  }

  function syncPoints(bone) {
    for (const endpoint of endpoints) vectors[endpoint].forEach((input, axis) => {
      input.value = Number(bone[endpoint][axis].toPrecision(7));
    });
    refreshViewer();
  }

  function move(endpoint, position) {
    const bone = currentBone();
    if (locked() || !bone) return;
    moveBonePoint(draft.bones, bone, endpoint, position, connected.checked);
    syncPoints(bone);
  }

  for (const point of endpoints) {
    places[point].onclick = () => setPlacement(placement === point ? null : point);
  }
  selection.onchange = () => showBone(selection.value);
  parent.onchange = () => {
    const bone = currentBone();
    if (bone?.parent) bone.parent = parent.value;
  };
  name.oninput = () => name.setCustomValidity('');
  name.onchange = () => {
    const bone = currentBone();
    const next = name.value.trim();
    if (!bone || next === bone.name) return;
    if (!next || new TextEncoder().encode(next).length > 63 || /\p{C}/u.test(next)
        || draft.bones.some(other => other.name === next)) {
      name.setCustomValidity('Choose a unique bone name of up to 63 bytes.');
      name.reportValidity();
      return;
    }
    for (const child of draft.bones) if (child.parent === bone.name) child.parent = next;
    bone.name = next;
    showBone(next);
  };
  segments.oninput = refreshControls;
  add.onclick = () => showBone(addBoneChain(draft.bones, currentBone(), segments.valueAsNumber));
  split.onclick = () => {
    const bone = currentBone();
    addBoneChain(draft.bones, bone, segments.valueAsNumber, true);
    showBone(bone.name);
  };
  remove.onclick = () => {
    const bone = currentBone();
    if (!bone?.parent) return;
    const branch = descendants(draft.bones, bone.name);
    draft.bones = draft.bones.filter(other => !branch.has(other.name));
    showBone(bone.parent);
  };
  $('creatureResetDraft').onclick = () => {
    draft.bones = structuredClone(draft.predicted);
    showBone();
    status.textContent = 'Original prediction restored.';
  };

  async function loadDraft(id) {
    if (loading || !id) return;
    const request = {id};
    loading = request;
    retry.hidden = true;
    status.textContent = 'Loading the predicted skeleton…';
    try {
      const data = await api(`/api/jobs/${encodeURIComponent(id)}/rig-preview`, {cache: 'no-store'});
      if (loading !== request || target !== id) return;
      if (!data.ready || data.aligned_to_model !== true || !Array.isArray(data.bones) || !data.bones.length
          || !/^[a-f0-9]{64}$/.test(data.revision)) throw Error('The editable skeleton is unavailable.');
      draft = {id, revision: data.revision, predicted: data.bones,
        bones: structuredClone(data.edited_bones || data.bones), limit: data.max_bones || 512};
      motion.value = [...motion.options].some(item => item.value === data.motion) ? data.motion : defaultMotion;
      connected.checked = true;
      segments.value = 3;
      form.hidden = false;
      status.textContent = 'Check joint placement before calculating skin weights.';
      showBone();
    } catch (error) {
      if (loading === request) {
        status.textContent = error.message;
        retry.hidden = false;
      }
    } finally {
      if (loading === request) loading = null;
    }
  }

  retry.onclick = () => loadDraft(target);

  form.onsubmit = async event => {
    event.preventDefault();
    if (!draft || draft.id !== target || locked()) return;
    const invalid = draft.bones.find(bone => samePoint(bone.head, bone.tail));
    if (invalid) {
      showBone(invalid.name);
      status.textContent = `Move one endpoint of ${invalid.name} before continuing.`;
      return;
    }
    const request = draft;
    saving = request;
    refreshViewer();
    status.textContent = 'Queuing skin weights…';
    try {
      const result = await api(`/api/jobs/${encodeURIComponent(request.id)}/rig-complete`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({revision: request.revision, bones: request.bones, motion: motion.value}),
      });
      if (draft === request) draft = null;
      if (target === request.id) close();
      await startJob(result.id, {rig: true});
    } catch (error) {
      if (target === request.id) {
        status.textContent = error.message;
        retry.hidden = false;
      }
    } finally {
      if (saving === request) saving = null;
      refreshViewer();
    }
  };

  function close() {
    setPlacement(null);
    viewer?.close();
    panel.hidden = true;
    form.hidden = true;
    loading = null;
    target = null;
    onVisibility(false);
  }

  return {
    close,
    sync(job, enabled) {
      if (!enabled || !isCreatureRigDraft(job) || !['done', 'error', 'cancelled'].includes(job.state)) {
        if (target) close();
        if (draft && job?.id !== draft.id) draft = null;
        return false;
      }
      if (target !== job.id) {
        if (target) close();
        target = job.id;
        panel.hidden = false;
        onVisibility(true);
        if (draft?.id === target) {
          form.hidden = false;
          showBone(selection.value);
        } else {
          draft = null;
          void loadDraft(target);
        }
      } else if (draft) refreshViewer();
      return true;
    },
  };
}
