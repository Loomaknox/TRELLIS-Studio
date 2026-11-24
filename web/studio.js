import {collectionDue, mergeCollection, visiblePoll} from './studio-poll.js';
import {apiErrorMessage,formatLocale,t} from './i18n.js';
import {createObstaclePreview, motionObstacles, obstacleFraming, playPreviewAction} from './motion-obstacle.js';
import {runtimeSummary} from './workbench-ui.js?v=stability';
import './language-selector.js';
import {createStudioWorkbench} from './studio-workbench.js?v=detail-refinement-native';
import {createViewerLighting,createViewerStage} from './viewer-lighting.js?v=visual-refresh-2';
import {createHologramViewer} from './hologram-viewer.js?v=visual-refresh-2';
import {createGenerationWait} from './generation-wait.js?v=studio-visual-refinement';
import {createStudioTools} from './studio-tools.js?v=option-help';
import {createAssetDetails,assetTypeName} from './asset-details.js?v=detail-study';
import {createPrintCopy} from './print-copy.js?v=3.4.0';
import {createAnimationStudio} from './animation-studio.js?v=3.15.1-rigs';
import {createRigSetupViewer} from './rig-setup-viewer.js?v=rig-expressive';
import {isCreatureRig,isCreatureRigDraft} from './creature-rig-editor.js?v=3.15.1-rigs';
import {createCreatureRigViewer} from './creature-rig-viewer.js?v=3.15.1-rigs';
import {createModelImport} from './import-model.js?v=3.4.0';
import {createMultiviewInputs} from './multiview-inputs.js?v=comfyui-profiles';
import {createReferencePreview} from './reference-preview.js?v=studio-visual-refinement';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { createAdvancedControls } from './advanced-controls.js?v=standard-profiles';
import { createProfileControls } from './profiles.js?v=profile-catalogue';
import { textureMethodAvailability, textureMethodChoices } from './texture-methods.js?v=figure-master-ultratex';
import {createCardMenu,updateCardStatus,icon} from './card-menu.js?v=texture-variant';
import {createCardTurntables} from './card-turntable.js?v=figure-master-ultratex';
import {createCollectionPreviews} from './collection-previews.js?v=collection-images';
const $=id=>document.getElementById(id);
const cardTurntables=createCardTurntables($('libraryGrid'));
const collectionPreviews=createCollectionPreviews();
let cardTurntablesAvailable=false;
const cardMenu=createCardMenu({version:reuseJob,remove:requestDelete,details:openDetails,print:j=>printCopy.open(j),compare:j=>studioTools.compare.open(j),diagnostics:j=>studioTools.diagnostics.open(j),export:j=>studioTools.exports.open(j),history:j=>workbench.history.open(j),folder:j=>workbench.workspace.move(j),lod:j=>workbench.prepare.open(j,'lod'),game:j=>workbench.prepare.open(j,'game'),refinish:openRefinish,finishingBoard:j=>workbench.finishingBoard.open(j)});
const labels={done:t('Completed'),running:t('Generating'),error:t('Failed'),cancelled:t('Cancelled'),queued:t('Queued')},reviews={review:t('To review'),retouch:t('Needs changes'),retained:t('Retained'),rejected:t('Rejected')};
let studioTools,viewerLighting,viewerStage,hologramViewer,workbench,rigSetupViewer,creatureRigViewer;
let selectedId=null,loadedId=null,loadingId=null,activeId=null,records=[],busy=false,ready=false,shutDown=false,features=false;
let page=0,trashMode=false,trashRecords=[],metadataId=null,inspectId=null,inspectVersion=0,textureOpen=false;
let submittingGeneration=false,restoringReferences=false;
let boneDots=null;const boneDotMatrix=new THREE.Matrix4(),boneDotPosition=new THREE.Vector3();
let loadedRevision=null;
let missingRigPreview=null,stoppedSkeletonChecked=null,rigSkeletonRequest=null;
let predictedSkeleton=null,predictedId=null;
let obstaclePreview, clipObstacles=[];
let animationStudio,animationMode=false,pendingSelection=null,mixer=null,clips=[],clipAction=null,clipPlaying=true,skeletonHelper=null;
const clock=new THREE.Clock();
let renderer,scene,camera,controls,model,grid,profileControls,rotating=false,wire=false,loadVersion=0;
const categoryName=value=>({Mobilier:'Furniture',Industriel:'Industrial','Mobilier urbain':'Street furniture',Autre:'Other'}[value]||value);
const viewport=$('viewport'),nameOf=j=>j.metadata?.display_name||j.settings?.name||'Untitled',jobOf=()=>records.find(j=>j.id===selectedId);
const generationWait=createGenerationWait(viewport,{getMode:()=>$('materialMode').value,setMode:mode=>{$('materialMode').value=mode;document.querySelectorAll('[data-material]').forEach(button=>button.setAttribute('aria-pressed',button.dataset.material===mode));materials();}});
const formatTriangles=count=>Number.isSafeInteger(count)&&count>0?t('{count} triangles',{count:count.toLocaleString(formatLocale)}):t('Count unavailable');
const detailControls=await createAssetDetails();
const printCopy=createPrintCopy({api,startJob:startStudioJob});
studioTools=createStudioTools({api,getRecords:()=>records,getJob:jobOf,refresh:async()=>{metadataId=null;await refresh();},printCopy,labelAnimation:name=>animationStudio?.label(name)||name,openPreparation:(job,action)=>workbench.prepare.open(job,action)});
const advancedControls=await createAdvancedControls($('advancedControls'));
const multiview=createMultiviewInputs({
  changed({role,file,mode,swap}){
    if(role||mode)referencePreview.discard(role);
    if(swap)referencePreview.swapSides();
    if(role==='front'){
      $('facialPortrait').value='';
      $('parentId').value='';
      if(file&&$('name').value==='New model')$('name').value=file.name.replace(/\.[^.]+$/,'').slice(0,80);
    }
    $('notice').textContent='';
    if(mode)profileControls?.sync();
    updateButtons();
  },
  invalid:message=>errorAt('notice',message),
});
const referencePreview=createReferencePreview({api,multiview,removeBackground:$('removeBg')});
$('removeBg').addEventListener('change',()=>{referencePreview.discard();updateButtons();});
function applyDefaultGeneration(){const d=advancedControls.defaults;if(!d)return;for(const[id,value]of Object.entries({preset:d.preset,resolution:d.resolution,triangles:d.triangles,textureSize:d.texture_size}))$(id).value=String(value);}
applyDefaultGeneration();
const settingsDownload=document.createElement('a');settingsDownload.className='download-settings';settingsDownload.textContent=t('Download settings JSON ↓');settingsDownload.download='trellis-reglages.json';settingsDownload.hidden=true;$('assetDetails').after(settingsDownload);
$('resetAdvanced').disabled=!advancedControls.ready;
$('resetAdvanced').onclick=()=>{
  const workflow=profileControls?.workflow;
  profileControls?.reset();
  explainCost();
  $('notice').textContent=workflow?t('Workflow defaults restored.'):t('Profile settings restored.');
};
const resolutionOf=j=>Number(j.result?.resolution||j.settings?.resolution||512);
let availableResolutions=[512],availableTextures=[1024,2048];
function syncVersionNotice(status) {
  const uiRevision = document.querySelector('meta[name="trellis-ui-revision"]')?.content;
  const outdated = uiRevision && status.ui_revision && status.ui_revision !== uiRevision;
  const olderServer = outdated && String(status.ui_revision).localeCompare(uiRevision, 'en', {numeric:true}) < 0;
  const message = !features || olderServer
    ? t('Restart TRELLIS Studio to enable the updated server features.')
    : t('The Studio interface has been updated.');
  const text = $('versionNoticeText');
  if (text.textContent !== message) text.textContent = message;
  $('reloadStudio').hidden = !features || !outdated || olderServer;
  $('versionNotice').hidden = features && !outdated;
}
function syncCapabilities(status){
  multiview.setCapabilities(status);
  workbench?.setCapabilities(status);
  animationStudio?.setCapabilities(status);
  availableResolutions=status.supported_resolutions||[512];
  availableTextures=status.texture_sizes||[1024,2048];
  for(const option of $('resolution').options)option.disabled=!availableResolutions.includes(Number(option.value));
  profileControls?.setFinishingCapabilities(status.features?.includes('repair_surface')===true,
    status.features?.includes('hd_reconstruction')===true,status.create_master_finishing,status.detail_texturing,
    textureMethodAvailability(status),status.edition==='desktop'?status.facial_head_enhancement:null);
  explainCost();
}
function explainCost(){const hint=$('qualityHint');if(!hint)return;const notes=[];if(Number($('resolution').value)===1536)notes.push(t('1536³ requires more processing time and memory.'));if(Number($('textureSize').value)===4096)notes.push(t('4K uses larger textures; reserve it for close-up objects and large surfaces.'));hint.textContent=notes.join(' ');hint.hidden=!!profileControls?.workflow||!notes.length;}
$('resolution').addEventListener('change',explainCost);$('textureSize').addEventListener('change',explainCost);
profileControls=await createProfileControls(advancedControls,{
  changed:()=>{explainCost();updateButtons();},
  usePixal:()=>multiview.usesPixal,
  isMultiview:()=>multiview.active,
  describeMethod:()=>multiview.methodLabel,
  useNativeMethod:()=>multiview.applyMethod('trellis2'),
  setWorkflow:multiview.setWorkflow,
});

