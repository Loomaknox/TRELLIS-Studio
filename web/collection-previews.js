import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';

const width = 384;
const height = 310;
const cacheLimit = 48;
const textureLimit = 1024;
const persistedLimit = 128;
const persistedCache = 'trellis-collection-previews-v1';

function imageBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Preview capture failed.')), 'image/webp', .9);
  });
}

async function browserSnapshots(entry, snapshots) {
  try {
    const store = await globalThis.caches?.open(persistedCache);
    if (!store) return null;
    const keys = ['textured', 'neutral'].map(mode => {
      const key = new URL(entry.url);
      key.searchParams.set('collection-preview', mode);
      key.searchParams.set('collection-revision', entry.revision ?? '');
      return key.href;
    });
    if (!snapshots) {
      const [textured, neutral] = await Promise.all(keys.map(key => store.match(key)));
      if (!textured || !neutral) return null;
      return {textured: await textured.blob(), neutral: await neutral.blob()};
    }
    const images = [snapshots.textured, snapshots.neutral];
    await Promise.all(keys.map((key, index) => store.put(key,
      new Response(images[index], {headers: {'Content-Type': images[index].type}}))));
    const stored = await store.keys();
    const extra = stored.length - 2 * persistedLimit;
    if (extra > 0) await Promise.all(stored.slice(0, extra).map(key => store.delete(key)));
  } catch {
    // Private browsing, browser policy and quota can leave only the in-memory cache.
  }
  return null;
}

function reducePreviewTextures(model) {
  const thumbnails = new Map();
  model.traverse(object => {
    for (const material of [].concat(object.material || [])) {
      for (const texture of Object.values(material)) {
        if (!texture?.isTexture || texture.isCompressedTexture) continue;
        const image = texture.image;
        const dimension = Math.max(image?.width || 0, image?.height || 0);
        if (dimension <= textureLimit) continue;
        if (!thumbnails.has(image)) {
          const canvas = document.createElement('canvas');
          const scale = textureLimit / dimension;
          canvas.width = Math.max(1, Math.round(image.width * scale));
          canvas.height = Math.max(1, Math.round(image.height * scale));
          const context = canvas.getContext('2d');
          if (!context) continue;
          try {
            context.drawImage(image, 0, 0, canvas.width, canvas.height);
          } catch {
            continue;
          }
          thumbnails.set(image, canvas);
        }
        texture.image = thumbnails.get(image);
        texture.needsUpdate = true;
      }
    }
  });
  for (const image of thumbnails.keys()) {
    if (typeof image.close === 'function') image.close();
  }
}

function createCapture() {
  const renderer = new THREE.WebGLRenderer({alpha: true, antialias: true, preserveDrawingBuffer: true});
  renderer.setSize(width, height, false);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  const scene = new THREE.Scene();
  const generator = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const environment = generator.fromScene(room, .04);
  scene.environment = environment.texture;
  room.dispose();
  generator.dispose();
  scene.add(new THREE.HemisphereLight(0xf8fff3, 0x67737d, 1.1));
  const key = new THREE.DirectionalLight(0xfff5e6, 2);
  key.position.set(-2, 3, 4);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xd9eaff, .9);
  rim.position.set(3, 1, -1);
  scene.add(rim);
  const clay = new THREE.MeshStandardMaterial({color: 0xb6bbc0, roughness: .85});
  const clayFlat = clay.clone();
  clayFlat.flatShading = true;
  const camera = new THREE.OrthographicCamera();
  const view = new THREE.Vector3(.22, .13, 1).normalize();

  function disposeModels(scenes, materials) {
    const geometries = new Set();
    const skeletons = new Set();
    const textures = new Set();
    const images = new Set();
    for (const model of scenes) model.traverse(object => {
      if (object.geometry) geometries.add(object.geometry);
      if (object.skeleton) skeletons.add(object.skeleton);
      for (const material of [].concat(object.material || [])) {
        if (material !== clay && material !== clayFlat) materials.add(material);
      }
    });
    for (const material of materials) {
      for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
      material.dispose();
    }
    for (const texture of textures) {
      for (const image of [].concat(texture.image || [])) if (typeof image.close === 'function') images.add(image);
      texture.dispose();
    }
    for (const image of images) image.close();
    for (const geometry of geometries) geometry.dispose();
    for (const skeleton of skeletons) skeleton.dispose();
    renderer.renderLists.dispose();
  }

  return {
    async render(bytes, signal) {
      const gltf = await new GLTFLoader().parseAsync(bytes, '');
      const model = gltf.scene;
      const originals = new Set();
      try {
        signal.throwIfAborted();
        reducePreviewTextures(model);
        scene.add(model);
        model.updateWorldMatrix(true, true);
        const bounds = new THREE.Box3().setFromObject(model);
        const centre = bounds.getCenter(new THREE.Vector3());
        const size = bounds.getSize(new THREE.Vector3());
        const span = size.length();
        if (!Number.isFinite(span) || span <= 0) throw new Error('The model has no preview bounds.');
        camera.position.copy(centre).addScaledVector(view, span * 2.5);
        camera.lookAt(centre);
        camera.updateMatrixWorld();
        const projection = column => {
          const axis = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, column);
          return Math.abs(axis.x) * size.x + Math.abs(axis.y) * size.y + Math.abs(axis.z) * size.z;
        };
        const aspect = width / height;
        const y = Math.max(projection(1), projection(0) / aspect) * .55;
        camera.left = -y * aspect;
        camera.right = y * aspect;
        camera.top = y;
        camera.bottom = -y;
        camera.near = span * .01;
        camera.far = span * 5;
        camera.updateProjectionMatrix();
        renderer.render(scene, camera);
        const textured = await imageBlob(renderer.domElement);
        signal.throwIfAborted();
        model.traverse(object => {
          if (!object.isMesh) return;
          const sourceMaterials = [].concat(object.material || []);
          for (const material of sourceMaterials) originals.add(material);
          object.material = !object.geometry.getAttribute('normal') || sourceMaterials.some(material => material.flatShading)
            ? clayFlat : clay;
        });
        renderer.render(scene, camera);
        const neutral = await imageBlob(renderer.domElement);
        signal.throwIfAborted();
        return {textured, neutral};
      } finally {
        model.removeFromParent();
        disposeModels(gltf.scenes, originals);
      }
    },
    dispose() {
      clay.dispose();
      clayFlat.dispose();
      environment.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}

