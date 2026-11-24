import * as THREE from 'three';

const vector = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);

export function motionObstacles(gltf, result) {
  return gltf.animations.map((clip, index) => {
    const saved = gltf.parser?.json?.animations?.[index]?.extras?.trellis_obstacle;
    const box = saved ?? result?.animation_set?.find(entry => entry.clip === clip.name)?.obstacle;
    if (box?.type !== 'box' || !vector(box.center) || !vector(box.size) || !box.size.every(n => n > 0)) return null;
    return box;
  });
}

export function playPreviewAction(action, withObstacle) {
  if (withObstacle) {
    action.setLoop(THREE.LoopOnce,1);
    action.clampWhenFinished=true;
    if (action.time >= action.getClip().duration) action.reset();
  }
  action.paused=false;
  action.play();
}

// Frame the travel from the supporting-hand side, accounting for portrait cards and wide viewports.
export function obstacleFraming(bounds, camera, heading) {
  const center = bounds.getCenter(new THREE.Vector3());
  const back = new THREE.Vector3(-.92,.27,.38).normalize();
  if (heading) back.applyAxisAngle(new THREE.Vector3(0,1,0),Math.atan2(heading.x,heading.z));
  const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),back).normalize();
  const up = new THREE.Vector3().crossVectors(back,right);
  const tan = Math.tan(THREE.MathUtils.degToRad(camera.fov)/2);
  let distance = camera.near;
  for (const x of [bounds.min.x,bounds.max.x]) for (const y of [bounds.min.y,bounds.max.y]) {
    for (const z of [bounds.min.z,bounds.max.z]) {
      const delta = new THREE.Vector3(x,y,z).sub(center);
      const extent = Math.max(Math.abs(delta.dot(up)),Math.abs(delta.dot(right))/camera.aspect);
      distance = Math.max(distance,delta.dot(back)+1.12*extent/tan);
    }
  }
  return {center,eye:center.clone().addScaledVector(back,distance),distance};
}

// The crate is a viewer prop in GLB coordinates, separate from the editable mesh.
export function createObstaclePreview(scene) {
  let marker, owner, descriptor;
  function clear() {
    if (!marker) return;
    scene.remove(marker);
    marker.traverse(part => { part.geometry?.dispose(); part.material?.dispose(); });
    marker = owner = descriptor = null;
  }
  function sync() {
    if (!marker) return;
    owner.updateWorldMatrix(true, false);
    marker.matrix.copy(owner.matrixWorld);
    marker.matrixWorldNeedsUpdate = true;
    marker.visible = owner.visible;
  }
  return {
    get active() { return Boolean(marker); },
    get heading() {
      const heading = descriptor?.heading ?? descriptor?.travel;
      if (!marker || !vector(heading)) return null;
      return new THREE.Vector3(...heading).transformDirection(marker.matrix);
    },
    clear, sync,
    hide() { if (marker) marker.visible = false; },
    set(root, box) {
      clear();
      if (!box || !root) return;
      owner = root;
      descriptor = box;
      marker = new THREE.Group();
      marker.name = 'Motion obstacle preview';
      marker.matrixAutoUpdate = false;
      const geometry = new THREE.BoxGeometry(...box.size);
      const crate = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({color:0x986637, roughness:.86}));
      crate.position.fromArray(box.center);
      const heading = box.heading ?? box.travel;
      if (vector(heading)) crate.rotation.y = Math.atan2(heading[0],heading[2]);
      crate.receiveShadow = true;
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({color:0x49311f}));
      crate.add(edges);
      marker.add(crate);
      scene.add(marker);
      sync();
    },
    expandBounds(bounds) {
      if (!marker) return;
      sync();
      bounds.union(new THREE.Box3().setFromObject(marker));
      if (vector(descriptor.travel)) {
        const center = new THREE.Vector3().fromArray(descriptor.center);
        const travel = new THREE.Vector3().fromArray(descriptor.travel);
        for (const sign of [-.62, .62]) {
          bounds.expandByPoint(center.clone().addScaledVector(travel, sign).applyMatrix4(marker.matrix));
        }
      }
    }
  };
}