function node(tag,className,value){const el=document.createElement(tag);if(className)el.className=className;if(value!==undefined)el.textContent=value;return el;}
async function api(url,options){const r=await fetch(url,options),v=await r.json();if(!r.ok)throw Error(apiErrorMessage(v.detail,r.headers.get('X-Trellis-Error')));return v;}
function errorAt(id,e){$(id).textContent=t(e?.message||String(e));}
function duration(s){if(!s)return '—';const m=Math.floor(s/60);s=Math.floor(s%60);return m?`${m} min ${String(s).padStart(2,'0')} s`:`${s} s`;}
try{
  renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;viewport.prepend(renderer.domElement);
  scene=new THREE.Scene();camera=new THREE.PerspectiveCamera(40,1,.001,1000);camera.position.set(2,1.6,2.5);controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.target.set(0,.5,0);
  const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();scene.environment=pmrem.fromScene(room,.04).texture;room.dispose();pmrem.dispose();scene.add(new THREE.HemisphereLight(0xffffff,0x48545d,.9));
  grid=new THREE.GridHelper(10,20,0x7d929a,0x596970);grid.material.transparent=true;grid.material.opacity=.22;scene.add(grid);grid.visible=false;
  viewerLighting=createViewerLighting({scene,renderer,getModel:()=>model});
  viewerStage=createViewerStage(scene,viewport);
  obstaclePreview=createObstaclePreview(scene);
  hologramViewer=createHologramViewer(viewport,{camera});
  const stopRotation=()=>{rotating=false;$('rotate').setAttribute('aria-pressed','false');};
  const canvas=renderer.domElement;
  canvas.tabIndex=0;canvas.setAttribute('role','application');canvas.setAttribute('aria-label',t('3D model view'));
  const instructions=document.createElement('span');
  instructions.className='sr-only';instructions.id='viewportKeyboardHelp';
  instructions.textContent=t('Arrow keys rotate the view. Plus and minus zoom. Home fits the character.');
  viewport.append(instructions);canvas.setAttribute('aria-describedby',instructions.id);
  canvas.setAttribute('aria-keyshortcuts','ArrowLeft ArrowRight ArrowUp ArrowDown Home + -');
  const announcement=document.createElement('span');announcement.className='sr-only';announcement.setAttribute('role','status');viewport.append(announcement);
  const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
  const applyMotionPreference=()=>{controls.enableDamping=!motionPreference.matches;if(motionPreference.matches)stopRotation();};
  applyMotionPreference();motionPreference.addEventListener('change',applyMotionPreference);
  canvas.addEventListener('keydown',event=>{
    if(!model||rigSetupViewer?.active||creatureRigViewer?.active||event.altKey||event.ctrlKey||event.metaKey)return;
    const key=event.key;
    if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','Home'].includes(key))return;
    event.preventDefault();stopRotation();
    const sphere=new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
    const step=Math.PI/18;
    if(key==='Home'){fit();}
    else {
      if(key==='ArrowLeft')sphere.theta-=step;
      if(key==='ArrowRight')sphere.theta+=step;
      if(key==='ArrowUp')sphere.phi-=step;
      if(key==='ArrowDown')sphere.phi+=step;
      if(key==='-'||key==='+'||key==='=')sphere.radius*=key==='-'?1.15:1/1.15;
      sphere.phi=THREE.MathUtils.clamp(sphere.phi,controls.minPolarAngle,controls.maxPolarAngle);
      sphere.radius=THREE.MathUtils.clamp(sphere.radius,controls.minDistance,controls.maxDistance);
      sphere.makeSafe();camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(sphere));
      controls.update();setViewPreset();
    }
    const offset=camera.position.clone().sub(controls.target);
    announcement.textContent=t('View angle {angle}°, distance {distance} m',{
      angle:Math.round(THREE.MathUtils.radToDeg(Math.atan2(offset.x,offset.z))),
      distance:offset.length().toLocaleString(formatLocale,{maximumFractionDigits:2})});
  });
  rigSetupViewer=createRigSetupViewer({scene,camera,controls,viewport,getModel:()=>model,onViewChange:setViewPreset,stopRotation});
  creatureRigViewer=createCreatureRigViewer({scene,camera,controls,viewport,stopRotation,showViewport:()=>setView(false),
    getModel:()=>loadedId===selectedId&&previewRevision(loadedRevision)?model:null});
  controls.addEventListener('start',()=>{if(!rigSetupViewer?.active)setViewPreset();});
  new ResizeObserver(()=>{const w=Math.max(1,viewport.clientWidth),h=Math.max(1,viewport.clientHeight);renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}).observe(viewport);
  renderer.setAnimationLoop(()=>{if(document.hidden||textureOpen||document.getElementById('compareDialog')?.open||document.getElementById('textureProjection')?.open||document.body.classList.contains('library-mode'))return;if(rotating&&model)model.rotation.y+=.004;if(mixer&&clipPlaying){mixer.update(Math.min(clock.getDelta(),.1));if(clipAction){$('clipTime').value=clipAction.time;$('clipTimeValue').value=clipAction.time.toFixed(1)+' s';}}else clock.getDelta();if(skeletonHelper&&boneDots){boneDots.visible=skeletonHelper.visible;model?.updateMatrixWorld(true);skeletonHelper.bones.forEach((bone,index)=>{boneDotPosition.setFromMatrixPosition(bone.matrixWorld);boneDotMatrix.makeTranslation(boneDotPosition.x,boneDotPosition.y,boneDotPosition.z);boneDots.setMatrixAt(index,boneDotMatrix);});boneDots.instanceMatrix.needsUpdate=true;}obstaclePreview?.sync();controls.update();rigSetupViewer?.update();creatureRigViewer?.update();hologramViewer?.update(performance.now());renderer.render(scene,camera);});
}catch(e){$('viewerError').hidden=false;errorAt('viewerError',e);}
function disposeModel(root){if(!root)return;const mats=new Set(),textures=new Set();root.traverse(x=>{x.geometry?.dispose();for(const m of [...(Array.isArray(x.material)?x.material:[x.material]),...(x.userData.baseMaterials||[])]){if(!m)continue;mats.add(m);for(const v of Object.values(m))if(v?.isTexture)textures.add(v);}});textures.forEach(x=>x.dispose());mats.forEach(x=>x.dispose());}
const angleButtons = [...viewport.querySelectorAll('[data-angle]')];
function setViewPreset(angle) {
  for (const button of angleButtons) button.setAttribute('aria-pressed', button.dataset.angle === angle);
}
setViewPreset();
const viewerDocks = viewport.querySelector('.viewport-docks');
new ResizeObserver(() => {
  viewport.style.setProperty('--viewer-docks-height', `${viewerDocks.offsetHeight}px`);
}).observe(viewerDocks);

function clearModel(){obstaclePreview?.clear();clipObstacles=[];hologramViewer?.clear();animationStudio?.closeRig();rigSetupViewer?.close();viewerLighting?.clear();viewerStage?.setVisible(false);setViewPreset();if(boneDots){scene.remove(boneDots);boneDots.geometry.dispose();boneDots.material.dispose();boneDots=null;}if(predictedSkeleton){scene.remove(predictedSkeleton);predictedSkeleton.geometry.dispose();predictedSkeleton.material.dispose();predictedSkeleton=null;predictedId=null;}mixer?.stopAllAction();mixer=null;clips=[];clipAction=null;$('animationPlayer').hidden=true;if(skeletonHelper){scene.remove(skeletonHelper);skeletonHelper.geometry.dispose();skeletonHelper.material.dispose();skeletonHelper=null;}if(model){scene.remove(model);disposeModel(model);}model=null;loadedId=null;loadingId=null;}
function fit(angle) {
  if (!model || !camera) return;
  model.updateMatrixWorld(true);
  model.traverse(mesh => {
    if (mesh.isSkinnedMesh) {
      mesh.skeleton.update();
      mesh.computeBoundingBox();
    }
  });
  const bounds = new THREE.Box3().setFromObject(model, true);
  obstaclePreview?.expandBounds(bounds);
  const size = bounds.getSize(new THREE.Vector3());
  const center = bounds.getCenter(new THREE.Vector3());
  const span = Math.max(size.x, size.y, size.z, 0.01);
  const vaultFrame = obstaclePreview?.active && !angle ? obstacleFraming(bounds,camera,obstaclePreview.heading) : null;
  const distance = vaultFrame?.distance ?? span * (angle === 'top' ? 1.8 : 2.2);
  const elevation = Math.max(0.13, 0.40 - size.y / span);
  const views = {front:[0,.05,1],back:[0,.05,-1],left:[-1,.05,0],right:[1,.05,0],top:[0,1,0]};
  if (angle !== 'top' && !vaultFrame) center.y -= 0.17 * size.y;
  camera.up.set(0, angle === 'top' ? 0 : 1, angle === 'top' ? -1 : 0);
  if (vaultFrame) camera.position.copy(vaultFrame.eye);
  else camera.position.copy(center).addScaledVector(new THREE.Vector3(...(views[angle] || [.36,elevation,1])), distance);
  camera.near = Math.max(0.001, distance / 1000);
  camera.far = Math.max(100, distance * 100);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.minDistance = distance * 0.1;
  controls.maxDistance = distance * 8;
  controls.update();
  viewerStage?.fit(bounds);
  viewerLighting?.fit();
  setViewPreset(angle);
}
function materials(){
 const mode=$('materialMode').value;
 hologramViewer?.setModel(model,mode==='hologram');
 viewerStage?.setVisible(!!model);
 const badge=viewport.querySelector('.viewport-badge>span:last-child');
 if(badge)badge.textContent=' / '+({pbr:'PBR',clay:t('CLAY'),normal:t('NORMALS'),hologram:t('HOLOGRAM · PREVIEW')}[mode]||'PBR');
 model?.traverse(mesh=>{
  if(!mesh.isMesh)return;
  const base=mesh.userData.baseMaterials;
  const current=Array.isArray(mesh.material)?mesh.material:[mesh.material];
  for(const material of current)if(!base.includes(material))material.dispose();
  const chosen=mode==='pbr'?base:base.map(source=>{
   const {side}=source;
   if(mode==='hologram')return hologramViewer.material(source);
   if(mode==='clay')return new THREE.MeshStandardMaterial({color:0xa8b4b5,roughness:.7,metalness:0,side});
   return new THREE.MeshNormalMaterial({side});
  });
  chosen.forEach(material=>material.wireframe=wire);
  mesh.material=mesh.userData.wasArray?chosen:chosen[0];
 });
}
function usesRigPreview(job) {
  return isCreatureRigDraft(job) || job?.settings.asset_type === 'rigged' && job.settings.source_kind === 'unirig'
    && job.operation !== 'animation' && job.state !== 'done';
}

function isStoppedRig(job) {
  return usesRigPreview(job) && (job.state === 'error' || job.state === 'cancelled');
}

function previewRevision(revision) {
  return typeof revision === 'string' && revision.startsWith('rig-preview-');
}

function rigJobError(job) {
  const error = typeof job.error === 'string' ? job.error.trim() : '';
  const exitStatus = /^Command [\s\S]* returned non-zero exit status (-?\d+)\.?$/.exec(error)?.[1];
  if (exitStatus) return t('UniRig exited with status {status}. See the job log for details.',{status:exitStatus});
  const message = error ? t(error) : job.state === 'cancelled' ? t('No rig was produced.') : t('See the job log for details.');
  const details = job.error_details;
  const hand = side => t(side === 'left' ? 'Left hand' : 'Right hand');
  if (Array.isArray(details?.joints) && details.joints.length) {
    const joints = details.joints.slice(0,4).map(({side,finger,phalanx,bone}) =>
      t('{hand} · finger chain {finger} · phalanx {phalanx} ({bone})',{hand:hand(side),finger,phalanx,bone}));
    if(details.joints.length>4)joints.push(t('{count} other joints',{count:details.joints.length-4}));
    return [message,...joints].join(' · ');
  }
  return details?.side ? `${hand(details.side)} · ${message}` : message;
}