export function createCollectionPreviews(grid) {
  const entries = new Map();
  const cache = new Map();
  const failed = new Set();
  let capture = null;
  let active = null;
  let eagerMode = false;
  let scheduled = false;
  let disposed = false;
  let webglUnavailable = false;

  function eligible(entry) {
    return entry.visible && grid.contains(entry.media) &&
      (entry.hovered || entry.focused || (entry.eager ?? eagerMode));
  }

  function paintWipe(entry) {
    const {media, layer, hovered, focused, inputKind} = entry;
    if (!layer) return;
    const keyboard = focused && (!hovered || inputKind === 'keyboard');
    const wipe = keyboard ? entry.keyboardWipe : hovered ? entry.pointerWipe : 0;
    media.style.setProperty('--collection-preview-wipe', `${wipe}%`);
    media.classList.toggle('collection-preview-wiping', wipe > 0 && wipe < 100);
  }

  async function show(entry, snapshots) {
    entry.decoding = true;
    const layer = document.createElement('span');
    layer.className = 'collection-preview-render';
    layer.setAttribute('aria-hidden', 'true');
    const textured = new Image();
    const neutral = new Image();
    textured.alt = '';
    neutral.alt = '';
    textured.className = 'collection-preview-textured';
    neutral.className = 'collection-preview-clay';
    const divider = document.createElement('span');
    divider.className = 'collection-preview-divider';
    entry.objectUrls = [URL.createObjectURL(snapshots.textured), URL.createObjectURL(snapshots.neutral)];
    [textured.src, neutral.src] = entry.objectUrls;
    try {
      await Promise.all([textured.decode(), neutral.decode()]);
      if (entries.get(entry.media) !== entry) return;
      layer.append(textured, neutral, divider);
      entry.layer = layer;
      entry.media.append(layer);
      entry.media.dataset.collectionPreview = 'ready';
      entry.button?.setAttribute('aria-keyshortcuts', 'ArrowLeft ArrowRight');
      paintWipe(entry);
    } catch {
      for (const url of entry.objectUrls) URL.revokeObjectURL(url);
      entry.objectUrls = [];
      entry.failed = true;
      if (entries.get(entry.media) === entry) entry.media.dataset.collectionPreview = 'fallback';
    } finally {
      entry.decoding = false;
      entry.media.removeAttribute('aria-busy');
    }
  }

  function schedule() {
    if (scheduled || disposed || active || document.hidden || webglUnavailable) return;
    scheduled = true;
    setTimeout(() => {
      scheduled = false;
      void drain();
    }, 0);
  }

  async function drain() {
    if (disposed || active || document.hidden || webglUnavailable) return;
    const candidates = [...entries.values()].filter(entry =>
      eligible(entry) && !entry.failed && !entry.layer && !entry.decoding && !failed.has(entry.key));
    const entry = candidates.find(candidate => candidate.hovered || candidate.focused) || candidates[0];
    if (!entry) return;
    const saved = cache.get(entry.key);
    if (saved) {
      cache.delete(entry.key);
      cache.set(entry.key, saved);
      void show(entry, saved);
      schedule();
      return;
    }
    const controller = new AbortController();
    active = {entry, controller};
    entry.media.dataset.collectionPreview = 'loading';
    entry.media.setAttribute('aria-busy', 'true');
    try {
      const persisted = await browserSnapshots(entry);
      controller.signal.throwIfAborted();
      if (persisted) {
        cache.set(entry.key, persisted);
        if (cache.size > cacheLimit) cache.delete(cache.keys().next().value);
        void show(entry, persisted);
        return;
      }
      if (!capture) {
        try {
          capture = createCapture();
        } catch {
          webglUnavailable = true;
          return;
        }
      }
      const response = await fetch(entry.url, {signal: controller.signal, credentials: 'same-origin'});
      if (!response.ok) throw new Error('Preview model unavailable.');
      const snapshots = await capture.render(await response.arrayBuffer(), controller.signal);
      cache.set(entry.key, snapshots);
      if (cache.size > cacheLimit) cache.delete(cache.keys().next().value);
      if (entries.get(entry.media) === entry) void show(entry, snapshots);
      void browserSnapshots(entry, snapshots);
    } catch {
      if (!controller.signal.aborted) {
        failed.add(entry.key);
        if (failed.size > cacheLimit) failed.delete(failed.values().next().value);
        entry.media.dataset.collectionPreview = 'fallback';
      }
    } finally {
      active = null;
      if (!entry.decoding) {
        if (entry.media.dataset.collectionPreview === 'loading') delete entry.media.dataset.collectionPreview;
        entry.media.removeAttribute('aria-busy');
      }
      if (disposed) capture?.dispose();
      schedule();
    }
  }

  function update() {
    if (active && (document.hidden || !eligible(active.entry))) active.controller.abort();
    schedule();
  }

  const observer = new IntersectionObserver(records => {
    for (const record of records) {
      const entry = entries.get(record.target);
      if (entry) entry.visible = record.isIntersecting;
    }
    update();
  });
  document.addEventListener('visibilitychange', update);

  function clear() {
    observer.disconnect();
    active?.controller.abort();
    for (const entry of entries.values()) {
      entry.listeners.abort();
      if (entry.layer) entry.button?.removeAttribute('aria-keyshortcuts');
      entry.layer?.remove();
      for (const url of entry.objectUrls) URL.revokeObjectURL(url);
      delete entry.media.dataset.collectionPreview;
      entry.media.removeAttribute('aria-busy');
      entry.media.style.removeProperty('--collection-preview-wipe');
      entry.media.classList.remove('collection-preview-wiping');
    }
    entries.clear();
  }

  return {
    clear,
    setEager(enabled) {
      eagerMode = enabled;
      update();
    },
    watch(media, {url, revision, eager}) {
      if (disposed || entries.has(media) || typeof url !== 'string' || !url) return;
      const address = new URL(url, location.href);
      if (address.origin !== location.origin) return;
      const button = media.closest('button.card-open');
      const entry = {
        media, button, url: address.href, key: `${address.href}|${revision ?? ''}`, eager, revision,
        listeners: new AbortController(), visible: false, hovered: false, focused: false,
        pointerWipe: 0, keyboardWipe: 50, objectUrls: [],
      };
      entries.set(media, entry);
      const options = {signal: entry.listeners.signal};
      const move = event => {
        if (event.pointerType !== 'mouse') return;
        const rect = media.getBoundingClientRect();
        entry.hovered = true;
        entry.inputKind = 'pointer';
        entry.pointerWipe = rect.width ? Math.max(0, Math.min(100, 100 * (event.clientX - rect.left) / rect.width)) : 0;
        paintWipe(entry);
      };
      media.addEventListener('pointerenter', event => {
        move(event);
        update();
      }, options);
      media.addEventListener('pointermove', move, options);
      media.addEventListener('pointerleave', () => {
        entry.hovered = false;
        entry.pointerWipe = 0;
        paintWipe(entry);
        update();
      }, options);
      button?.addEventListener('focus', () => {
        if (!button.matches(':focus-visible')) return;
        entry.focused = true;
        entry.inputKind = 'keyboard';
        entry.keyboardWipe = 50;
        paintWipe(entry);
        update();
      }, options);
      button?.addEventListener('keydown', event => {
        if (!entry.focused || !entry.layer || event.target !== button || button.closest('.turntable-playing')
            || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
        event.preventDefault();
        entry.inputKind = 'keyboard';
        entry.keyboardWipe = Math.max(0, Math.min(100, entry.keyboardWipe + (event.key === 'ArrowLeft' ? -10 : 10)));
        paintWipe(entry);
      }, options);
      button?.addEventListener('blur', () => {
        entry.focused = false;
        paintWipe(entry);
        update();
      }, options);
      observer.observe(media);
      const snapshots = cache.get(entry.key);
      if (snapshots) void show(entry, snapshots);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      document.removeEventListener('visibilitychange', update);
      clear();
      cache.clear();
      failed.clear();
      if (!active) capture?.dispose();
    },
  };
}
