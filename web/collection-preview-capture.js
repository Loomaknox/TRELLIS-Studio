import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';

const width = 384;
const height = 310;
const textureLimit = 1024;

function imageBlob(canvas) {
  const pixels = document.createElement('canvas');
  pixels.width = canvas.width;
  pixels.height = canvas.height;
  const context = pixels.getContext('2d', {willReadFrequently: true});
  if (!context) throw new Error('Preview capture failed.');
  context.drawImage(canvas, 0, 0);
  const rgba = context.getImageData(0, 0, pixels.width, pixels.height).data;
  if (!rgba.some((value, i) => i % 4 === 3 && value > 0)) {
    throw new Error('The rendered preview is empty.');
  }
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => blob?.type === 'image/webp'
      ? resolve(blob) : reject(new Error('WebP preview capture failed.')), 'image/webp', .9);
  });
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

export function createCapture() {
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

  const manager = new THREE.LoadingManager();
  manager.setURLModifier(url => {
    if (!url.startsWith('blob:') && !url.startsWith('data:')) throw new Error('Preview assets must be embedded in the GLB.');
    return url;
  });
  const loader = new GLTFLoader(manager);

  return {
    async render(bytes, signal) {
      const gltf = await loader.parseAsync(bytes, '');
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
