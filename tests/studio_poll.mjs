import assert from 'node:assert/strict';
import test from 'node:test';
import {visiblePoll, collectionDue, mergeCollection} from '../web/studio-poll.js';
import {batchSpecification, faceRestriction, pixalRestriction} from '../web/single-image-recipe.js';

test('polling sleeps while hidden and resumes exactly once', async () => {
  const page = new EventTarget();
  let callback, delay, calls = 0;
  const timers = {setTimeout(fn, ms) { callback = fn; delay = ms; return 1; }, clearTimeout() { callback = undefined; }};
  const poll = visiblePoll(async () => { ++calls; }, () => 12000, page, timers);
  poll.start();
  assert.equal(delay, 12000);
  await callback();
  assert.equal(calls, 1);
  page.hidden = true;
  page.dispatchEvent(new Event('visibilitychange'));
  assert.equal(callback, undefined);
  page.hidden = false;
  page.dispatchEvent(new Event('visibilitychange'));
  assert.equal(delay, 0);
  await callback();
  poll.stop();
  assert.equal(calls, 2);
  assert.equal(callback, undefined);
});

test('collection observes final frame, workspace changes, explicit refresh and periodic repair', () => {
  const idle = {age: 5000, revision: 'v1', previous: 'v1'};
  assert.equal(collectionDue(idle), false);
  for (const change of [{active: 'A'}, {wasActive: 'B'}, {pending: 'C'}, {age: 60000}, {revision:'v2'}, {force:true}])
    assert.equal(collectionDue({...idle, ...change}), true);
  const delta = {full:false, order:['C','B','A','D'], changes:[{id:'C'},{id:'A', new:true}], unavailable:['D']};
  assert.deepEqual(mergeCollection([{id:'A'}, {id:'B'}, {id:'D'}, {id:'deleted'}], delta), [{id:'C'},{id:'B'},{id:'A', new:true}]);
});

test('batch recipes separate Pixal sampling, compatible TOPOS and fixed workflows', () => {
  const pixal = {engine:'pixal3d_single', profile_id:'game_d', resolution:1024, advanced_settings:{steps:10}, name:'A'};
  assert.deepEqual(batchSpecification(pixal, false).advanced_settings, {});
  assert.deepEqual(pixal.advanced_settings, {steps:10});
  const workflow = batchSpecification({...pixal, height_m:1, priority:0}, true);
  assert.equal(workflow.engine, undefined);
  assert.equal(workflow.name, 'A');
  assert.ok(pixalRestriction({}, 'game_d'));
  assert.ok(pixalRestriction({pixal3d:{single_image:{ready:true}}}, 'figure_master'));
  const recipe = {engine:'trellis2', type:'humanoid', resolution:1024, texture:'trellis', finishing:'none'};
  assert.equal(faceRestriction({ready:true}, recipe), '');
  for (const overrides of [{type:'object'}, {engine:'pixal3d_single'}, {texture:'multiview'}, {resolution:512}, {finishing:'hi3d_1024'}])
    assert.ok(faceRestriction({ready:true}, {...recipe,...overrides}));
});