async function loadModel(job) {
  const {id} = job;
  const preview = usesRigPreview(job);
  const stopped = isStoppedRig(job);
  if (job.operation === 'animation' && job.state !== 'done' && loadedId === id && !previewRevision(loadedRevision)) return;
  const retainedPreview = stopped && loadedId === id && previewRevision(loadedRevision);
  let revision = job.result?.revision || 0;
  if (preview) revision = isCreatureRig(job) ? 'rig-preview-creature' : stopped ? 'rig-preview-stopped' : `rig-preview-${job.progress >= 8}`;
  if (retainedPreview) revision = loadedRevision;
  if (!renderer || (loadedId === id && loadedRevision === revision) || loadingId === id
    || (stopped && missingRigPreview === id)) return;

  const version = ++loadVersion;
  const path = preview ? 'rig-preview-model' : 'files/model.glb';
  loadingId = id;
  try {
    const gltf = await new GLTFLoader().loadAsync(`/api/jobs/${id}/${path}?v=${revision}`);
    if (version !== loadVersion || selectedId !== id || preview !== usesRigPreview(jobOf())) {
      disposeModel(gltf.scene);
      return;
    }
    clearModel();
    model = gltf.scene;
    loadedId = id;
    loadedRevision = revision;
    model.traverse(mesh => {
      if (!mesh.isMesh) return;
      mesh.userData.wasArray = Array.isArray(mesh.material);
      mesh.userData.baseMaterials = mesh.userData.wasArray ? [...mesh.material] : [mesh.material];
    });
    scene.add(model);
    setupClips(gltf);
    materials();
    $('empty').hidden = true;
    $('viewerError').hidden = true;
    fit();
    if (preview) {
      $('stats').textContent = isCreatureRigDraft(jobOf()) ? t('Creature rig draft') : t('Source preview');
      refreshRigPreview();
    }
    if (!preview || isCreatureRigDraft(jobOf())) animationStudio?.modelLoaded();
  } catch (error) {
    if (version !== loadVersion || selectedId !== id) return;
    if (preview && isStoppedRig(jobOf())) {
      missingRigPreview = id;
      return;
    }
    $('viewerError').hidden = false;
    errorAt('viewerError', preview ? t('The rig preview is temporarily unavailable.') : `Unable to load model: ${error.message}`);
  } finally {
    if (loadingId === id) loadingId = null;
  }
}
$('gridToggle').onclick = () => {
  if (!grid) return;
  grid.visible = !grid.visible;
  viewerStage?.setGridVisible(!grid.visible);
  $('gridToggle').setAttribute('aria-pressed', grid.visible);
};
$('fit').onclick=()=>fit();$('rotate').onclick=()=>{if(rigSetupViewer?.active||creatureRigViewer?.active)return;rotating=!rotating;if(rotating)setViewPreset();$('rotate').setAttribute('aria-pressed',rotating);};$('wireframe').onclick=()=>{wire=!wire;$('wireframe').setAttribute('aria-pressed',wire);materials();};$('materialMode').onchange=materials;
angleButtons.forEach(b=>b.onclick=()=>{if(rigSetupViewer?.active){rigSetupViewer.frame(b.dataset.angle);return;}rotating=false;$('rotate').setAttribute('aria-pressed','false');if(model)model.rotation.y=0;fit(b.dataset.angle);});
function downloads(j){
 const done=j?.state==='done'&&!isCreatureRigDraft(j),terrain=j?.settings.asset_type==='terrain_unity';
 for(const[id,file,enabled]of[['downloadBlender','Blender.zip',features],['downloadGlb','model.glb',true],['downloadUnity','Unity.zip',true]]){
  const el=$(id),ok=done&&enabled;
  el.classList.toggle('disabled',!ok);el.setAttribute('aria-disabled',!ok);
  if(ok)el.href=id==='downloadUnity'&&!terrain?'#exportDialog':`/api/jobs/${j.id}/files/${file}`;else el.removeAttribute('href');
 }
 const unityLabel=terrain?t('Download native Unity terrain'):t('Export to Unity');
 $('downloadUnity').title=unityLabel;$('downloadUnity').setAttribute('aria-label',unityLabel);
 const printable=done&&j.settings.asset_type==='print';
 $('downloadStl').hidden=!printable;
 if(printable)$('downloadStl').href=`/api/jobs/${j.id}/files/model.stl`;else $('downloadStl').removeAttribute('href');
 $('downloadHeight').hidden=!(terrain&&done);
 if(terrain)$('downloadHeight').href=`/api/jobs/${j.id}/files/heightmap.png`;
}
$('downloadUnity').onclick=e=>{
 const j=jobOf();
 if(j?.state!=='done'||isCreatureRigDraft(j)){e.preventDefault();return;}
 if(j.settings.asset_type!=='terrain_unity'){
  e.preventDefault();studioTools.exports.open(j,'unity');
 }
};
function fillMetadata(j){if(metadataId===j?.id)return;metadataId=j?.id||null;const m=j?.metadata||{};$('displayName').value=j?nameOf(j):'';detailControls.setValue('category',categoryName(m.category)||'');detailControls.setValue('detailAssetType',m.asset_type||j?.settings.asset_type||'object');$('reviewState').value=m.review_state||'review';$('tags').value=(m.tags||[]).join(', ');$('notes').value=m.notes||'';$('metadataNotice').textContent='';}

function renderRigJobNotice(job) {
  const notice = $('rigJobNotice');
  notice.hidden = !isStoppedRig(job);
  if (notice.hidden) return;

  const stage = job.state === 'cancelled' ? t('Rig cancelled') : t(job.stage || 'Rigging failed');
  const detail = rigJobError(job);
  if ($('rigJobStage').textContent !== stage) $('rigJobStage').textContent = stage;
  if ($('rigJobError').textContent !== detail) $('rigJobError').textContent = detail;

  const sourceId = job.settings.parent_id ?? job.parent_id;
  const source = records.find(record => record.id === sourceId && record.state === 'done');
  const button = $('openRigSource');
  button.hidden = !source;
  button.onclick = source ? () => selectJob(source.id) : null;
  const rigid = $('retryRigidHands');
  const options = job.settings.rig_options;
  rigid.hidden = !source || !job.error_details?.use_rigid_hands || !animationStudio?.canRetryRigidHands(options);
  rigid.disabled = busy;
  rigid.onclick = rigid.hidden ? null : () => {
    selectJob(source.id);
    if(!animationMode)openAnimationStudio();
    animationStudio.retryRigidHands(options);
  };
}

