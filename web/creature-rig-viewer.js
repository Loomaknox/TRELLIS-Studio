import * as THREE from 'three';
import {t} from './i18n.js';

export function createCreatureRigViewer({scene, camera, controls, viewport, getModel, showViewport, stopRotation}) {
  const geometry = new THREE.BufferGeometry();
  const material = new THREE.LineBasicMaterial({depthTest: false, depthWrite: false, vertexColors: true});
  const lines = new THREE.LineSegments(geometry, material);
  lines.renderOrder = 14;
  lines.frustumCulled = false;
  const overlay = document.createElement('div');
  overlay.className = 'rig-landmark-overlay creature-rig-overlay';
  overlay.hidden = true;
  viewport.append(overlay);
  const normal = new THREE.Color(0xbfe98c);
  const highlight = new THREE.Color(0xffc780);
  const ray = new THREE.Raycaster();
  const plane = new THREE.Plane();
  const hit = new THREE.Vector3();
  const point = new THREE.Vector3();
  let selected = null, model = null, drag = null, onMove = null;
  const handles = {};
  for (const endpoint of ['head', 'tail']) {
    const button = document.createElement('button');
    const label = t(endpoint === 'head' ? 'Drag bone start' : 'Drag bone end');
    button.type = 'button';
    button.className = `rig-landmark creature-rig-point creature-rig-${endpoint}`;
    button.title = label;
    button.setAttribute('aria-label', label);
    button.addEventListener('pointerdown', event => {
      if (!selected || !model || event.button !== 0 || drag) return;
      event.stopPropagation();
      event.preventDefault();
      camera.getWorldDirection(plane.normal);
      plane.setFromNormalAndCoplanarPoint(plane.normal, point.fromArray(selected[endpoint]));
      const start = pointerPoint(event);
      if (!start) return;
      const offset = point.clone().sub(start);
      drag = {endpoint, pointerId: event.pointerId, enabled: controls.enabled, offset};
      controls.enabled = false;
      button.setPointerCapture(event.pointerId);
    });
    button.addEventListener('pointermove', event => {
      if (!drag || drag.pointerId !== event.pointerId || drag.endpoint !== endpoint) return;
      const result = pointerPoint(event);
      if (result) onMove?.(endpoint, result.add(drag.offset).toArray());
    });
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(type, endDrag);
    overlay.append(button);
    handles[endpoint] = button;
  }

  function pointerPoint(event) {
    const rect = viewport.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(
      (event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2,
    ), camera);
    return ray.ray.intersectPlane(plane, hit);
  }

  function endDrag(event) {
    if (!drag || (event && drag.pointerId !== event.pointerId)) return;
    const current = drag;
    drag = null;
    controls.enabled = current.enabled;
    const button = handles[current.endpoint];
    if (button.hasPointerCapture(current.pointerId)) button.releasePointerCapture(current.pointerId);
  }

  function update() {
    if (!model || !selected) return;
    const {clientWidth:width, clientHeight:height} = viewport;
    for (const [endpoint, button] of Object.entries(handles)) {
      point.fromArray(selected[endpoint]).project(camera);
      button.hidden = point.z < -1 || point.z > 1;
      button.style.left = `${(point.x + 1) * width * .5}px`;
      button.style.top = `${(1 - point.y) * height * .5}px`;
    }
  }

  function show(bones, selectedName, onChange) {
    const current = getModel();
    if (!current) {close(); return;}
    if (current !== model) {
      model = current;
      stopRotation();
      showViewport();
      scene.add(lines);
      overlay.hidden = false;
    }
    selected = bones.find(bone => bone.name === selectedName);
    onMove = onChange;
    const vertexCount = bones.length * 2;
    if (geometry.getAttribute('position')?.count !== vertexCount) {
      geometry.dispose();
      for (const key of ['position', 'color']) {
        geometry.setAttribute(key, new THREE.BufferAttribute(new Float32Array(vertexCount * 3), 3).setUsage(THREE.DynamicDrawUsage));
      }
    }
    const positions = geometry.getAttribute('position'), colors = geometry.getAttribute('color');
    bones.forEach((bone, index) => {
      positions.setXYZ(index * 2, ...bone.head);
      positions.setXYZ(index * 2 + 1, ...bone.tail);
      const color = bone === selected ? highlight : normal;
      colors.setXYZ(index * 2, color.r, color.g, color.b);
      colors.setXYZ(index * 2 + 1, color.r, color.g, color.b);
    });
    positions.needsUpdate = true;
    colors.needsUpdate = true;
    update();
  }

  function close() {
    if (!model) return;
    endDrag();
    model = selected = onMove = null;
    overlay.hidden = true;
    scene.remove(lines);
  }

  return {show, close, update, get active() {return model !== null;}};
}
