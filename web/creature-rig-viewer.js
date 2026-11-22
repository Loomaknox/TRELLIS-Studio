import * as THREE from 'three';

export function createCreatureRigViewer({scene, camera, controls, viewport, getModel, stopRotation}) {
  const geometry = new THREE.BufferGeometry();
  const material = new THREE.LineBasicMaterial({depthTest: false, depthWrite: false, vertexColors: true});
  const lines = new THREE.LineSegments(geometry, material);
  lines.renderOrder = 14;
  lines.frustumCulled = false;
  const overlay = document.createElement('div');
  overlay.className = 'rig-landmark-overlay creature-rig-overlay';
  overlay.hidden = true;
  viewport.append(overlay);
  const handles = {};
  const ray = new THREE.Raycaster();
  const plane = new THREE.Plane();
  const pointer = new THREE.Vector2();
  const hit = new THREE.Vector3();
  const point = new THREE.Vector3();
  const normal = new THREE.Color(0xbfe98c), highlight = new THREE.Color(0xffc780);
  let selected = null, model = null, drag = null, onMove = null, onPlaced = null;
  let placement = null, nudge = 0.01;

  function aim(event) {
    const rect = viewport.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2);
    ray.setFromCamera(pointer, camera);
    return true;
  }

  function endDrag(event) {
    if (!drag || (event && drag.pointerId !== event.pointerId)) return;
    const current = drag;
    drag = null;
    controls.enabled = current.enabled;
    const button = handles[current.endpoint];
    if (button.hasPointerCapture(current.pointerId)) button.releasePointerCapture(current.pointerId);
  }

  for (const endpoint of ['head', 'tail']) {
    const button = document.createElement('button');
    const label = endpoint === 'head' ? 'Bone start' : 'Bone end';
    button.type = 'button';
    button.className = `rig-landmark creature-rig-point creature-rig-${endpoint}`;
    button.title = `${label} · drag or use arrow keys`;
    button.setAttribute('aria-label', button.title);
    button.textContent = endpoint === 'head' ? 'S' : 'E';
    button.addEventListener('pointerdown', event => {
      if (!selected || !model || placement || event.button !== 0 || drag || !aim(event)) return;
      camera.getWorldDirection(plane.normal);
      plane.setFromNormalAndCoplanarPoint(plane.normal, point.fromArray(selected[endpoint]));
      if (!ray.ray.intersectPlane(plane, hit)) return;
      event.stopPropagation();
      event.preventDefault();
      drag = {endpoint, pointerId: event.pointerId, enabled: controls.enabled, offset: point.clone().sub(hit)};
      controls.enabled = false;
      button.setPointerCapture(event.pointerId);
    });
    button.addEventListener('pointermove', event => {
      if (!drag || drag.pointerId !== event.pointerId || drag.endpoint !== endpoint || !aim(event)) return;
      if (ray.ray.intersectPlane(plane, hit)) onMove?.(endpoint, hit.add(drag.offset).toArray());
    });
    button.addEventListener('keydown', event => {
      const move = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1]}[event.key];
      if (!move || !selected || placement) return;
      event.preventDefault();
      const step = nudge * (event.shiftKey ? 5 : 1);
      hit.set(move[0] * step, move[1] * step, 0).applyQuaternion(camera.quaternion);
      onMove?.(endpoint, point.fromArray(selected[endpoint]).add(hit).toArray());
    });
    for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(event, endDrag);
    handles[endpoint] = button;
    overlay.append(button);
  }

  viewport.addEventListener('pointerdown', event => {
    if (!placement || !model || event.button !== 0 || !event.target.closest('canvas')) return;
    event.preventDefault();
    event.stopPropagation();
    if (!aim(event)) return;
    const match = ray.intersectObject(model, true)[0];
    if (!match) return;
    onMove?.(placement, match.point.toArray());
    onPlaced?.();
  }, {capture: true});

  document.addEventListener('keydown', event => {
    if (placement && event.key === 'Escape') {
      event.preventDefault();
      onPlaced?.();
    }
  });

  function update() {
    if (!model || !selected) return;
    const {clientWidth: width, clientHeight: height} = viewport;
    for (const [endpoint, button] of Object.entries(handles)) {
      point.fromArray(selected[endpoint]).project(camera);
      button.hidden = Math.abs(point.x) > 1 || Math.abs(point.y) > 1 || Math.abs(point.z) > 1;
      button.style.left = `${(point.x + 1) * width * .5}px`;
      button.style.top = `${(1 - point.y) * height * .5}px`;
    }
  }

  function show(bones, name, move, placed) {
    const current = getModel();
    if (!current) {close();return;}
    if (model !== current) {
      model = current;
      stopRotation();
      model.rotation.y = 0;
      model.updateMatrixWorld(true);
      const scale = new THREE.Box3().setFromObject(model).getSize(point).length();
      nudge = Math.max(scale * .002, 1e-6);
      scene.add(lines);
      overlay.hidden = false;
    }
    selected = bones.find(bone => bone.name === name);
    onMove = move;
    onPlaced = placed;
    const size = bones.length * 2;
    if (geometry.getAttribute('position')?.count !== size) {
      geometry.dispose();
      for (const key of ['position', 'color']) {
        geometry.setAttribute(key, new THREE.BufferAttribute(new Float32Array(size * 3), 3).setUsage(THREE.DynamicDrawUsage));
      }
    }
    const positions = geometry.getAttribute('position'), colors = geometry.getAttribute('color');
    bones.forEach((bone, index) => {
      const color = bone === selected ? highlight : normal;
      positions.setXYZ(index * 2, ...bone.head);
      positions.setXYZ(index * 2 + 1, ...bone.tail);
      colors.setXYZ(index * 2, color.r, color.g, color.b);
      colors.setXYZ(index * 2 + 1, color.r, color.g, color.b);
    });
    positions.needsUpdate = colors.needsUpdate = true;
    update();
  }

  function place(endpoint) {
    placement = model && endpoint ? endpoint : null;
    viewport.classList.toggle('creature-picking', Boolean(placement));
  }

  function close() {
    endDrag();
    place(null);
    model = selected = onMove = onPlaced = null;
    overlay.hidden = true;
    scene.remove(lines);
  }

  return {show, close, update, place, get active() {return model !== null;}};
}