function renderSelected(){const j=jobOf(),draft=isCreatureRigDraft(j),workflow=!!j?.settings.workflow_id,workflowEngine=j?.result?.engine||(j?.settings.engine==='comfyui'?'ComfyUI':'TRELLIS.2 GGUF');generationWait.update(j,{hasModel:!!model&&loadedId===j?.id,referenceUrl:j?`/api/jobs/${j.id}/files/${workflow?'input.png':'prepared.png'}`:''});studioTools?.update(draft?null:j,records,trashMode);workbench?.update(draft?null:j);detailControls.update(j);animationStudio?.update();$('animateModel').disabled=!j||(j.state!=='done'&&j.operation!=='animation'&&!draft);downloads(j);fillMetadata(j);renderRigJobNotice(j);settingsDownload.hidden=!j;if(j)settingsDownload.href=`/api/jobs/${j.id}/files/settings.json`;$('favorite').disabled=!j||!features;$('favorite').textContent=j?.metadata?.favorite?'★':'☆';$('favorite').setAttribute('aria-pressed',!!j?.metadata?.favorite);$('saveMetadata').disabled=!j||!features;$('viewTextures').disabled=!j||j.state!=='done'||!features||draft;
  if(!j){$('modelTitle').textContent=t('Your next model');$('stats').textContent='';$('sourceThumb').hidden=true;$('assetDetails').replaceChildren(node('dt','',t('Model')),node('dd','',t('No model selected')));$('textureSummary').textContent=t('Select a completed model.');$('textureGallery').replaceChildren();if(model||loadingId){++loadVersion;clearModel();}$('empty').hidden=false;return;}
  $('modelTitle').textContent=nameOf(j);const terrain=j.settings.asset_type==='terrain_unity',external=['imported','rigged','print'].includes(j.settings.asset_type),pixal=j.settings.engine==='pixal3d';
  const pixalSingle=pixal&&(j.settings.view_mode==='single'||j.settings.pipeline_type==='pixal3d_1024_monoview');
  $('engineLabel').textContent=external?(j.settings.asset_type==='print'?'3D PRINT COPY':j.settings.asset_type==='rigged'?t('RIG & ANIMATION'):t('IMPORTED MODEL')):terrain?t('PROCEDURAL TERRAIN'):workflow?`${workflowEngine} · ${resolutionOf(j)}³`:pixalSingle?t('PIXAL3D · SINGLE IMAGE'):pixal?t('PIXAL3D · {count} VIEWS',{count:j.settings.views?.length||0}):`TRELLIS.2 · ${resolutionOf(j)}³`;$('downloadGlb').title=j.settings.asset_type==='print'?t('Download print preview GLB in metres'):terrain?t('Download terrain GLB'):t('Download PBR GLB with all animations');$('sourceThumb').hidden=terrain||external;if(!terrain&&!external&&$('sourcePreview').dataset.id!==j.id){$('sourcePreview').src=`/api/jobs/${j.id}/files/input.png`;$('sourcePreview').dataset.id=j.id;}
  $('exportHint').textContent=j.settings.asset_type==='print'?t('The STL uses millimetres. The Blender package includes the static source and the topology report.'):terrain?t('The Blender package contains the terrain mesh; the Unity export keeps a native Terrain.'):t('GLB includes UVs and materials. The Blender package also provides separate textures and UV layouts.');const r=j.result;$('stats').textContent=j.state==='done'||(j.operation==='animation'&&r)?(r?(terrain?t('{size} m square · elevation {height} m · {resolution}² map',{size:r.dimensions_m?.[0]||j.settings.size_m,height:r.height_m,resolution:r.resolution}):[t('{count} triangles',{count:Number(r.triangles||0).toLocaleString(formatLocale)}),r.bones?t('{count} bones',{count:r.bones}):null,`${Number(r.height_m||0).toLocaleString(formatLocale,{maximumFractionDigits:2})} m`].filter(Boolean).join(' · ')):t('Completed model · ready to inspect')):'';
  const rigPreview = usesRigPreview(j);
  const previewLoaded = loadedId === j.id && previewRevision(loadedRevision);
  if (rigPreview && previewLoaded) $('stats').textContent = t(isCreatureRigDraft(j)&&j.state==='done'?'Creature rig draft':'Source preview');
  if (isStoppedRig(j)) {
    if (!previewLoaded && loadingId !== j.id && (model || loadingId)) {
      ++loadVersion;
      clearModel();
    }
    $('empty').hidden = true;
    if (renderer) $('viewerError').hidden = true;
  }
  if (j.state === 'done' || j.operation === 'animation' || rigPreview) loadModel(j);
  else if (loadedId !== j.id) {
    ++loadVersion;
    clearModel();
    $('empty').hidden = false;
  }
  const entries=[[t('Asset type'),assetTypeName(j.metadata?.asset_type||j.settings.asset_type)],[t('Engine'),external?(j.settings.asset_type==='print'?t('Blender voxel remesh'):j.result?.rig_engine||t('Local import')):terrain?t('Procedural'):workflow?`${workflowEngine} / ${resolutionOf(j)}³`:pixal?`Pixal3D / ${resolutionOf(j)}³`:`TRELLIS.2 / ${resolutionOf(j)}³`],[t('Height'),j.settings.height_m+' m'],[t('Texture'),j.settings.texture_size+' px'],[t('Seed'),j.settings.seed??'—'],[t('Status'),labels[j.state]||j.state],[t('Created'),new Date(j.settings.created*1000).toLocaleDateString(formatLocale)]];const o=j.generation_options;
  const textureMethod=r?.texture_method||j.settings.texture_method;
  const textureLabel=textureMethodChoices.find(([method])=>method===textureMethod)?.[1];
  const refinement=textureMethod==='ultratex' ? r?.finishing?.ultratex_texture_refinement : r?.finishing?.multiview_texture_refinement;
  if(textureLabel&&!terrain){
    const label=refinement && ['skipped','failed','error'].includes(refinement.state)
      ? t('{method} skipped · Native PBR used', {method:t(textureLabel)}) : t(textureLabel);
    entries.push([t('Texture method'),label]);
  }
  if(j.settings.facial_head_enhancement){
    const state=r?.facial_head_enhancement?.state==='applied'?'Applied':j.state==='done'?'No report':'Requested';
    entries.push([t('Enhance face (TOPOS)'),t(state)]);
  }
  const triangleBudget=[j.settings.adaptive_finishing?t('Triangle ceiling'):t('Target triangles'),Number(j.settings.triangles).toLocaleString(formatLocale)];
  if(pixal){
    if (pixalSingle) {
      entries.push([t('Reference images'),t('1 · camera estimated with MoGe')],triangleBudget);
    } else {
      entries.push([t('Reference views'),(j.settings.views||[]).map(view=>view.role).join(' · ')],[t('Side view angle'),j.settings.side_angle+'°'],triangleBudget);
    }
    const projection=j.result?.face_projection;
    if(projection?.state==='applied')entries.push([t('Face reprojection'),t('Applied')]);
    else if(projection?.state==='skipped')entries.push([t('Face reprojection'),projection.reason?t('Skipped. ')+projection.reason:t('Skipped')]);
    else if(j.settings.reproject_face)entries.push([t('Face reprojection'),j.state==='done'?t('No report'):t('Requested')]);
  }else if(workflow)entries.push([t('Profile'),j.settings.profile?.name||workflowEngine],triangleBudget);
  else if(o&&!terrain)entries.push([t('Steps · structure / shape / texture'),`${o.structure_steps} / ${o.shape_steps} / ${o.texture_steps}`],[t('Guidance · structure / shape / texture'),`${o.structure_guidance} / ${o.shape_guidance} / ${o.texture_guidance}`],triangleBudget,[t('Finishing'),o.mesh_mode==='direct'?t('Direct simplification'):t('Remesh and simplify')],[t('Pre-simplify to 2M'),o.pre_simplify?t('Yes'):t('No')],[t('Seed texture'),o.texture_seed<0?t('Main random sequence'):o.texture_seed],[t('Angle UV'),o.uv_angle+'°']);
  if (r?.adaptive_finishing) {
    entries.push([t('Surface tolerance'), r.adaptive_finishing.target_met ? t('Met') : t('Exceeded at the triangle ceiling')]);
  }
  if(j.operation==='texture_projection'||j.settings.source_kind==='texture_projection'){
    const projection=r?.texture_projection;
    if(projection?.state==='applied'){
      const fraction=projection.covered_texels>0?projection.projected_texels/projection.covered_texels:projection.atlas_confidence_fraction;
      if(Number.isFinite(fraction))entries.push([t(projection.covered_texels>0?'Projection coverage on mapped surface':'Projection coverage on texture atlas'),
        fraction.toLocaleString(formatLocale,{style:'percent',maximumFractionDigits:1})]);
      if(projection.overlapping_uv_samples>0)entries.push([t('Excluded overlapping UV samples'),projection.overlapping_uv_samples.toLocaleString(formatLocale)]);
      if(projection.occluded_samples>0)entries.push([t('Excluded hidden samples'),projection.occluded_samples.toLocaleString(formatLocale)]);
    }
  }
  $('assetDetails').replaceChildren(...entries.flatMap(([k,v])=>[node('dt','',k),node('dd','',String(v))]));if(textureOpen&&inspectId!==j.id)inspectTextures();
}
function renderNavigation(){const select=$('librarySelect'),signature=records.map(j=>j.id+nameOf(j)+j.state).join('|');if(select.dataset.signature!==signature){select.replaceChildren(node('option','',t('Choose from the library…')));select.firstChild.value='';for(const j of records){const o=node('option','',nameOf(j)+' · '+(labels[j.state]||j.state));o.value=j.id;select.append(o);}select.dataset.signature=signature;}select.value=selectedId||'';$('count').textContent=records.length;$('collectionCount').textContent=records.length;const recentKey=JSON.stringify([selectedId,records.slice(0,6).map(j=>[j.id,nameOf(j),j.state])]);if($('history').dataset.signature===recentKey)return;$('history').dataset.signature=recentKey;$('history').replaceChildren();for(const j of records.slice(0,6)){const b=node('button','history-card'+(j.id===selectedId?' selected':''));b.type='button';const image=node('img');image.src=`/api/jobs/${j.id}/files/${j.settings.asset_type==='terrain_unity'?'heightmap.png':'input.png'}?v=${j.result?.revision||j.state}`;image.alt='';image.loading='lazy';image.onerror=()=>image.style.visibility='hidden';const t=node('span');t.append(node('strong','',nameOf(j)),node('small','',labels[j.state]||j.state));b.append(image,t);b.onclick=()=>selectJob(j.id);$('history').append(b);}if(!records.length)$('history').append(node('p','history-empty',t('No models yet.')));}
function setMode(terrain){profileControls?.closeWorkflowGraph();animationStudio?.closeRig();animationMode=false;document.body.classList.remove('animation-mode');document.body.classList.remove('library-mode');$('rigPanel').hidden=true;$('rigTab').setAttribute('aria-pressed','false');showCollection(false);$('openLibrary').setAttribute('aria-pressed','false');$('form').hidden=terrain;$('terrainForm').hidden=!terrain;$('imageTab').setAttribute('aria-pressed',!terrain);$('terrainTab').setAttribute('aria-pressed',terrain);document.querySelector('h1').textContent=terrain?t('Create terrain'):t('Image to 3D');$('workspaceIntro').textContent=terrain?t('Textured procedural terrain, ready to adapt to your scene.'):'';$('workspaceIntro').hidden=!terrain;}
function selectJob(id){const keepAnimation=animationMode;if(!records.some(j=>j.id===id))return;if(id!==selectedId){selectedId=id;metadataId=null;inspectId=null;++inspectVersion;$('textureGallery').replaceChildren();$('textureSummary').textContent=t('Inspecting textures…');}setMode(jobOf()?.settings.asset_type==='terrain_unity');if(keepAnimation||isCreatureRigDraft(jobOf()))openAnimationStudio();renderNavigation();renderSelected();renderLibrary();updateButtons();refreshLog();}
$('librarySelect').onchange=()=>selectJob($('librarySelect').value);$('imageTab').onclick=()=>{$('parentId').value='';setMode(false);};$('terrainTab').onclick=()=>{$('terrainForm').dataset.parentId='';setMode(true);};$('openLibrary').onclick=()=>{profileControls?.closeWorkflowGraph();animationStudio?.closeRig();document.body.classList.remove('collection-collapsed');document.body.classList.add('library-mode');showCollection(false);for(const id of['imageTab','terrainTab','rigTab'])$(id).setAttribute('aria-pressed','false');$('openLibrary').setAttribute('aria-pressed','true');renderLibrary();};
function renderLibrary() {
  studioTools?.selection.sync(records, trashMode);
  const grid = $('libraryGrid');
  const query = $('librarySearch').value.toLocaleLowerCase('en');
  const filter = $('libraryFilter').value;
  const list = (trashMode ? trashRecords : records).filter(job => {
    const metadata = job.metadata || {};
    const type = metadata.asset_type || job.settings.asset_type;
    const search = [nameOf(job), metadata.category, assetTypeName(type), ...(metadata.tags || [])]
      .join(' ').toLocaleLowerCase('en');
    return (!workbench || workbench.workspace.matches(job)) && search.includes(query)
      && (filter === 'all' || filter === 'favorite' && metadata.favorite || filter === job.state
        || filter === job.settings.asset_type || filter === metadata.review_state || filter === 'type:' + type);
  });
  const pages = Math.max(1, Math.ceil(list.length / 24));
  page = Math.max(0, Math.min(page, pages - 1));
  const displayed = list.slice(page * 24, page * 24 + 24);
  studioTools?.selection.visible(displayed, list);
  const signature = JSON.stringify([query, filter, page, trashMode, features, selectedId, cardTurntablesAvailable,
    list.map(job => [job.id, nameOf(job), job.state, job.rig_phase, job.metadata, job.media, job.result?.revision,
      job.presentation?.thumbnail?.revision, job.presentation?.library_turntable?.revision])]);
  if (grid.dataset.signature === signature) {
    for (const [index, card] of [...grid.querySelectorAll('[data-job-id]')].entries()) {
      const job = displayed[index];
      updateCardStatus(card, job);
      collectionPreviews.watch(card.querySelector('.asset-preview'), trashMode ? null : job.collection_preview);
    }
    return;
  }
  cardMenu.close();
  cardTurntables.stop();
  collectionPreviews.clear();
  grid.dataset.signature = signature;
  $('pageLabel').textContent = (page + 1) + ' / ' + pages;
  $('pagePrev').disabled = page === 0;
  $('pageNext').disabled = page >= pages - 1;
  $('libraryTotal').textContent = t(list.length>1?'{count} models':'{count} model',{count:list.length});
  $('showTrash').replaceChildren(icon(trashMode ? 'grid' : 'trash'));
  $('showTrash').title = trashMode ? t('Back to library') : t('Open trash');
  $('showTrash').setAttribute('aria-label', $('showTrash').title);
  $('showTrash').disabled = !features;
  $('collectionTitle').textContent = trashMode ? t('Trash') : t('My models');
  $('collectionCount').textContent = trashMode ? trashRecords.length : records.length;
  grid.replaceChildren();

  for (const job of displayed) {
    const name = nameOf(job);
    const card = node('article', 'asset-card' + (job.id === selectedId ? ' selected' : ''));
    const open = node('button', 'card-open');
    const media = node('span', 'asset-preview');
    const image = node('img');
    const assetType = job.settings.asset_type;
    const hasModel = !trashMode && job.state === 'done' && job.media?.available === true;
    card.dataset.jobId = job.id;
    open.type = 'button';
    open.disabled = trashMode;
    const poster = job.presentation?.thumbnail;
    const files = '/api/jobs/' + encodeURIComponent(job.id);
    image.dataset.referenceUrl = trashMode ? '/web/asset-placeholder.svg' : poster
      ? files + '/presentation/thumbnail.png?v=' + encodeURIComponent(poster.revision)
      : files + '/files/' + (assetType === 'terrain_unity' ? 'heightmap.png' : 'input.png')
        + '?v=' + encodeURIComponent(job.result?.revision || job.state);
    image.loading = 'lazy';
    image.alt = '';
    image.onerror = () => { image.onerror = null; image.src = '/web/asset-placeholder.svg'; };
    media.append(image);
    const body = node('span', 'card-body');
    body.append(node('strong', '', name),
      node('small', '', t(categoryName(job.metadata?.category)||'Uncategorised',undefined,'category') + ' · ' + (labels[job.state] || job.state)),
      node('span', 'badge', (job.metadata?.favorite ? '★ · ' : '') + (reviews[job.metadata?.review_state] || t('To review'))));
    open.append(media, body, studioTools.mediaBadge(job));
    open.onclick = () => {
      if (studioTools.selection.mode) studioTools.selection.toggle(job);
      else selectJob(job.id);
    };
    card.append(open);
    if (trashMode) {
      const restore = node('button', 'secondary restore', t('Restore'));
      restore.onclick = async () => {
        restore.disabled = true;
        try {
          await api('/api/trash/' + job.id + '/restore', {method: 'POST'});
          trashRecords = await api('/api/trash');
          await refresh();
          renderLibrary();
        } catch (error) {
          restore.textContent = error.message;
          restore.disabled = false;
        }
      };
      card.append(restore);
    } else {
      const type = isCreatureRigDraft(job) ? t('RIG DRAFT') : assetType === 'terrain_unity' ? t('HEIGHTMAP') : assetType === 'print' ? t('3D PRINT COPY')
        : hasModel ? t('3D MODEL') : t('REFERENCE IMAGE');
      card.append(node('span', 'reference-caption', type), cardMenu.button(job, {busy, features, activeId}));
      studioTools.selection.attach(card, job);
      if (cardTurntablesAvailable) {
        cardTurntables.attach(card, image, job, name, {media, hover: !hasModel});
      }
    }
    updateCardStatus(card, job);
    grid.append(card);
    collectionPreviews.watch(media, hasModel ? job.collection_preview : null);
  }
  if (!list.length) grid.append(node('div', 'library-empty',
    trashMode ? t('The trash is empty.') : t('No models match these filters.')));
}
for(const id of['librarySearch','libraryFilter'])$(id).addEventListener(id==='librarySearch'?'input':'change',()=>{page=0;renderLibrary();});$('pagePrev').onclick=()=>{--page;renderLibrary();};$('pageNext').onclick=()=>{++page;renderLibrary();};$('showTrash').onclick=async()=>{try{trashMode=!trashMode;if(trashMode)trashRecords=await api('/api/trash');page=0;renderLibrary();}catch(e){trashMode=false;errorAt('metadataNotice',e);}};
async function patchMetadata(value){const id=selectedId;if(!id)return;const m=await api(`/api/jobs/${id}/metadata`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}),j=records.find(x=>x.id===id);if(j)j.metadata=m;renderNavigation();renderSelected();renderLibrary();return m;}
$('metadataForm').onsubmit=async e=>{e.preventDefault();$('saveMetadata').disabled=true;try{await patchMetadata({display_name:$('displayName').value,category:$('category').value,asset_type:$('detailAssetType').value,review_state:$('reviewState').value,tags:$('tags').value.split(',').map(x=>x.trim()).filter(Boolean),notes:$('notes').value});$('metadataNotice').textContent=t('Details saved.');}catch(e){errorAt('metadataNotice',e);}finally{$('saveMetadata').disabled=!features||!jobOf();}};$('favorite').onclick=async()=>{try{await patchMetadata({favorite:!jobOf()?.metadata?.favorite});}catch(e){errorAt('metadataNotice',e);}};
let deleteId=null;function requestDelete(j){if(!j)return;deleteId=j.id;$('deleteName').textContent=nameOf(j);$('confirmDelete').disabled=false;$('deleteDialog').showModal();}$('confirmDelete').onclick=async()=>{$('confirmDelete').disabled=true;try{await api(`/api/jobs/${deleteId}`,{method:'DELETE'});if(selectedId===deleteId){selectedId=null;metadataId=null;inspectId=null;++inspectVersion;}$('deleteDialog').close();await refresh();}catch(e){errorAt('deleteName',e);$('confirmDelete').disabled=false;}};
function openImage(url,alt){$('largeImage').src=url;$('largeImage').alt=alt;$('imageDialog').showModal();}$('sourceThumb').onclick=()=>openImage($('sourcePreview').src,t('Model reference'));$('closeImage').onclick=()=>$('imageDialog').close();
function setView(textures){textureOpen=textures;viewport.hidden=textures;$('texturePanel').hidden=!textures;$('view3d').classList.toggle('active',!textures);$('viewTextures').classList.toggle('active',textures);if(textures)inspectTextures();}$('view3d').onclick=()=>setView(false);$('viewTextures').onclick=()=>setView(true);
async function inspectTextures(){const j=jobOf();if(!j||j.state!=='done'||!features)return;const id=j.id;if(inspectId===id)return;inspectId=id;const version=++inspectVersion;$('textureSummary').textContent=t('Extracting texture maps and UV layouts…');$('textureGallery').replaceChildren();try{const d=await api(`/api/jobs/${id}/inspect`);if(version!==inspectVersion||selectedId!==id)return;$('textureSummary').textContent=`${d.meshes.length} mesh(es) · ${d.has_uv?t('UVs present'):t('UVs missing')} · ${d.has_pbr?t('roughness and metalness present'):t('PBR maps incomplete')} · ${d.normals_map_present?t('normal map present'):t('no normal map in this GLB')}`;const items=[...d.textures.map(t=>({...t,detail:`${t.width} × ${t.height} · ${t.color_space}`})),...d.meshes.filter(m=>m.uv_preview).map(m=>({file:m.uv_preview,label:'UV layout · '+m.name,detail:m.uv_warning||t('Painting guide · PNG / SVG included in the package')}))];for(const t of items){const b=node('button','texture-card');b.type='button';const img=node('img');img.src=`/api/jobs/${id}/blender/${t.file}`;img.alt=t.label;b.append(img,node('strong','',t.label),node('small','',t.detail));b.onclick=()=>openImage(img.src,t.label);$('textureGallery').append(b);}if(!items.length)$('textureGallery').append(node('p','hint',t('This model contains no image textures.')));}catch(e){if(version===inspectVersion){inspectId=null;errorAt('textureSummary',e);}}}
function updateButtons(){
  const workflow=profileControls?.workflow;
  if(!jobOf())$('engineLabel').textContent=workflow?workflow.label:'TRELLIS.2';
  const budget=profileControls?.budget();
  const textures=multiview.usesPixal?[1024,2048]:availableTextures;
  const resolutions=multiview.usesPixal?[1024]:availableResolutions;
  for(const option of $('textureSize').options)option.disabled=Number(option.value)!==0&&!textures.includes(Number(option.value));
  multiview.sync(budget?.texture_size);
  const supported=workflow?workflow.available===true:multiview.ready&&advancedControls.ready&&profileControls?.ready&&profileControls.finishingReady
    && resolutions.includes(budget?.resolution)&&textures.includes(budget?.texture_size);
  $('generate').disabled=!multiview.hasFront||!supported||shutDown||submittingGeneration||restoringReferences;
  referencePreview.sync(!!workflow||shutDown||submittingGeneration||restoringReferences);
  $('openReferencePreview').hidden=!!workflow;
  if(workflow){$('cropReference').hidden=true;$('referenceEditSummary').hidden=true;}
  updateRefinishTool(jobOf());
  $('cancel').hidden=!busy;
  $('cancel').disabled=!activeId||jobOf()?.settings.asset_type==='terrain_unity';
  $('createTerrain').disabled=busy||shutDown||!features;
}
$('copyReferencePrompt').onclick=async()=>{const prompt=`Production reference for a contemporary stylised realism game. Subject: ${$('name').value}. ${$('referencePrompt').value}\nOne complete object fully visible and centred, isolated on a plain neutral grey background, single three-quarter view. Credible construction, readable detail and carefully worked materials. Soft diffuse light and minimal shadow. No surrounding scene, text, logo or multi-view sheet. Keep thin parts readable and show the whole subject without cropping. The grey background is not part of the object.`;try{await navigator.clipboard.writeText(prompt);$('notice').textContent=t('Brief copied. Use it with your image generator.');}catch{$('referencePrompt').value=prompt;$('referencePrompt').closest('details').open=true;$('referencePrompt').focus();$('referencePrompt').select();$('notice').textContent=t('The brief is ready in the context field for you to copy.');}};
$('form').onsubmit=async event=>{
  event.preventDefault();
  if($('generate').disabled)return;
  submittingGeneration=true;
  updateButtons();
  $('notice').textContent='';
  try{
    const workflow=profileControls.workflow;
    const current=new FormData($('form'));
    const form=workflow?new FormData():current;
    if(workflow){
      if(!await referencePreview.reviewEdges(current.get('image')))return;
      for(const field of ['image','profile_id','name','height_m','asset_type','reference_prompt','parent_id']){
        if(current.has(field))form.set(field,current.get(field));
      }
      if(!profileControls.appendWorkflow(form))return;
    }else{
      if(!await referencePreview.reviewEdges())return;
      for(const [field,value] of Object.entries(profileControls.budget()))form.set(field,String(value));
      multiview.appendRequest(form);
      form.set('remove_bg',String(multiview.usesPixal||$('removeBg').checked));
      form.set('keep_finishing_source',String($('keepFinishingSource').checked));
      if(!multiview.usesPixal)form.set('advanced_settings',JSON.stringify(advancedControls.read()));
      profileControls.appendFinishing(form);
      referencePreview.append(form);
      profileControls.closeWorkflowGraph();
    }
    form.set('queue_only','true');
    const v=await api(multiview.active?'/api/generate-multiview':'/api/generate',{method:'POST',body:form});
    if(!selectedId){selectedId=v.id;metadataId=null;}
    revealNewCreation();
    await refresh();
  }catch(error){errorAt('notice',error);}
  finally{submittingGeneration=false;updateButtons();}
};
$('cancel').onclick=async()=>{if(!activeId)return;try{await api(`/api/jobs/${activeId}/cancel`,{method:'POST'});await refresh();}catch(e){errorAt('notice',e);}};
function revealNewCreation(){trashMode=false;page=0;$('librarySearch').value='';$('libraryFilter').value='all';document.body.classList.remove('collection-collapsed','library-mode');$('toggleCollection').setAttribute('aria-pressed','true');showCollection(false);$('libraryGrid').scrollTop=0;}
document.querySelectorAll('[data-material]').forEach(b=>b.onclick=()=>{generationWait.userModeChanged();$('materialMode').value=b.dataset.material;if(b.dataset.material==='hologram')hologramViewer?.restart();document.querySelectorAll('[data-material]').forEach(x=>x.setAttribute('aria-pressed',x===b));materials();});
function ranges(){$('roughnessValue').textContent=Math.round(Number($('roughness').value)*100)+' %';$('flatValue').textContent=Math.round(Number($('flatZone').value)*100)+' %';}$('roughness').oninput=ranges;$('flatZone').oninput=ranges;
$('terrainForm').onsubmit=async e=>{e.preventDefault();if(busy)return;busy=true;updateButtons();$('notice').textContent=t('Creating terrain and textures…');const data={name:$('terrainName').value,terrain_style:$('terrainStyle').value,size_m:Number($('terrainSize').value),height_m:Number($('terrainHeight').value),seed:Number($('terrainSeed').value),roughness:Number($('roughness').value),flat_zone:Number($('flatZone').value),resolution:Number($('terrainResolution').value),terrain_palette:$('terrainPalette').value,parent_id:$('terrainForm').dataset.parentId||''};try{const v=await api('/api/terrain',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});selectedId=v.id;metadataId=null;$('notice').textContent=t('Terrain created.');setView(false);await refresh();}catch(e){busy=false;errorAt('notice',e);updateButtons();}};
async function reuseJob(j){
  if(!j||busy||submittingGeneration||restoringReferences)return;
  const s=j.settings;
  if(['imported','rigged','print'].includes(s.asset_type)){
    try{
      const v=await api(`/api/jobs/${j.id}/version`,{method:'POST'});
      await startStudioJob(v.id);
    }catch(error){errorAt('notice',error);}
    return;
  }
  if(s.asset_type==='terrain_unity'){
    setMode(true);
    $('terrainForm').dataset.parentId=j.id;
    for(const [id,v] of Object.entries({terrainName:nameOf(j)+' version',terrainStyle:s.terrain_style,terrainSize:s.size_m,terrainHeight:s.height_m,terrainSeed:s.seed,roughness:s.roughness,flatZone:s.flat_zone,terrainResolution:s.resolution,terrainPalette:s.terrain_palette||'blackwater'}))$(id).value=String(v);
    ranges();
    return;
  }
  restoringReferences=true;
  updateButtons();
  try{
    await multiview.restore(j);
    $('facialPortrait').value='';
    if(s.facial_portrait){
      const response=await fetch(`/api/jobs/${j.id}/files/facial-portrait.png`);
      if(!response.ok)throw Error(t('The supplemental portrait could not be restored.'));
      const transfer=new DataTransfer();
      transfer.items.add(new File([await response.blob()],'facial-portrait.png',{type:'image/png'}));
      $('facialPortrait').files=transfer.files;
    }
    referencePreview.restore(s.reference_edits,s.remove_bg);
    setMode(false);
    $('parentId').value=j.id;
    $('name').value=(nameOf(j)+' version').slice(0,80);
    $('height').value=String(s.height_m);
    $('assetType').value=s.asset_type||'object';
    $('referencePrompt').value=j.metadata?.reference_prompt||'';
    if(profileControls.restoreWorkflow(s)){
      detailControls.hint();
      $('notice').textContent='Reference and workflow settings restored.';
      return;
    }
    if(s.workflow_id)throw Error('This model’s workflow is missing from the current profile catalogue.');
    for(const [id,v] of Object.entries({preset:s.preset,seed:s.seed,triangles:s.triangles,textureSize:s.texture_size,resolution:s.resolution||j.result?.resolution||512}))$(id).value=String(v);
    profileControls.restoreFinishing(s);
    const restoredOptions = s.hd_reconstruction||s.repair_surface||s.master_finishing ? s.generation_options : j.generation_options;
    advancedControls.apply(restoredOptions||s.generation_options||{});
    $('removeBg').checked=s.remove_bg??multiview.usesPixal;
    detailControls.hint();
    profileControls.detach(s.profile?.id);profileControls.restoreSource(s.keep_finishing_source);
    $('profileBase').value=$('preset').value;
    explainCost();
    $('notice').textContent=t('Reference, geometry, texture and finishing settings restored. Adjust them to compare a new version.');
  }catch(error){errorAt('notice',error);}
  finally{restoringReferences=false;updateButtons();}
}

