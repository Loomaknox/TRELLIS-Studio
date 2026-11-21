import {createCapture} from './collection-preview-capture.js';

async function post(name, body) {
  const reply = await fetch(`result/${name}`, {method: 'POST', body});
  if (!reply.ok) throw new Error('The renderer could not return its result.');
}

let capture;
try {
  const signal = AbortSignal.timeout(45000);
  const model = await fetch('model.glb', {signal});
  if (!model.ok) throw new Error('The GLB could not be read.');
  capture = createCapture();
  const {textured, neutral} = await capture.render(await model.arrayBuffer(), signal);
  await post('textured', textured);
  await post('clay', neutral);
} catch (error) {
  await post('error', String(error.message || error).slice(0, 1000));
} finally {
  capture?.dispose();
}
