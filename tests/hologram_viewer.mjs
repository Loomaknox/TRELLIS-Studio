import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createHologramMaterial,hologramConstruction} from '../web/hologram-viewer.js';

assert.equal(hologramConstruction(0).progress, 0);
assert.equal(hologramConstruction(3.25).progress, 0.5);
assert.equal(hologramConstruction(7).constructing, false);
assert.equal(hologramConstruction(700).progress, 1);
assert.equal(hologramConstruction(0,true).progress, 1);
assert.equal(hologramConstruction(3,true).constructing, false);

// Changing the preview must not change the source assets or own their textures.
const texture = new THREE.Texture();
texture.colorSpace = THREE.SRGBColorSpace;
const source = new THREE.MeshStandardMaterial({map:texture, color:'#8a734a', roughness:0.4,
  metalness:0.3, side:THREE.DoubleSide, normalMap:new THREE.Texture(), alphaTest:0.2});
source.normalScale.set(0.7, 0.9);
const before = JSON.stringify(source.toJSON());
let textureDisposals = 0;
texture.addEventListener('dispose', () => textureDisposals++);
const uniforms = {hologramTime:{value:0}, hologramHeight:{value:1}, hologramBottom:{value:0},
  hologramColour:{value:new THREE.Color('#50f4ce')},hologramReveal:{value:1.04},hologramConstructing:{value:0}};
const preview = createHologramMaterial(source, uniforms);
assert.notEqual(preview, source);
assert.equal(preview.map, texture);
assert.equal(preview.normalMap, source.normalMap);
assert.deepEqual(preview.normalScale.toArray(), [0.7, 0.9]);
assert.equal(preview.side, THREE.DoubleSide);
assert.equal(preview.alphaTest, 0.2);
preview.color.set('#ffffff');
preview.wireframe = true;
preview.dispose();
assert.equal(JSON.stringify(source.toJSON()), before);
assert.equal(textureDisposals, 0);
assert.equal(texture.colorSpace, THREE.SRGBColorSpace);

// Inject into the real Three shader, retaining morphing, skinning and tone mapping.
const shader = {uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,
  fragmentShader:THREE.ShaderLib.standard.fragmentShader};
preview.onBeforeCompile(shader);
assert.equal(shader.uniforms.hologramTime, uniforms.hologramTime);
assert.ok(shader.vertexShader.indexOf('#include <skinning_vertex>') < shader.vertexShader.indexOf('vHologramPosition ='));
assert.ok(shader.vertexShader.includes('#include <morphtarget_vertex>'));
assert.ok(shader.fragmentShader.includes('#include <tonemapping_fragment>'));
assert.ok(shader.fragmentShader.includes('#include <colorspace_fragment>'));
console.log('Hologram preview: source preservation, texture ownership and deformation chunks passed.');