function updateRefinishTool(job){
  const control=$('toolbarRefinishControl'),button=$('toolbarRefinish');
  control.hidden=job?.state!=='done';
  button.disabled=control.hidden||!job.can_refinish||busy||shutDown;
  const panel=$('refinishDialog');
  if(panel.matches(':popover-open')&&(button.disabled||panel.dataset.source!==job?.id))panel.hidePopover();
  if(control.hidden)return;
  control.title=shutDown?t('Restart TRELLIS Studio to remesh.'):!job.can_refinish?
    t('Finishing source unavailable. Enable “Keep source for finishing variants” when generating a new model.'):
    busy?t('Wait for the active computation to finish.'):t('Remesh · choose triangle budget');
  if(button.disabled){control.tabIndex=0;control.setAttribute('aria-label',`Remesh. ${control.title}`);}
  else{control.removeAttribute('tabindex');control.removeAttribute('aria-label');}
}

const refinishPanel = $('refinishDialog');
const refinishButton = $('toolbarRefinish');
const refinishForm = $('refinishForm');
const refinishFields = refinishForm.elements;
let refinishRequest = 0;
let submittingRefinish = false;

function positionRefinish() {
  if (!refinishPanel.matches(':popover-open')) return;
  const anchor = refinishButton.getBoundingClientRect();
  if (!anchor.width || anchor.bottom < 0 || anchor.top > innerHeight) {
    refinishPanel.hidePopover();
    return;
  }
  const {width, height} = refinishPanel.getBoundingClientRect();
  const gap = 10;
  const left = anchor.left + (anchor.width - width) / 2;
  const above = anchor.top - height - gap;
  const below = anchor.bottom + gap;
  const top = above >= gap || below + height > innerHeight - gap ? above : below;
  refinishPanel.style.left = Math.max(gap, Math.min(innerWidth - width - gap, left)) + 'px';
  refinishPanel.style.top = Math.max(gap, Math.min(innerHeight - height - gap, top)) + 'px';
}

