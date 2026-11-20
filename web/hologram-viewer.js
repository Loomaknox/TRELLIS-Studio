import * as THREE from 'three';

const hologramPalette = {
  material: '#b8ef69',
  beam: '174, 229, 91',
  contact: '230, 255, 172',
  trail: '191, 235, 133',
};

export function hologramConstruction(elapsed, reducedMotion = false) {
  const time = reducedMotion ? 0 : Math.max(0, Number.isFinite(elapsed) ? elapsed : 0);
  const progress = reducedMotion ? 1 : Math.min(1, time / 6.5);
  return {time, progress, reveal: progress * 1.04, constructing: !reducedMotion && progress < 1};
}

// Preview materials share texture references, but never mutate the source material
// or geometry. Three's skinning and morph chunks run before our world-position read.
export function createHologramMaterial(source, uniforms) {
  const material = new THREE.MeshStandardMaterial({
    color: source.color || 0xffffff, map: source.map || null,
    normalMap: source.normalMap || null, side: source.side,
    alphaMap: source.alphaMap || null, alphaTest: source.alphaTest || 0,
    transparent: source.transparent, opacity: source.opacity,
    roughness: 1, metalness: 0, depthWrite: source.depthWrite,
  });
  if (source.normalScale) material.normalScale.copy(source.normalScale);
  material.name = 'Hologram preview';
  material.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = 'varying vec3 vHologramPosition;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace('#include <project_vertex>',
      `#include <project_vertex>
vec4 hologramPosition = vec4(transformed, 1.0);
#ifdef USE_BATCHING
hologramPosition = batchingMatrix * hologramPosition;
#endif
#ifdef USE_INSTANCING
hologramPosition = instanceMatrix * hologramPosition;
#endif
vHologramPosition = (modelMatrix * hologramPosition).xyz;`);
    shader.fragmentShader = `uniform float hologramTime;
uniform float hologramBottom;
uniform float hologramHeight;
uniform float hologramReveal;
uniform float hologramConstructing;
uniform vec3 hologramColour;
varying vec3 vHologramPosition;
` + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>', `
float holoY = (vHologramPosition.y - hologramBottom) / hologramHeight;
if (hologramConstructing > 0.5 && holoY > hologramReveal) discard;
float holoRim = pow(clamp(1.0 - abs(dot(normalize(normal), normalize(vViewPosition))), 0.0, 1.0), 2.4);
float holoLines = pow(0.5 + 0.5 * sin(holoY * 640.0), 14.0);
float holoScan = exp(-pow((fract(holoY - hologramTime * 0.09) - 0.5) / 0.012, 2.0));
float holoFront = exp(-pow((holoY - hologramReveal) / 0.012, 2.0)) * hologramConstructing;
float holoLight = 0.042 + holoRim * 0.76 + holoLines * 0.13 + holoScan * 0.16 + holoFront * 0.85;
outgoingLight = diffuseColor.rgb * 0.20 + hologramColour * holoLight;
#include <opaque_fragment>`);
  };
  material.customProgramCacheKey = () => 'trellis-hologram-v3';
  return material;
}

