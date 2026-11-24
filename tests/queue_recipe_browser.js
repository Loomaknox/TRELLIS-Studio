import {createQueueStudio} from '../web/queue-studio.js';
import {createExportPreflight} from '../web/export-preflight.js';

const profile = {id:'test', name:'Test', settings:{preset:'game_d', remove_bg:true, triangles:28000,
  texture_size:2048,resolution:1024,advanced:{shape_steps:16}}};
const runtime = {edition:'desktop',texture_sizes:[1024,2048,4096],supported_resolutions:[512,1024],
  facial_head_enhancement:{ready:true},generation_methods:{pixal3d_single:{ready:true}},pixal3d:{face_projection:{ready:true}}};
let submitted;
async function api(path, options) {
  if (path === '/api/status') return runtime;
  if (path === '/api/generation-options') return {triangle_min:1000,triangle_max:8000000};
  if (path === '/api/profiles') return {profiles:[profile],startup_profile:'test'};
  if (path === '/api/queue') return {items:[]};
  if (path === '/api/queue/batch') { submitted = JSON.parse(options.body.get('specifications')); return {}; }
  if (path === '/api/exports/preflight') return {models:[{id:'A',name:'Modèle',human_review:'retained',checks:[
    {label:'Skeleton and motion',detail:'1 joints · 2 clips',detail_key:'{bones} joints · {clips} clips',
      detail_values:{bones:1,clips:2},status:'attention'}]}]};
  throw Error(path);
}
const $ = s => document.querySelector(s);
const assert = (ok, text) => { if (!ok) throw Error(text); };
function change(control,value) {
  control.value = value;
  control.dispatchEvent(new Event('change',{bubbles:true}));
}
async function openSettings(index) {
  document.querySelectorAll('.queue-draft .queue-row-actions button:first-child')[index].click();
  for (let i=0; i<20 && !$('#queueRecipeDialog').open; ++i) await new Promise(resolve=>setTimeout(resolve,25));
  assert($('#queueRecipeDialog').open,'Recipe failed to open');
}
export async function run() {
  document.documentElement.style.zoom='200%';
  assert(devicePixelRatio===2 && getComputedStyle(document.documentElement).zoom==='2','200% zoom required');
  const queue = createQueueStudio({api,refresh:async()=>{}});
  queue.setRuntime(runtime);
  await queue.open(true);
  const dt = new DataTransfer();
  for (const name of ['pixal.png','face.png']) dt.items.add(new File(['x'],name,{type:'image/png'}));
  const picker = $('#queueDialog input[type=file]');
  picker.files = dt.files;
  picker.dispatchEvent(new Event('change'));
  await openSettings(0);
  change($('#queueImageEngine'),'pixal3d_single');
  assert($('#queueFacialHead').disabled,'Pixal must disable TOPOS');
  assert(!$('#queueReprojectFace').disabled,'Verified Pixal face detector must enable reprojection');
  $('#queueReprojectFace').click();
  $('#queueRecipeDialog footer button').click();
  await new Promise(resolve=>setTimeout(resolve,50));
  assert(document.activeElement===document.querySelector('.queue-row-actions button:first-child'),'Restore focus on the edited queue row');
  await openSettings(1);
  assert($('#queueFacialHead').disabled,'Object cannot request TOPOS');
  change($('#queueAssetType'),'humanoid');
  assert(!$('#queueFacialHead').disabled,'Humanoid 1024 native PBR can request TOPOS');
  $('#queueFacialHead').click();
  $('#queueRecipeDialog footer button').click();
  assert($('#queueDialog').textContent.includes('TOPOS'),'Batch summary must show the face choice');
  await $('#queueDialog footer button.primary').onclick();
  assert(submitted?.length===2,'Batch did not submit both images');
  assert(submitted[0].engine==='pixal3d_single' && submitted[0].reproject_face && submitted[0].resolution===1024 && !Object.keys(submitted[0].advanced_settings).length,'Invalid Pixal recipe');
  assert(submitted[1].engine==='trellis2' && submitted[1].asset_type==='humanoid' && submitted[1].facial_head_enhancement,'Invalid face recipe');
  $('#queueDialog').close();
  const panel = createExportPreflight({api,onAction(){},onChange(){}});
  document.body.append(panel.root);
  panel.setSelection([{id:'A',settings:{}}],'unity',true);
  await panel.run();
  const french=new URLSearchParams(location.search).get('lang')==='fr';
  const expected=french?['À vérifier · 1','Contrôle visuel','Articulations (1) · clips (2)']:['1 to inspect','1 joints · 2 clips'];
  for (const text of expected) assert(panel.root.textContent.includes(text),text);
}