function syncRefinishMode() {
  const hd = !refinishFields.hd_reconstruction.disabled && refinishFields.hd_reconstruction.checked;
  const wtivo = !refinishFields.wtivo_reconstruction.disabled && refinishFields.wtivo_reconstruction.checked;
  const reconstruction = hd || wtivo;
  if (reconstruction) {
    refinishFields.budget_mode.value = 'fixed';
    refinishFields.budget_preset.value = 'manual';
    refinishFields.repair_surface.checked = false;
  }
  for (const fieldset of refinishForm.querySelectorAll('[data-refinish-budgets]')) {
    fieldset.disabled = reconstruction;
    fieldset.hidden = reconstruction;
  }
  $('refinishRepair').hidden = reconstruction;
  const adaptive = refinishFields.budget_mode.value === 'adaptive';
  const preset = refinishFields.budget_preset.value;
  const manual = preset === 'manual';
  const repair = !refinishFields.repair_surface.disabled && refinishFields.repair_surface.checked;
  $('refinishBudgetField').hidden = !manual;
  refinishFields.triangles.disabled = !manual;
  $('refinishBudgetLabel').textContent = hd || adaptive ? t('Maximum triangles') : t('Target triangles');
  $('refinishManualOptions').hidden = !manual || adaptive || repair || reconstruction;
  $('startRefinishLabel').textContent = wtivo ? t('Create WTiVo variant')
    : hd ? t('Reconstruct HD variant') : repair ? t('Create repaired variant') : t('Create variant');
  const budgetHint = adaptive ? t('Tests lighter meshes up to the chosen ceiling.') : t('The final count can be lower.');
  const presetHint = {
    medium: t('Budget for a game model.'),
    ultra: t('Can exceed the preview mesh. Dense variants take longer to process.'),
  }[preset];
  $('refinishBudgetHint').textContent = [presetHint, budgetHint].filter(Boolean).join(' ');
}

