import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {createObstaclePreview, motionObstacles, obstacleFraming, playPreviewAction} from '../web/motion-obstacle.js';

test('the library preview plays the actual vault and places the palm on its crate', async () => {
  const library = JSON.parse(await readFile(new URL('../animations/library.json', import.meta.url)));
  const recipe = library.find(clip => clip.id === 'side_vault');
  const asset = await readFile(new URL('..' + recipe.preview_url, import.meta.url));
  const gltf = await new GLTFLoader().parseAsync(asset.buffer.slice(asset.byteOffset, asset.byteOffset + asset.byteLength), '');
  const clip = gltf.animations.find(clip => clip.name === recipe.preview_clip);
  assert.equal(clip.duration, recipe.source_duration);
  const [box] = motionObstacles(gltf);
  assert.ok(box.travel[2] > box.size[2]);
  const contact = gltf.parser.json.animations[0].extras.trellis_contact;
  const palm = gltf.scene.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(contact.bone));
  const mixer = new THREE.AnimationMixer(gltf.scene);
  const action = mixer.clipAction(clip);
  playPreviewAction(action,true);
  const target = new THREE.Vector3(...contact.palm_target);
  assert.ok(Math.abs(target.y - box.center[1] - box.size[1]/2) < .002);
  const [start,end] = contact.interval_s;
  for (let t = start; t <= end; t += 1/120) {
    mixer.setTime(t);
    const point = palm.localToWorld(new THREE.Vector3(...contact.palm_offset));
    assert.ok(point.distanceTo(target) < .025, `palm missed the crate at ${t.toFixed(3)} s`);
  }
  // A file born facing +X, then rotated, scaled and translated by the viewer.
  const aroundY = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),Math.PI/2);
  const rotate = v => new THREE.Vector3(...v).applyQuaternion(aroundY).toArray();
  const oriented = new THREE.Group(), scene = new THREE.Scene();
  gltf.scene.quaternion.copy(aroundY);
  oriented.add(gltf.scene);
  scene.add(oriented);
  oriented.rotation.y=-.37;
  oriented.position.set(2,-.2,1);
  oriented.scale.setScalar(.7);
  const marker = createObstaclePreview(scene);
  marker.set(oriented,{...box,center:rotate(box.center),travel:rotate(box.travel)});
  const crateMesh = scene.getObjectByName('Motion obstacle preview').children[0];
  for (let t = start; t <= end; t += 1/120) {
    mixer.setTime(t);
    const point = crateMesh.worldToLocal(palm.localToWorld(new THREE.Vector3(...contact.palm_offset)));
    assert.ok(Math.abs(point.x) < box.size[0]/2 && Math.abs(point.z) < box.size[2]/2);
    assert.ok(Math.abs(point.y-box.size[1]/2) < .025);
  }
  const heading = oriented.localToWorld(new THREE.Vector3(...rotate(box.travel))).sub(oriented.position).normalize();
  assert.ok(heading.distanceTo(marker.heading)<1e-6);
  // Landing holds until Play is pressed. A normal looping clip keeps its own playback policy.
  mixer.update(clip.duration+1);
  assert.equal(action.time,clip.duration);
  assert.equal(action.paused,true);
  playPreviewAction(action,true);
  assert.equal(action.time,0);
  mixer.update(.1);
  assert.ok(Math.abs(action.time-.1)<1e-6);
  const next=mixer.clipAction(new THREE.AnimationClip('walk',1,[]));
  playPreviewAction(next,false);
  assert.equal(next.loop,THREE.LoopRepeat);
});

test('crate follows model placement, contributes to framing and clears when switching clips', () => {
  const scene = new THREE.Scene(), model = new THREE.Group();
  scene.add(model);
  const preview = createObstaclePreview(scene);
  const box = {type:'box', center:[0,.5,2],size:[1,1,.4],travel:[0,0,4]};
  const gltf = {animations:[{name:'run'},{name:'vault'}]};
  assert.deepEqual(motionObstacles(gltf,{animation_set:[{clip:'vault',obstacle:box}]}),[null,box]);
  assert.deepEqual(motionObstacles(gltf),[null,null]);
  const invalid = { ...box, size:[1,0,1] };
  assert.deepEqual(motionObstacles(gltf,{animation_set:[{clip:'vault',obstacle:invalid}]}),[null,null]);
  preview.set(model,box);
  model.rotation.y=Math.PI/2;
  model.position.x=2;
  model.scale.setScalar(.5);
  preview.sync();
  const bounds=new THREE.Box3();
  preview.expandBounds(bounds);
  assert.ok(bounds.containsPoint(new THREE.Vector3(4, .25, 0)));
  assert.ok(bounds.containsPoint(new THREE.Vector3(2, .25, 0)));
  assert.equal(model.children.length,0);
  assert.equal(scene.children.length,2);
  for (const aspect of [.75,1.8]) {
    const camera = new THREE.PerspectiveCamera(40,aspect,.01,100);
    const frame = obstacleFraming(bounds,camera);
    camera.position.copy(frame.eye);
    camera.lookAt(frame.center);
    camera.updateMatrixWorld();
    for (const x of [bounds.min.x,bounds.max.x]) for (const y of [bounds.min.y,bounds.max.y]) {
      for (const z of [bounds.min.z,bounds.max.z]) {
        const point=new THREE.Vector3(x,y,z).project(camera);
        assert.ok(Math.abs(point.x)<1 && Math.abs(point.y)<1);
      }
    }
  }
  preview.set(model,null);
  assert.equal(preview.active,false);
  assert.equal(scene.children.length,1);
});
