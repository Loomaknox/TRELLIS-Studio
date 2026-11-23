import assert from 'node:assert/strict';
import test from 'node:test';
import {addBoneChain, hasTentacleRig, isCreatureRigDraft, moveBonePoint} from '../web/creature-rig-editor.js';

function armature() {
  return [
    {name: 'root', parent: null, head: [0, 0, 0], tail: [0, 1, 0]},
    {name: 'body', parent: 'root', head: [0, 1, 0], tail: [0, 2, 0]},
    {name: 'tail', parent: 'body', head: [0, 2, 0], tail: [0, 2, 1]},
    {name: 'detached', parent: 'body', head: [1, 1, 0], tail: [1, 2, 0]},
  ];
}

test('moving a coincident joint moves attached segments but leaves offset branches in place', () => {
  const bones = armature();
  moveBonePoint(bones, bones[1], 'tail', [0, 2.5, 0], true);
  assert.deepEqual(bones[2].head, [0, 2.5, 0]);
  assert.deepEqual(bones[3].head, [1, 1, 0]);
  moveBonePoint(bones, bones[2], 'head', [0, 2, 0], false);
  assert.deepEqual(bones[1].tail, [0, 2.5, 0]);
});

test('subdivision retains the first name and attaches adjoining children to the last segment', () => {
  const bones = armature();
  const first = addBoneChain(bones, bones[1], 3, true);
  assert.equal(bones.length, 6);
  assert.equal(bones[4].name, first);
  assert.equal(bones[1].name, 'body');
  assert.deepEqual(bones[5].tail, [0, 2, 0]);
  assert.equal(bones[2].parent, bones[5].name);
  assert.equal(bones[3].parent, 'body');
});

test('adding a branch makes a continuous chain regardless of existing bone names', () => {
  const bones = armature();
  bones[3].name = 'branch_1';
  const first = addBoneChain(bones, bones[2], 3);
  assert.equal(first, 'branch_2');
  assert.equal(bones[4].parent, 'tail');
  assert.deepEqual(bones[4].head, bones[2].tail);
  assert.equal(bones[6].parent, bones[5].name);
  assert.deepEqual(bones[6].tail, [0, 2, 2]);
  assert.equal(new Set(bones.map(bone => bone.name)).size, 7);
});

test('a completed skeleton draft waits for final media without affecting humanoid jobs', () => {
  assert.equal(isCreatureRigDraft({state: 'done', settings: {rig_options: {mode: 'creature'}}, media: {available: false}}), true);
  assert.equal(isCreatureRigDraft({state: 'done', settings: {rig_options: {mode: 'creature'}}, media: {available: true}}), false);
  assert.equal(isCreatureRigDraft({state: 'done', settings: {}, media: {available: false}}), false);
});

test('swim controls need an adapted bell and at least two attached tentacle chains', () => {
  const bones = [
    {name: 'racine', parent: null},
    {name: 'ombrelle_01', parent: 'racine'},
    {name: 'tentacule_01_01', parent: 'ombrelle_01'},
    {name: 'ombrelle_02', parent: 'racine'},
    {name: 'tentacule_02_01', parent: 'ombrelle_02'},
  ];
  assert.equal(hasTentacleRig(armature()), false);
  assert.equal(hasTentacleRig(bones.slice(0, -1)), false);
  assert.equal(hasTentacleRig(bones), true);
  bones[4].parent = 'ombrelle_01';
  assert.equal(hasTentacleRig(bones), false);
});