export function createHologramViewer(viewport, {camera} = {}) {
  const uniforms = {
    hologramTime: {value: 0}, hologramBottom: {value: 0},
    hologramHeight: {value: 1}, hologramColour: {value: new THREE.Color(hologramPalette.material)},
    hologramReveal: {value: 0}, hologramConstructing: {value: 1},
  };
  const canvas = document.createElement('canvas');
  canvas.setAttribute('aria-hidden', 'true');
  canvas.className = 'hologram-overlay';
  canvas.style.cssText = 'position:absolute;inset:0;pointer-events:none;width:100%;height:100%;display:none;';
  canvas.hidden = true;
  viewport.querySelector('canvas')?.after(canvas);
  const context = canvas.getContext('2d');
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let enabled = false, lastDraw = -Infinity, width = 0, height = 0;
  let root = null, samples = [], triangleSamples = [], startedAt = null;
  const symbols = '01ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const hash = value => {const x = Math.sin(value * 127.1) * 43758.5453;return x - Math.floor(x);};
  const motionChanged = () => {lastDraw = -Infinity;startedAt = null;};
  motion.addEventListener('change', motionChanged);

  function collectSurface(model) {
    samples = [];triangleSamples = [];
    if (!model) return;
    const meshes = [];
    model.traverse(mesh => {if (mesh.isMesh && mesh.geometry?.attributes.position && (!mesh.isInstancedMesh || mesh.count > 0)) meshes.push(mesh);});
    const total = meshes.reduce((count, mesh) => count + mesh.geometry.attributes.position.count, 0);
    const triangleCount = mesh => Math.floor((mesh.geometry.index?.count || mesh.geometry.attributes.position.count) / 3);
    const totalTriangles = meshes.reduce((count, mesh) => count + triangleCount(mesh), 0);
    for (const mesh of meshes) {
      const count = mesh.geometry.attributes.position.count;
      const quota = Math.max(1, Math.floor(1800 * count / Math.max(total, 1)));
      const instances = mesh.isInstancedMesh ? Math.min(mesh.count, 32) : 1;
      for (let i = 0; i < quota; i++) samples.push({mesh, index: Math.min(count - 1, Math.floor(i * count / quota)),
        instance: mesh.isInstancedMesh ? i % instances : null, point: new THREE.Vector3()});
      const triangles = triangleCount(mesh), triangleQuota = Math.min(triangles, Math.max(1, Math.floor(1200 * triangles / Math.max(1, totalTriangles))));
      for (let i = 0; i < triangleQuota; i++) {
        const face = Math.floor(i * triangles / triangleQuota) * 3;
        const indices = [0, 1, 2].map(offset => mesh.geometry.index ? mesh.geometry.index.getX(face + offset) : face + offset);
        triangleSamples.push({mesh, indices, instance: mesh.isInstancedMesh ? i % instances : null,
          points: indices.map(() => new THREE.Vector3())});
      }
    }
  }

  const instanceMatrix = new THREE.Matrix4();
  function surfaceTargets(reveal, w, h) {
    if (!camera || !root || !samples.length) return [];
    root.updateMatrixWorld(true);
    camera.updateMatrixWorld();
    const skeletons = new Set(samples.filter(sample => sample.mesh.isSkinnedMesh).map(sample => sample.mesh.skeleton));
    skeletons.forEach(skeleton => skeleton.update());
    const plane = uniforms.hologramBottom.value + reveal * uniforms.hologramHeight.value;
    const readWorld = (sample, index, point) => {
      sample.mesh.getVertexPosition(index, point);
      if (sample.instance !== null) {
        sample.mesh.getMatrixAt(sample.instance, instanceMatrix);
        point.applyMatrix4(instanceMatrix);
      }
      point.applyMatrix4(sample.mesh.matrixWorld);
    };
    // Sample a bounded set of real deformed vertices, never the whole dense mesh.
    const candidates = [];
    for (const sample of samples) {
      readWorld(sample, sample.index, sample.point);
      const distance = Math.abs(sample.point.y - plane);
      if (distance < uniforms.hologramHeight.value * 0.045) candidates.push({sample, distance});
    }
    candidates.sort((a, b) => a.distance - b.distance);
    const points = [];
    for (const {sample} of candidates.slice(0, 64)) {
      const point = sample.point.clone();
      point.y = plane;
      points.push(point);
    }
    // Sparse meshes can have no vertices near the scan plane (a simple box, for
    // example). Intersect sampled triangle edges instead of losing their beams.
    if (!points.length) for (const sample of triangleSamples) {
      sample.indices.forEach((index, i) => readWorld(sample, index, sample.points[i]));
      for (let i = 0; i < 3; i++) {
        const a = sample.points[i], b = sample.points[(i + 1) % 3], delta = b.y - a.y;
        if (Math.abs(delta) < 1e-9) continue;
        const t = (plane - a.y) / delta;
        if (t >= 0 && t <= 1) points.push(a.clone().lerp(b, t));
      }
      if (points.length >= 64) break;
    }
    const targets = [];
    for (const point of points) {
      point.project(camera);
      if (point.z < -1 || point.z > 1) continue;
      const x = (point.x * 0.5 + 0.5) * w, y = (-point.y * 0.5 + 0.5) * h;
      if (x > 0 && x < w && y > 0 && y < h) targets.push({x, y});
    }
    return targets.sort((a, b) => a.x - b.x);
  }

  function drawLasers(frame, w, h) {
    if (!frame.constructing || motion.matches) return;
    const targets = surfaceTargets(frame.reveal, w, h);
    if (!targets.length) return;
    const strength = Math.min(1, frame.progress * 12) * Math.min(1, (1 - frame.progress) * 16);
    const emitters = [[w * 0.09, h * 0.15], [w * 0.91, h * 0.12], [w * 0.5, h * 0.04]];
    context.save();
    context.globalCompositeOperation = 'lighter';
    for (const [emitter, origin] of emitters.entries()) {
      for (let beam = 0; beam < 4; beam++) {
        const sweep = (Math.sin(frame.time * (1.1 + beam * 0.17) + emitter * 2.1 + beam) + 1) * 0.5;
        const target = targets[Math.min(targets.length - 1, Math.floor(sweep * targets.length))];
        const gradient = context.createLinearGradient(origin[0], origin[1], target.x, target.y);
        gradient.addColorStop(0, `rgba(${hologramPalette.beam}, ${0.03 * strength})`);
        gradient.addColorStop(0.75, `rgba(${hologramPalette.beam}, ${0.20 * strength})`);
        gradient.addColorStop(1, `rgba(${hologramPalette.contact}, ${0.62 * strength})`);
        context.strokeStyle = gradient;
        context.lineWidth = 0.85;
        context.beginPath();context.moveTo(...origin);context.lineTo(target.x, target.y);context.stroke();
        const glow = context.createRadialGradient(target.x, target.y, 0, target.x, target.y, 7);
        glow.addColorStop(0, `rgba(${hologramPalette.contact}, ${0.48 * strength})`);
        glow.addColorStop(0.2, `rgba(${hologramPalette.beam}, ${0.22 * strength})`);
        glow.addColorStop(1, `rgba(${hologramPalette.beam}, 0)`);
        context.fillStyle = glow;context.fillRect(target.x - 7, target.y - 7, 14, 14);
      }
    }
    context.restore();
  }

  function draw(frame) {
    if (!context) return;
    const time = frame.time;
    // Keep the overlay bounded on high-DPI screens; it is decorative, not texture data.
    const w = Math.min(1920, Math.max(1, viewport.clientWidth));
    const h = Math.max(1, Math.round(viewport.clientHeight * w / Math.max(1, viewport.clientWidth)));
    const resized = width !== w || height !== h;
    if (resized) {canvas.width = width = w;canvas.height = height = h;}
    if (!resized && (time - lastDraw < 1 / 30 || motion.matches && lastDraw !== -Infinity)) return;
    lastDraw = time;
    context.clearRect(0, 0, w, h);
    const size = Math.max(11, Math.min(16, w / 90));
    context.font = `${size}px monospace`;
    // Leave the centre relatively clear so the model, facial detail and silhouette read.
    for (let column = 0; column < Math.ceil(w / 25); column++) {
      const x = (column + 0.5) * 25;
      const edge = Math.pow(Math.abs(x / w - 0.5) * 2, 1.5);
      if (edge < 0.2 || hash(column + 2) > 0.62) continue;
      const speed = 22 + hash(column + 27) * 28;
      const head = (hash(column + 11) * (h + 300) + time * speed) % (h + 300) - 80;
      for (let row = 0; row < 13; row++) {
        const y = head - row * size * 1.1;
        if (y < 35 || y > h - 45) continue;
        const alpha = (1 - row / 13) * edge * 0.32;
        context.fillStyle = `rgba(${hologramPalette.trail}, ${alpha})`;
        const index = Math.floor(hash(column * 53 + row + Math.floor(time * 3)) * symbols.length);
        context.fillText(symbols[index], x, y);
      }
    }
    drawLasers(frame, w, h);
  }

  return {
    material(source) {return createHologramMaterial(source, uniforms);},
    setModel(model, active) {
      const restarting = !enabled || root !== model;
      enabled = !!model && active;
      if (root !== model) {root = model;collectSurface(model);}
      canvas.hidden = !enabled;
      canvas.style.display = enabled ? 'block' : 'none';
      lastDraw = -Infinity;
      if (!enabled) return;
      if (restarting) startedAt = null;
      model.updateMatrixWorld(true);
      model.traverse(mesh => {if (mesh.isSkinnedMesh) mesh.skeleton.update();});
      const box = new THREE.Box3().setFromObject(model, true);
      if (!box.isEmpty()) {
        uniforms.hologramBottom.value = box.min.y;
        uniforms.hologramHeight.value = Math.max(0.001, box.max.y - box.min.y);
      }
    },
    update(milliseconds) {
      if (!enabled) return;
      if (startedAt === null) startedAt = milliseconds;
      const frame = hologramConstruction((milliseconds - startedAt) / 1000, motion.matches);
      uniforms.hologramTime.value = frame.time;
      uniforms.hologramReveal.value = frame.reveal;
      uniforms.hologramConstructing.value = frame.constructing ? 1 : 0;
      draw(frame);
    },
    restart() {startedAt = null;lastDraw = -Infinity;},
    clear() {enabled = false;root = null;samples = [];triangleSamples = [];startedAt = null;canvas.hidden = true;canvas.style.display = 'none';},
    dispose() {enabled = false;root = null;samples = [];triangleSamples = [];motion.removeEventListener('change', motionChanged);canvas.remove();},
  };
}