async function openRefinish(job) {
  if (busy || shutDown || submittingRefinish || !job?.can_refinish) return;
  if (selectedId !== job.id || document.body.classList.contains('library-mode')) selectJob(job.id);
  setView(false);
  refinishButton.scrollIntoView({block: 'nearest', inline: 'nearest'});
  const request = ++refinishRequest;
  refinishPanel.dataset.source = job.id;
  $('refinishSource').textContent = nameOf(job);
  $('refinishSource').title = nameOf(job);
  $('refinishControls').hidden = true;
  $('refinishStatus').hidden = false;
  $('refinishStatus').textContent = t('Loading triangle budgets…');
  $('refinishError').hidden = true;
  $('startRefinish').disabled = true;
  $('refinishOptions').open = false;
  if (!refinishPanel.matches(':popover-open')) refinishPanel.showPopover({source: refinishButton});
  positionRefinish();

  try {
    const config = await api(`/api/jobs/${job.id}/finishing-board`);
    if (request !== refinishRequest || !refinishPanel.matches(':popover-open')) return;
    const {triangle_limits: limits, triangle_presets: presets, texture_sizes: textures} = config;
    $('refinishDisplayedTriangles').textContent = formatTriangles(job.result?.triangles);
    $('refinishSourceTriangles').textContent = formatTriangles(config.source_triangles);
    for (const item of refinishPanel.querySelectorAll('[data-budget]')) {
      const count = presets[item.dataset.budget];
      item.textContent = count >= 1000000 ? `${count / 1000000}M` : `${count / 1000}k`;
      item.closest('label').title = t('{count} triangles',{count:count.toLocaleString(formatLocale)});
    }
    refinishFields.budget_mode.value = 'fixed';
    refinishFields.budget_preset.value = 'medium';
    refinishFields.repair_surface.checked = false;
    refinishFields.repair_surface.disabled = config.repair_surface !== true;
    refinishFields.hd_reconstruction.checked = false;
    refinishFields.hd_reconstruction.disabled = config.hd_reconstruction !== true;
    $('refinishHdReconstruction').hidden = refinishFields.hd_reconstruction.disabled;
    refinishFields.wtivo_reconstruction.checked = false;
    refinishFields.wtivo_reconstruction.disabled = config.wtivo_reconstruction !== true;
    $('refinishWtivoReconstruction').hidden = refinishFields.wtivo_reconstruction.disabled;
    $('refinishRepairHint').textContent = refinishFields.repair_surface.disabled ?
      t('Restart Studio to enable hole repair.') : t('Closes gaps using the cached source. Fine edges may soften.');
    refinishFields.triangles.min = limits.min;
    refinishFields.triangles.max = limits.max;
    const suggested = job.result?.triangles || job.settings.triangles || presets.medium;
    refinishFields.triangles.value = Math.max(limits.min, Math.min(limits.max, suggested));
    const options = job.generation_options || job.settings.generation_options || {};
    refinishFields.mesh_mode.value = options.mesh_mode || 'direct';
    refinishFields.repair_holes.checked = !!options.repair_holes;
    refinishFields.pre_simplify.checked = !!options.pre_simplify;
    refinishFields.texture_size.replaceChildren(...textures.map(size => new Option(`${size / 1024}K`, size)));
    refinishFields.texture_size.value = textures.includes(job.settings.texture_size) ? job.settings.texture_size : textures[0];
    refinishFields.bake_normals.disabled = !config.normal_bake;
    refinishFields.bake_normals.checked = !!config.normal_bake;
    $('refinishBake').hidden = !config.normal_bake;
    $('refinishStatus').hidden = true;
    $('refinishControls').hidden = false;
    $('startRefinish').disabled = false;
    syncRefinishMode();
    positionRefinish();
    if ([document.body, refinishButton, $('closeRefinish')].includes(document.activeElement)) {
      refinishForm.querySelector('[name="budget_mode"]:checked').focus({preventScroll: true});
    }
  } catch (error) {
    if (request === refinishRequest && refinishPanel.matches(':popover-open')) {
      $('refinishStatus').textContent = error.message || String(error);
      positionRefinish();
    }
  }
}

refinishButton.onclick = event => {
  event.preventDefault();
  if (refinishPanel.matches(':popover-open')) refinishPanel.hidePopover();
  else openRefinish(jobOf());
};
$('closeRefinish').onclick = () => refinishPanel.hidePopover();
refinishPanel.addEventListener('toggle', event => {
  const open = event.newState === 'open';
  refinishButton.setAttribute('aria-expanded', open);
  if (!open && refinishPanel.contains(document.activeElement)) refinishButton.focus({preventScroll: true});
});
new ResizeObserver(positionRefinish).observe(refinishPanel);
window.addEventListener('resize', positionRefinish);
window.addEventListener('scroll', positionRefinish, {capture: true, passive: true});

refinishForm.addEventListener('change', event => {
  const {name} = event.target;
  if (name === 'hd_reconstruction' && refinishFields.hd_reconstruction.checked) {
    refinishFields.wtivo_reconstruction.checked = false;
    refinishFields.triangles.value = 1200000;
    refinishFields.bake_normals.checked = false;
  }
  if (name === 'wtivo_reconstruction' && refinishFields.wtivo_reconstruction.checked) {
    refinishFields.hd_reconstruction.checked = false;
  }
  if (name === 'budget_preset') {
    refinishFields.bake_normals.checked = !refinishFields.bake_normals.disabled && refinishFields.budget_preset.value === 'medium';
  }
  if (['budget_mode', 'budget_preset', 'repair_surface', 'hd_reconstruction', 'wtivo_reconstruction'].includes(name)) syncRefinishMode();
});

refinishForm.onsubmit = async event => {
  event.preventDefault();
  const source = refinishPanel.dataset.source;
  if (!source || submittingRefinish || $('startRefinish').disabled) return;
  const preset = refinishFields.budget_preset.value;
  const data = {texture_size: Number(refinishFields.texture_size.value)};
  if (!refinishFields.bake_normals.disabled) data.bake_normals = refinishFields.bake_normals.checked;
  if (!refinishFields.wtivo_reconstruction.disabled && refinishFields.wtivo_reconstruction.checked) {
    data.wtivo_reconstruction = true;
    data.triangles = refinishFields.triangles.valueAsNumber;
  } else {
    data.adaptive_finishing = refinishFields.budget_mode.value === 'adaptive';
    if (!refinishFields.repair_surface.disabled && refinishFields.repair_surface.checked) data.repair_surface = true;
    if (!refinishFields.hd_reconstruction.disabled && refinishFields.hd_reconstruction.checked) data.hd_reconstruction = true;
    if (preset === 'manual') {
      data.triangles = refinishFields.triangles.valueAsNumber;
      if (!data.adaptive_finishing && !data.repair_surface && !data.hd_reconstruction) {
        data.mesh_mode = refinishFields.mesh_mode.value;
        data.repair_holes = refinishFields.repair_holes.checked;
        data.pre_simplify = refinishFields.pre_simplify.checked;
      }
    } else data.budget_preset = preset;
  }

  submittingRefinish = true;
  $('startRefinish').disabled = true;
  $('refinishError').hidden = true;
  try {
    const result = await api(`/api/jobs/${source}/refinish`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    if (refinishPanel.matches(':popover-open')) refinishPanel.hidePopover();
    await startStudioJob(result.id);
  } catch (error) {
    errorAt('refinishError', error);
    $('refinishError').hidden = false;
    if (!refinishPanel.matches(':popover-open')) errorAt('notice', error);
  } finally {
    submittingRefinish = false;
    $('startRefinish').disabled = false;
  }
};

async function refreshLog(){if(!selectedId)return;try{const d=await api(`/api/jobs/${selectedId}/log`);$('log').textContent=d.text||t('No log entries yet.');}catch{}}
let lastRevision, collectionOrder = [], reviewAfter = '', reviewing = false, lastCollectionRead = 0, currentRefresh = null, needsRefresh = false;
const studioPoll = visiblePoll(() => refresh(false), () => busy || pendingSelection ? 3000 : 12000);

async function refresh(force = true) {
  if (shutDown) return;
  if (currentRefresh) {
    if (force) needsRefresh = true;
    return currentRefresh;
  }
  currentRefresh = (async () => {
    do {
      needsRefresh = false;
      try {
        const status = await api('/api/status?collection_hint=true');
        const collectionChanged = !status.collection_revision || collectionDue({force: force || reviewing, active: status.active, wasActive: activeId,
          pending: pendingSelection, revision: status.collection_revision, previous: lastRevision,
          age: Date.now() - lastCollectionRead});
        let jobs = records;
        if (collectionChanged) {
          const checkNested = reviewing || Date.now() - lastCollectionRead >= 60000;
          if (status.collection_revision) {
            const watch = [...new Set([status.active, activeId, pendingSelection].filter(Boolean))];
            const query = new URLSearchParams({since: force ? '' : lastRevision || '', watch: watch.join(',')});
            if (checkNested && !force && lastRevision) query.set('review_after', reviewAfter);
            const delta = await api('/api/collection/sync?' + query);
            if (delta.order) collectionOrder = delta.order;
            jobs = mergeCollection(records, delta, collectionOrder);
            lastRevision = delta.revision;
            if (delta.full || delta.review_after != null) {
              reviewAfter = delta.review_after || '';
              reviewing = !!reviewAfter;
              if (!reviewing) lastCollectionRead = Date.now();
            }
          } else {
            jobs = await api('/api/jobs');
            lastCollectionRead = Date.now();
          }
        }
        features = !!status.studio_version;
        cardTurntablesAvailable = status.features?.includes('library_turntable') === true;
        syncCapabilities(status);
        ready = status.ready;
        activeId = status.active;
        busy = !!activeId;
        records = jobs;
        if (pendingSelection) {
          const pending = records.find(job => job.id === pendingSelection);
          if (pending?.state === 'done') {
            if (pending.operation_error) errorAt('animationNotice', pending.operation_error);
            selectedId = pendingSelection;
            pendingSelection = metadataId = inspectId = null;
          } else if (pending && ['error', 'cancelled'].includes(pending.state)) {
            errorAt('animationNotice', isStoppedRig(pending) ? rigJobError(pending) : pending.error || pending.stage);
            pendingSelection = null;
          }
        }
        if (selectedId && !records.some(job => job.id === selectedId)) {
          selectedId = metadataId = inspectId = null;
          ++inspectVersion;
        }
        syncVersionNotice(status);
        const stage = jobs.find(job => job.id === activeId)?.stage;
        const summary = runtimeSummary(status, stage);
        $('runtime').textContent = ready ? summary : t('WORKSHOP · generation engine not installed') + ' · ' + summary;
        $('runtime').title = $('runtime').textContent;
        workbench?.queue.setRuntime(status, stage);
        $('hardware').textContent = status.gpu || t('Local compute');
        updateButtons();
        if (collectionChanged) {
          renderNavigation();
          renderSelected();
          renderLibrary();
          refreshRigPreview();
        }
        if (document.querySelector('.journal').open) refreshLog();
      } catch (error) {
        console.error('Studio refresh failed:', error);
        $('runtime').textContent = t('Disconnected · restart TRELLIS');
        ready = false;
        multiview.setCapabilities({message: t('Studio is disconnected. Restart TRELLIS Studio.')});
        updateButtons();
      }
      force = needsRefresh;
    } while (needsRefresh && !shutDown);
  })().finally(() => { currentRefresh = null; });
  return currentRefresh;
}
$('shutdown').onclick=async()=>{try{await api('/api/shutdown',{method:'POST'});shutDown=true;studioPoll.stop();ready=false;busy=false;renderer?.setAnimationLoop(null);generationWait.dispose();clearModel();hologramViewer?.dispose();renderer?.dispose();$('notice').textContent=t('Run Open TRELLIS.cmd to restart the studio.');$('runtime').textContent=t('STUDIO STOPPED');$('shutdown').disabled=true;downloads(null);$('downloadHeight').hidden=true;updateButtons();}catch(e){errorAt('notice',e);}};
function showCollection(details){$('libraryView').hidden=details;$('inspectorPanel').hidden=!details;$('collectionPanel').classList.toggle('details-open',details);}
function openDetails(j) {
  if (!j) return;
  selectJob(j.id);
  document.body.classList.remove('library-mode', 'collection-collapsed');
  $('openLibrary').setAttribute('aria-pressed', 'false');
  const workspaceTab = animationMode ? 'rigTab' : $('terrainForm').hidden ? 'imageTab' : 'terrainTab';
  $(workspaceTab).setAttribute('aria-pressed', 'true');
  showCollection(true);
}
$('backToCollection').onclick=()=>showCollection(false);
$('toggleCollection').onclick=()=>{const collapsed=document.body.classList.toggle('collection-collapsed');$('toggleCollection').setAttribute('aria-pressed',!collapsed);};
function openAnimationStudio(){setMode(false);animationMode=true;document.body.classList.add('animation-mode');$('form').hidden=true;$('rigPanel').hidden=false;$('imageTab').setAttribute('aria-pressed','false');$('rigTab').setAttribute('aria-pressed','true');document.querySelector('h1').textContent=t('Animation studio');$('workspaceIntro').textContent=isCreatureRig(jobOf())?t('Prepare the skeleton and inspect its clips.'):t('Choose a motion and add it to your model.');$('workspaceIntro').hidden=false;animationStudio?.render();}
$('rigTab').onclick=openAnimationStudio;$('animateModel').onclick=openAnimationStudio;

for (const workflowTab of document.querySelectorAll('[data-workflow-tab]')) {
  const railTab = $(workflowTab.dataset.workflowTab);
  const syncPressed = () => workflowTab.setAttribute('aria-pressed', railTab.getAttribute('aria-pressed'));
  syncPressed();
  new MutationObserver(syncPressed).observe(railTab, {attributeFilter: ['aria-pressed']});
  workflowTab.addEventListener('click', () => railTab.click());
}

document.addEventListener('paste',event=>{
  if(referencePreview.open||event.target.closest('input:not([type=file]),textarea,[contenteditable=true]'))return;
  const file=[...(event.clipboardData?.files||[])].find(value=>value.type.startsWith('image/'));
  if(file){
    event.preventDefault();
    setMode(false);
    multiview.accept(multiview.pasteRole(event.target),file);
  }
});
async function startStudioJob(id,options={}){if(options.rig){selectedId=id;metadataId=null;}busy=true;pendingSelection=id;revealNewCreation();updateButtons();await refresh();}
async function loadRigSource(id){
  const current=model;
  let source;
  try{
    ({scene:source}=await new GLTFLoader().loadAsync(`/api/jobs/${encodeURIComponent(id)}/files/model.glb`));
  }catch{
    throw Error(t('Could not load the original unrigged model.'));
  }
  if(current!==model){disposeModel(source);return null;}
  const visibility=[current,skeletonHelper,boneDots].filter(Boolean).map(object=>[object,object.visible]);
  for(const [object] of visibility)object.visible=false;
  scene.add(source);
  return {
    model:source,
    close(){
      scene.remove(source);
      disposeModel(source);
      for(const [object,visible] of visibility)object.visible=visible;
    },
  };
}
animationStudio=await createAnimationStudio({api,getJob:jobOf,isBusy:()=>busy,startJob:startStudioJob,refresh,rigSetup:rigSetupViewer,creatureViewer:creatureRigViewer,getClips:loadedAnimationClips,playClip:playAnimationClip,loadRigSource,
  openDiagnostics:id=>studioTools.diagnostics.open(records.find(record=>record.id===id))});createModelImport({api,startJob:startStudioJob});
workbench=await createStudioWorkbench({api,getRecords:()=>records,getJob:jobOf,refresh,startJob:startStudioJob,renderLibrary,tools:studioTools,canUseCardTurntables:()=>cardTurntablesAvailable,labelAnimation:name=>animationStudio?.label(name)||name,getViewer:()=>({scene,renderer,camera,controls,model,loadedId,lighting:viewerLighting})});
document.querySelector('.journal').addEventListener('toggle',refreshLog);await refresh();const entry=new URLSearchParams(location.search),entryModel=entry.get('model');if(entryModel&&records.some(j=>j.id===entryModel))selectJob(entryModel);if(entry.get('workspace')==='animation')openAnimationStudio();if(entry.get('workspace')==='details'&&jobOf())openDetails(jobOf());const comparison=records.find(j=>j.id===entry.get('compare')&&j.state==='done');if(comparison&&jobOf()?.state==='done')studioTools.compare.open(jobOf(),comparison,{focus:entry.get('focus')});studioPoll.start();

function setupClips(gltf){
 clipObstacles=motionObstacles(gltf,jobOf()?.result);
 clips=gltf.animations;mixer=clips.length?new THREE.AnimationMixer(model):null;
 mixer?.addEventListener('finished',({action})=>{
  if(action!==clipAction)return;
  clipPlaying=false;
  $('clipPlay').querySelector('use').setAttribute('href','/web/icons.svg#play');
 });
 $('clipSelect').replaceChildren(...clips.map((c,i)=>{const o=node('option','',animationStudio?.label(c.name)||c.name);o.value=i;return o;}));
 skeletonHelper=new THREE.SkeletonHelper(model);skeletonHelper.visible=jobOf()?.settings.source_kind==='unirig';skeletonHelper.material.depthTest=false;skeletonHelper.material.vertexColors=false;skeletonHelper.material.color.set(0xc4f58a);skeletonHelper.renderOrder=10;scene.add(skeletonHelper);if(skeletonHelper.bones.length){const radius=Math.max(new THREE.Box3().setFromObject(model,true).getSize(new THREE.Vector3()).y*.004,.003);boneDots=new THREE.InstancedMesh(new THREE.SphereGeometry(radius,8,6),new THREE.MeshBasicMaterial({color:0xc4f58a,depthTest:false}),skeletonHelper.bones.length);boneDots.renderOrder=11;boneDots.frustumCulled=false;scene.add(boneDots);}$('clipSkeleton').setAttribute('aria-pressed',skeletonHelper.visible);
 $('animationPlayer').hidden=!clips.length&&!skeletonHelper.bones.length;
 $('clipSelect').hidden=!clips.length;$('clipTime').hidden=!clips.length;$('clipPlay').hidden=!clips.length;
 if(clips.length){
  const params=new URLSearchParams(location.search);
  const requested=params.get('model')===loadedId?params.get('clip'):null;
  selectClip(Math.max(0,clips.findIndex(clip=>clip.name===requested)),false);
 }
}
function loadedAnimationClips(job) {
  if (!model || loadedId !== job?.id || previewRevision(loadedRevision)) return null;
  if (job.state === 'done' && loadedRevision !== (job.result?.revision || 0)) return null;
  return clips;
}

function playAnimationClip(index, name) {
  if (loadedAnimationClips(jobOf())?.[index]?.name !== name) return;
  setView(false);
  selectClip(index);
}

function selectClip(index, reframe = true) {
  const clip = clips[index];
  if (!mixer || !clip) return;
  const hadObstacle = obstaclePreview.active;
  mixer.stopAllAction();
  clipAction = mixer.clipAction(clip);
  playPreviewAction(clipAction,Boolean(clipObstacles[index]));
  mixer.update(0);
  obstaclePreview.set(model, clipObstacles[index]);
  if (reframe && (hadObstacle || obstaclePreview.active)) fit();
  clipPlaying = true;
  clock.getDelta();
  $('clipPlay').querySelector('use').setAttribute('href', '/web/icons.svg#pause');
  $('clipSelect').value = String(index);
  $('clipTime').max = clip.duration;
  $('clipTime').value = 0;
  $('clipTimeValue').value = '0 s';
}
$('clipSelect').onchange=()=>selectClip(Number($('clipSelect').value));
$('clipPlay').onclick=()=>{
 clipPlaying=!clipPlaying;
 if(clipPlaying&&clipAction)playPreviewAction(clipAction,obstaclePreview.active);
 $('clipPlay').querySelector('use').setAttribute('href','/web/icons.svg#'+(clipPlaying?'pause':'play'));
};
$('clipTime').oninput=()=>{if(!clipAction)return;clipPlaying=false;clipAction.time=Number($('clipTime').value);mixer.update(0);$('clipPlay').querySelector('use').setAttribute('href','/web/icons.svg#play');$('clipTimeValue').value=clipAction.time.toFixed(1)+' s';};
$('clipSkeleton').onclick=()=>{if(predictedSkeleton&&(!skeletonHelper||!skeletonHelper.bones.length)){predictedSkeleton.visible=!predictedSkeleton.visible;$('clipSkeleton').setAttribute('aria-pressed',predictedSkeleton.visible);return;}if(skeletonHelper){skeletonHelper.visible=!skeletonHelper.visible;$('clipSkeleton').setAttribute('aria-pressed',skeletonHelper.visible);}};
async function refreshRigPreview() {
  const job = jobOf();
  if (!usesRigPreview(job) || isCreatureRig(job) || loadedId !== job.id || !previewRevision(loadedRevision) || predictedId === job.id) return;
  const version = loadVersion;
  const stopped = isStoppedRig(job);
  if (rigSkeletonRequest === version || (stopped && stoppedSkeletonChecked === version)) return;
  if (stopped) stoppedSkeletonChecked = version;
  rigSkeletonRequest = version;
  try {
    const data = await api(`/api/jobs/${job.id}/rig-preview`);
    if (!data.ready || selectedId !== job.id || loadVersion !== version || !usesRigPreview(jobOf())) return;
    const vertices = data.bones.flatMap(bone => [...bone.head, ...bone.tail]);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    if (predictedSkeleton) {
      scene.remove(predictedSkeleton);
      predictedSkeleton.geometry.dispose();
      predictedSkeleton.material.dispose();
    }
    predictedSkeleton = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({color: 0xc4f58a, depthTest: false, transparent: true, opacity: .95}));
    predictedSkeleton.renderOrder = 12;
    scene.add(predictedSkeleton);
    predictedId = job.id;
    $('animationPlayer').hidden = false;
    $('clipSkeleton').setAttribute('aria-pressed', 'true');
  } catch {
    // The preview is optional while UniRig prepares the skeleton.
  } finally {
    if (rigSkeletonRequest === version) rigSkeletonRequest = null;
  }
}
