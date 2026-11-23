import {formatLocale, language, t} from './i18n.js';
import {icon} from './card-menu.js?v=2.6.1';
import {createMotionPreviews} from './authored-previews.js?v=3.4.0';
import {createPersonalAnimationLibrary} from './personal-animation-library.js?v=3.4.0-motion2';
import {createCreatureRigEditor, createSwimFields, isCreatureRig, isCreatureRigDraft} from './creature-rig-editor.js?v=3.15.1-rigs';
import {createCreatureMotions} from './creature-motions.js?v=3.15.1-rigs?v=creature-motions';

function creatureSkeletonIcon(){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
 svg.classList.add('ui-icon');
 svg.setAttribute('aria-hidden','true');
 svg.setAttribute('viewBox','0 0 24 24');
 svg.innerHTML=`<path d="M12 6v3m-1.5 3.3-5 4.4m8-4.4 5 4.4M12 13v5"/>
  <circle cx="12" cy="4" r="2"/><circle cx="12" cy="11" r="2"/>
  <circle cx="4" cy="18" r="2"/><circle cx="12" cy="20" r="2"/><circle cx="20" cy="18" r="2"/>`;
 return svg;
}

const rigProfileNames={auto:'Auto',simple:'Simple',standard:'Standard',advanced:'Advanced',expert:'Expert',expressive:'Expressive'};
const rigProfileDescriptions={
 auto:'Use the skeleton detected by UniRig.',
 simple:'22 body joints with rigid hands.',
 standard:'52 joints with articulated fingers. Requires five separate digits on each hand.',
};
const rigHandDescriptions={
 advanced:{
  rigid:'24 joints with rigid hands and forearm twist.',
  articulated:'54 joints with articulated fingers and forearm twist. Requires five separate digits on each hand.',
 },
 expert:{
  rigid:'49 joints with rigid hands. Adds 25 joints for the torso, shoulders, arms, pelvis and legs.',
  articulated:'79 joints, including 25 additional joints for the torso, shoulders, arms, pelvis and legs. Requires five separate digits on each hand.',
 },
 expressive:{
  rigid:'65 joints with rigid hands. Includes 41 body helpers, 16 more than Expert.',
  articulated:'95 joints with articulated fingers. Includes 41 body helpers, 16 more than Expert. Requires five separate digits on each hand.',
 },
};
const availableRigProfiles=status=>['simple','standard','advanced','expert','expressive'].filter(profile=>Array.isArray(status.rig_profiles)&&status.rig_profiles.includes(profile));

export async function createAnimationStudio({api,getJob,isBusy,startJob,refresh,rigSetup,creatureViewer,getClips,playClip,loadRigSource,openDiagnostics}){
 const $=id=>document.getElementById(id),data=await api('/api/animations');
 let tab='library';const catalog=data.animations,previews=createMotionPreviews();
 let batchAvailable=false,removeAvailable=false,creatureRigAvailable=false,creatureClipTarget=null,rigProfiles=[];
 let tentacleAvailable=false,swimAvailable=false,creatureMotionsAvailable=false;
 let rigSourceCheck=null,openingRig=null,rigSourcePreview=null;
 let selecting=false,selectionTarget=null,submitting=false;
 let clipNotice=null,removal=null;
 let swimCheck=null,pendingSwim=null;
 const swimEditor=$('creatureSwimEditor'),swimStatus=$('creatureSwimStatus');
 const finalSwim=createSwimFields($('creatureFinalSwimFields'));
 const selectedClips=new Set();
 const batchLimit=Number.isInteger(data.max_batch_clips)?data.max_batch_clips:catalog.length;
 const categories=[...new Set(catalog.map(c=>c.category))];
 for(const category of categories){const option=document.createElement('option');option.value=category;option.textContent=t(category);$('animationCategory').append(option);}
 const nameOf=j=>j?.metadata?.display_name||j?.settings.name||t('Choose a model from the collection');
 $('animationDuration').oninput=()=>{$('animationDurationValue').value=Number($('animationDuration').value).toLocaleString(formatLocale)+' s';};
 const hasRig=job=>Boolean(job?.result?.bones||job?.result?.rigged||job?.media?.bones);
 const canEdit=job=>job?.state==='done'&&!isBusy()&&!submitting;
 const canAdd=job=>canEdit(job)&&hasRig(job)&&!isCreatureRig(job);
 const canRemove=job=>canEdit(job)&&removeAvailable;
 const canCreateVariant=job=>rigProfiles.length>0||(creatureRigAvailable&&isCreatureRig(job));
 const rigSourceId=job=>rigSourceCheck?.jobId===job?.id?rigSourceCheck?.sourceId:null;
 const personal=createPersonalAnimationLibrary({api,getJob,canAdd,
  applyMotion:(job,motion)=>editClips(job,'POST',{animation_id:motion.id,in_place:false},t('Animation added.'),false,`/api/jobs/${encodeURIComponent(job.id)}/my-animations`),
  onCount:count=>{$('personalAnimationCount').textContent=count;}});
 const creatureEditor=createCreatureRigEditor({api,viewer:creatureViewer,startJob,getJob,isBusy,
  onVisibility(visible){
   document.body.classList.toggle('creature-rig-editing',visible);
   $('animationLibraryControls').hidden=visible||Boolean(rigJobId);
  }});
 const creatureMotions=createCreatureMotions({api,canEdit,async apply(job,recipe){
  const result=await editClips(job,'POST',recipe,t('Creature motion added.'),false,
   `/api/jobs/${encodeURIComponent(job.id)}/creature-motions`);
  if(result.ok&&getJob()?.id===job.id&&tab==='creature'){
   setAnimationTab('Added');render();
   if(!$('rigPanel').hidden)$('animationTabAdded').focus();
  }
  return result;
 }});

 function authoredMotion(name){
  const match=/^TS_(.+)_([0-9.]+)s$/.exec(name||'');
  if(!match)return null;
  return {id:match[1],title:t(catalog.find(clip=>clip.id===match[1])?.name||match[1]),duration:Number(match[2])};
 }

 function embeddedClips(job){
  if(!job)return [];
  const loaded=getClips(job);
  const items=job.media?.animation_items
   ?? (loaded?.map(({name},index)=>({index,name}))||job.media?.animation_names?.map((name,index)=>({index,name}))||[]);
  const entries=items.map(({index,name})=>{
   const expectedName=name||`animation_${index}`;
   const preview=loaded?.[index]?.name===expectedName?loaded[index]:null;
   const authored=authoredMotion(name);
   const generated=job.settings?.generated_animation_clips?.find(clip=>clip.clip===name);
   const duration=preview?.duration??generated?.duration??authored?.duration??job.result?.animation_set?.find(clip=>clip.clip===name)?.duration_s;
   return {index,name,expectedName,duration,recipeId:authored?.id,playable:!!preview,title:generated?.name||authored?.title||(name&&isCreatureRig(job)?t(name):name)||t('Animation {number}',{number:index+1})};
  });
  const duplicates=new Set(entries.filter((entry,index)=>entries.findIndex(other=>other.title===entry.title)!==index).map(entry=>entry.title));
  return entries.map(entry=>duplicates.has(entry.title)?{...entry,title:`${entry.title} (${entry.index+1})`}:entry);
 }

 function showClipNotice(job){
  const message=clipNotice?.id===job?.id?clipNotice?.message||'':'';
  if($('animationClipNotice').textContent!==message)$('animationClipNotice').textContent=message;
 }

 function setClipNotice(id,message){
  clipNotice={id,message};
  showClipNotice(getJob());
 }

 function resetSelection(){
  selecting=false;
  selectedClips.clear();
 }

 function updateSelectionControls(job){
  const enabled=canAdd(job),count=selectedClips.size;
  $('createRig').disabled=!canEdit(job)||!rigSetup?.ready||Boolean(openingRig);
  $('animationSelection').hidden=tab!=='library'||isCreatureRig(job)||!batchAvailable||!batchLimit;
  $('selectAnimations').disabled=!enabled;
  $('selectAnimations').setAttribute('aria-pressed',String(selecting));
  $('selectAnimations').querySelector('span').textContent=selecting?t('Cancel selection'):t('Select clips');
  $('selectedAnimationCount').hidden=!selecting;
  const countLabel=t(count===1?'{count} clip selected':'{count} clips selected',{count});
  if($('selectedAnimationCount').textContent!==countLabel)$('selectedAnimationCount').textContent=countLabel;
  $('animationSelectionActions').hidden=!selecting;
  $('clearAnimationSelection').disabled=!count||submitting;
  $('addAnimationSelection').disabled=!count||!enabled;
  for(const button of $('animationCards').querySelectorAll('button[data-clip]'))button.disabled=!enabled;
  for(const button of $('animationCards').querySelectorAll('button[data-remove-clip]'))button.disabled=!canRemove(job);
  for(const input of $('animationCards').querySelectorAll('input[data-select-clip]')){
   input.checked=selectedClips.has(input.dataset.selectClip);
   input.disabled=!enabled||(!input.checked&&count>=batchLimit);
   input.closest('.animation-card').classList.toggle('selected-motion',input.checked);
   input.nextElementSibling.textContent=input.checked?t('Selected'):t('Select');
  }
 }

 function renderRigTarget(job){
  const rigged=hasRig(job),done=job?.state==='done';
  const result=job?.result;
  const profile=result?.rig_profile;
  const bones=result?.bones||job?.media?.bones||profile?.joint_count;
  let state=rigged?(bones?t(bones===1?'{count} bone · ready to animate':'{count} bones · ready to animate',{count:bones}):t('Rigged · ready to animate')):done?t('Add a rig to use the motion library.'):t('Open a completed model from the collection.');
  if(profile&&Object.hasOwn(rigProfileNames,profile.profile)){
   const hands=t(profile.articulated_fingers?'Articulated fingers':'Rigid hands');
   const modules=[];
   if(Object.keys(profile.twists||{}).length)modules.push(t('Forearm twist'));
   const bodyJoints=Object.keys(profile.body_helpers||{}).length;
   if(bodyJoints)modules.push(t('{count} additional body joints',{count:bodyJoints}));
   state=[state,t(rigProfileNames[profile.profile]),hands,...modules].join(' · ');
  }
  if(isCreatureRigDraft(job))state=t('Check the proposed skeleton before calculating skin weights.');
  else if(isCreatureRig(job)&&result?.creature_motion?.warning){
   state+=' · '+result.creature_motion.warning.split(/(?<=\.)\s+/).map(message=>t(message)).join(' ');
  }
  $('animationRigState').textContent=state;
  const skipped=Array.isArray(result?.rig_skipped_clips)?result.rig_skipped_clips.filter(name=>typeof name==='string'):[];
  $('animationRigSkipped').hidden=!skipped.length;
  $('animationRigSkipped').textContent=skipped.length?t('Clips to retarget separately · {clips}',{clips:skipped.join(', ')}):'';
  const sourceNotice=rigged&&canCreateVariant(job)&&rigSourceCheck?.jobId===job?.id?rigSourceCheck?.notice:'';
  $('animationRigSourceNotice').hidden=!sourceNotice;
  $('animationRigSourceNotice').textContent=sourceNotice||'';
  const create=$('createRig');
  create.hidden=isCreatureRigDraft(job)||(rigged&&!rigSourceId(job));
  create.querySelector('span').textContent=t(rigged?'Create rig variant':'Add rig');
  create.disabled=!canEdit(job)||!rigSetup?.ready||Boolean(openingRig);
 }

 async function checkRigSource(job){
  if(!canCreateVariant(job)||!loadRigSource||$('rigPanel').hidden||job?.state!=='done'||!hasRig(job)){
   rigSourceCheck=null;
   return;
  }
  if(rigSourceCheck?.jobId===job.id)return;
  const check={jobId:job.id,notice:t('Checking for the original rig source…')};
  rigSourceCheck=check;
  try{
   const source=await api(`/api/jobs/${encodeURIComponent(job.id)}/rig-source`);
   if(!/^[0-9a-f]{32}$/.test(source?.id))throw Error(t('The original unrigged model is unavailable.'));
   check.sourceId=source.id;
   check.options=source.rig_options;
   check.notice='';
  }catch(error){check.notice=t(error.message);}
  if(rigSourceCheck===check&&getJob()?.id===job.id)renderRigTarget(getJob());
 }

 function updateSwimControls(job){
  const enabled=Boolean(swimCheck?.compatible&&swimCheck.id===job?.id&&canEdit(job));
  $('creatureApplySwim').disabled=!enabled;
  finalSwim.enable(enabled);
 }

 function syncSwimEditor(job,editing){
  if(swimCheck?.id!==job?.id){
   swimCheck=null;
   swimEditor.open=false;
   swimStatus.textContent='';
  }
  if(pendingSwim&&pendingSwim.id!==job?.id)pendingSwim=null;
  const visible=swimAvailable&&!editing&&!rigJobId&&!$('rigPanel').hidden
   &&isCreatureRig(job)&&!isCreatureRigDraft(job)&&job.state==='done';
  swimEditor.hidden=!visible||!swimCheck?.compatible;
  updateSwimControls(job);
  if(!visible)return;
  const revision=job.media?.animation_revision;
  if(swimCheck&&swimCheck.revision===revision)return;
  const check={id:job.id,revision,compatible:swimCheck?.compatible===true};
  swimCheck=check;
  api(`/api/jobs/${encodeURIComponent(job.id)}/creature-swim`,{cache:'no-store'}).then(summary=>{
   if(check!==swimCheck||getJob()?.id!==check.id)return;
   check.compatible=summary.compatible===true;
   if(check.compatible)finalSwim.set(summary.options);
   swimEditor.hidden=!check.compatible||$('rigPanel').hidden||Boolean(rigJobId);
   updateSwimControls(getJob());
  }).catch(()=>{
   if(check===swimCheck){check.compatible=false;swimEditor.hidden=true;}
  });
 }

 function playUpdatedSwim(){
  const job=getJob();
  if(!pendingSwim||pendingSwim.id!==job?.id||pendingSwim.previous===job.result?.revision)return;
  const loaded=getClips(job);
  const index=loaded?.findIndex(clip=>clip.name===pendingSwim.clip);
  if(index>=0){
   playClip(index,pendingSwim.clip);
   pendingSwim=null;
  }
 }

 $('creatureSwimForm').onsubmit=async event=>{
  event.preventDefault();
  const job=getJob();
  if(swimEditor.hidden||!swimCheck?.compatible||swimCheck.id!==job?.id||!canEdit(job))return;
  const options=finalSwim.get();
  if(!options)return;
  swimStatus.textContent=t('Updating swim…');
  submitting=true;
  updateSwimControls(job);
  try{
   const revised=await api(`/api/jobs/${encodeURIComponent(job.id)}/creature-swim`,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(options),
   });
   if(getJob()?.id===job.id){
    pendingSwim={id:job.id,clip:revised.clip_name,previous:job.result?.revision};
    setAnimationTab('Added');
    swimStatus.textContent=t('Swim updated.');
   }
  }catch(error){
   if(getJob()?.id===job.id)swimStatus.textContent=t(error.message);
  }finally{
   submitting=false;
   try{await refresh();}
   finally{render();playUpdatedSwim();}
  }
 };

 async function editClips(job,method,body,success,batch=false,path=`/api/v1/models/${job.id}/animations`){
  setClipNotice(job.id,method==='DELETE'?t('Removing clip…'):t('Saving animations…'));
  submitting=true;
  updateSelectionControls(job);
  try{
   const result=await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   const statusUrl=result.status_url||`/api/v1/jobs/${job.id}`;
   while(true){
    const status=await api(statusUrl,{cache:'no-store'});
    if(status.state==='done'&&!status.operation_error){
     if(batch&&selectionTarget===job.id)resetSelection();
     setClipNotice(job.id,success);
     return {ok:true};
    }
    if(status.state==='error'||status.state==='cancelled'||status.operation_error){
     throw Error(status.operation_error||status.error||status.stage||t('Animation update did not complete.'));
    }
    if(status.stage)setClipNotice(job.id,t(status.stage));
    await new Promise(resolve=>setTimeout(resolve,900));
   }
  }catch(error){setClipNotice(job.id,t(error.message));return {ok:false,error:error.message};}
  finally{
   try{await refresh();}
   finally{submitting=false;render();}
  }
 }

 function submitMotions(ids,batch=false){
  const job=getJob();
  if(!canAdd(job)||!ids.length||(batch&&!batchAvailable))return;
  const duration=Number($('animationDuration').value);
  const clips=ids.map(clip=>({clip,duration}));
  return editClips(job,'POST',batch?{clips}:clips[0],ids.length===1?t('Animation saved.'):t('Animations saved.'),batch);
 }

 function confirmRemoval(job,clip){
  if(!canRemove(job))return;
  removal={id:job.id,index:clip.index,name:clip.name,revision:job.media?.animation_revision};
  $('animationRemoveName').textContent=clip.title;
  $('animationRemoveDialog').returnValue='cancel';
  $('animationRemoveDialog').showModal();
 }

 $('animationRemoveDialog').addEventListener('close',()=>{
  const target=removal,job=getJob();
  removal=null;
  if($('animationRemoveDialog').returnValue==='remove'&&target?.id===job?.id&&canRemove(job)){
   editClips(job,'DELETE',{index:target.index,clip:target.name,revision:target.revision},t('Animation removed.'));
  }
 });

 $('selectAnimations').onclick=()=>{
  if(selecting)resetSelection();else selecting=true;
  render();
 };
 $('clearAnimationSelection').onclick=()=>{
  selectedClips.clear();
  updateSelectionControls(getJob());
 };
 $('addAnimationSelection').onclick=()=>submitMotions([...selectedClips],true);
 const rotation=[];let rigStep=0,rigJobId=null,savedLandmarks=null;
 for(const axis of ['X','Y','Z']){const label=document.createElement('label');label.className='rig-rotation';const caption=document.createElement('span');caption.textContent=t('Rotation {axis}',{axis});const slider=document.createElement('input');slider.type='range';slider.min=-180;slider.max=180;slider.step=1;slider.value=0;slider.setAttribute('aria-label',t('Rotation {axis}',{axis}));const value=document.createElement('output');value.value='0°';const reset=document.createElement('button');reset.type='button';reset.className='quiet';reset.append(icon('rotate'));reset.setAttribute('aria-label',t('Reset rotation {axis}',{axis}));reset.onclick=()=>{slider.value=0;changeRig();};slider.oninput=changeRig;label.append(caption,slider,value,reset);rotation.push(slider);$('rigRotationControls').append(label);}
 function rigOptions(){return {rotation:rotation.map(s=>Number(s.value)),height_m:Number($('rigHeight').value),offset_m:Number($('rigOffset').value)};}
 function changeRig(){rotation.forEach(s=>s.nextElementSibling.value=s.value+'°');$('rigHeightValue').value=Number($('rigHeight').value).toLocaleString(formatLocale,{minimumFractionDigits:2})+' m';$('rigHeightNumber').value=$('rigHeight').value;$('rigOffsetValue').value=Number($('rigOffset').value).toLocaleString(formatLocale)+' m';rigSetup?.preview(rigOptions(),rigSourcePreview?.model);}
 function showRigStep(step){
  rigStep=step;
  const creature=step===0&&$('rigMode').value==='creature';
  document.body.classList.toggle('rig-orienting',step===0&&!creature);
  $('rigModeField').hidden=step!==0||!creatureRigAvailable||Boolean(rigSourcePreview&&!rigProfiles.length);
  $('rigTransformStep').hidden=step!==0||creature;
  $('rigLandmarkStep').hidden=step!==1;
  $('rigCreatureStep').hidden=!creature;
  $('resetRigSetup').hidden=creature;
  $('rigStepLabel').textContent=t(creature?'Skeleton prediction':step===0?'01 / Size & orientation':'02 / Joint placement');
  $('confirmRigSetup').replaceChildren(creature?creatureSkeletonIcon():icon('skeleton'),t(creature?'Predict skeleton':step===0?'Next · place joints':'Confirm & create rig'));
  $('cancelRigSetup').textContent=step===0?t('Cancel'):t('Back',undefined,'navigation');
 }
 function closeRig(){
  document.body.classList.remove('rig-preparing','rig-orienting','rig-source-preview');
  if(openingRig)$('animationNotice').textContent='';
  rigSetup?.close();
  rigSourcePreview?.close();
  rigSourcePreview=null;
  openingRig=null;
  rigJobId=null;
  savedLandmarks=null;
  creatureEditor.close();
  $('rigSetup').hidden=true;
  $('animationLibraryControls').hidden=false;
 }

 function describeRigProfile(){
  const profile=$('rigProfile').value;
  const fingers=$('rigArticulatedFingers').checked;
  const hands=rigHandDescriptions[profile];
  $('rigFingerControls').hidden=!hands;
  $('rigProfileDescription').textContent=t(hands?.[fingers?'articulated':'rigid']||rigProfileDescriptions[profile]||'');
 }
 $('rigProfile').onchange=describeRigProfile;
 $('rigArticulatedFingers').onchange=describeRigProfile;
 $('rigMode').onchange=()=>{
  if($('rigMode').value==='creature')rigSetup?.close();
  showRigStep(0);
  if($('rigMode').value==='humanoid')changeRig();
 };

 function beginRig(job,retryOptions=null){
  const previous=rigSourcePreview?{...job.settings?.rig_options,...rigSourceCheck?.options}:retryOptions;
  const profiles=rigSourcePreview?rigProfiles:['auto',...rigProfiles];
  const selected=profiles.includes(previous?.profile)?previous.profile:profiles[0];
  const select=$('rigProfile');
  select.replaceChildren(...profiles.map(profile=>{
   const option=document.createElement('option');
   option.value=profile;
   option.textContent=t(rigProfileNames[profile]);
   return option;
  }));
  select.value=selected;
  $('rigArticulatedFingers').checked=previous?.articulated_fingers!==false;
  $('rigProfileControls').hidden=!rigProfiles.length;
  $('rigSourcePreviewHint').hidden=!rigSourcePreview;
  describeRigProfile();
  document.body.classList.add('rig-preparing');
  document.body.classList.toggle('rig-source-preview',Boolean(rigSourcePreview));
  rigJobId=job.id;
  savedLandmarks=previous?.landmarks||null;
  $('rigSetup').hidden=false;
  $('animationLibraryControls').hidden=true;
  swimEditor.hidden=true;
  $('rigMode').value=creatureRigAvailable&&isCreatureRig(job)?'creature':'humanoid';
  showRigStep(0);
  rotation.forEach((slider,index)=>slider.value=previous?.rotation?.[index]??0);
  $('rigHeight').value=Math.min(3,Math.max(.2,previous?.height_m||job.result?.height_m||1.7));
  $('rigOffset').value=previous?.offset_m??0;
  $('rigSymmetry').checked=true;
  if($('rigMode').value==='humanoid')changeRig();
 }

 function rigidProfile(preferred){
  const enabled=profile=>rigProfiles.includes(profile);
  const supportsRigid=profile=>profile==='simple'||Boolean(rigHandDescriptions[profile]);
  if(enabled(preferred)&&supportsRigid(preferred))return preferred;
  return ['simple','advanced','expert','expressive'].find(enabled);
 }
 $('openRigDiagnostics').onclick=()=>openDiagnostics?.(rigSourcePreview?rigSourceId(getJob()):rigJobId);

 $('createRig').onclick=async()=>{
  const job=getJob();
  if(!canEdit(job)||!rigSetup?.ready||openingRig)return;
  if(!hasRig(job)){beginRig(job);return;}
  const source=rigSourceId(job);
  if(!source||!canCreateVariant(job))return;
  const request={jobId:job.id};
  openingRig=request;
  renderRigTarget(job);
  $('animationNotice').textContent=t('Loading the original unrigged model…');
  try{
   const preview=await loadRigSource(source);
   if(openingRig!==request||getJob()?.id!==job.id||$('rigPanel').hidden||!canEdit(job)||!canCreateVariant(job)){
    preview?.close();
    return;
   }
   if(!preview)throw Error(t('The original unrigged model is unavailable.'));
   rigSourcePreview=preview;
   $('animationNotice').textContent='';
   beginRig(job);
  }catch(error){
   if(openingRig===request){
    closeRig();
    $('animationNotice').textContent=t(error.message);
   }
  }finally{
   if(openingRig===request)openingRig=null;
   renderRigTarget(getJob());
  }
 };
 $('rigHeight').oninput=changeRig;$('rigOffset').oninput=changeRig;
 $('rigHeightNumber').oninput=()=>{const input=$('rigHeightNumber');if(!input.validity.valid||!input.value)return;$('rigHeight').value=input.value;changeRig();};
 $('cancelRigSetup').onclick=()=>{if(rigStep===1){savedLandmarks=rigSetup.getLandmarks();rigSetup.endMarkers();showRigStep(0);}else{closeRig();render();}};
 $('resetRigSetup').onclick=()=>{if(rigStep===1){rigSetup.resetMarkers();return;}savedLandmarks=null;rotation.forEach(s=>s.value=0);$('rigHeight').value=1.7;$('rigOffset').value=0;changeRig();};
 $('rigSymmetry').onchange=()=>rigSetup.setSymmetry($('rigSymmetry').checked);
 $('confirmRigSetup').onclick=async()=>{
  const options=rigOptions(),j=getJob(),button=$('confirmRigSetup');
  if(!j||j.id!==rigJobId){closeRig();return;}
  if(!canEdit(j)||button.disabled)return;
  if(rigStep===0&&$('rigMode').value==='creature'){
   if(!creatureRigAvailable||isBusy()||button.disabled)return;
   const source=rigSourcePreview?rigSourceId(j):j.id;
   if(!source)return;
   button.disabled=true;
   $('animationNotice').textContent='';
   try{
    const result=await api(`/api/jobs/${source}/rig`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'creature'})});
    closeRig();
    await startJob(result.id,{rig:true});
   }catch(error){$('animationNotice').textContent=t(error.message);}
   finally{button.disabled=false;render();}
   return;
  }
  if(rigStep===0){
   if(!$('rigHeightNumber').reportValidity())return;
   $('animationNotice').textContent='';showRigStep(1);
   rigSetup.startMarkers({points:savedLandmarks,symmetry:$('rigSymmetry').checked,onChange:(points,key)=>{
    $('rigSelectedPoint').textContent=t(key.replaceAll('_',' '))+' · '+points[key].map(v=>(v*options.height_m).toLocaleString(formatLocale,{minimumFractionDigits:3,maximumFractionDigits:3})).join(language==='fr'?' / ':', ')+' m';
   }});return;
  }
  options.landmarks=rigSetup.getLandmarks();button.disabled=true;$('animationNotice').textContent='';
  const profile=$('rigProfile').value;
  if(rigHandDescriptions[profile])options.articulated_fingers=$('rigArticulatedFingers').checked;
  if(profile&&profile!=='auto')options.profile=profile;
  try{
   const status=await api('/api/status');
   if(!status.features?.includes('rig_landmarks'))throw Error(t('Restart TRELLIS to enable manual joint placement before creating this rig.'));
   if((options.profile&&!availableRigProfiles(status).includes(options.profile))||(rigSourcePreview&&!options.profile)){
    throw Error(t('This skeleton profile is no longer available. Close the setup and select an available profile.'));
   }
   if(getJob()?.id!==j.id||rigJobId!==j.id)return;
   const result=await api(`/api/jobs/${j.id}/rig`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(options)});
   $('animationNotice').textContent='';
   closeRig();await startJob(result.id,{rig:true});
  }catch(error){$('animationNotice').textContent=t(error.message);}
  finally{button.disabled=false;render();}
 };
 function renderAdded(job,clips,query){
  const list=clips.filter(clip=>clip.title.toLocaleLowerCase().includes(query));
  $('animationAvailableCount').textContent=t(list.length===1?'{count} clip':'{count} clips',{count:list.length});
  for(const clip of list){
   const row=document.createElement('article');row.className='added-motion';
   const heading=document.createElement('div');heading.className='added-motion-heading';
   const title=document.createElement('h3');title.textContent=clip.title;
   heading.append(icon('motion'),title);
   if(Number.isFinite(clip.duration)&&clip.duration>0){
    const time=document.createElement('span');
    time.textContent=clip.duration.toLocaleString(formatLocale,{maximumFractionDigits:2})+' s';
    heading.append(time);
   }
   const actions=document.createElement('div');actions.className='added-motion-actions';
   const play=document.createElement('button');play.type='button';play.className='secondary has-icon';
   play.append(icon('play'),document.createTextNode(t('Play on character')));
   play.setAttribute('aria-label',t('Play {title} on character',{title:clip.title}));
   play.disabled=!clip.playable;
   play.onclick=()=>playClip(clip.index,clip.expectedName);
   actions.append(play);
   if(removeAvailable){
    const remove=document.createElement('button');remove.type='button';remove.className='quiet has-icon';remove.dataset.removeClip=clip.index;
    remove.setAttribute('aria-label',t('Remove {title}',{title:clip.title}));
    remove.append(icon('trash'),document.createTextNode(t('Remove')));
    remove.onclick=()=>confirmRemoval(job,clip);
    actions.append(remove);
   }
   row.append(heading,actions);
   $('animationCards').append(row);
  }
  if(!list.length){
   const p=document.createElement('p');p.className='hint';
   p.textContent=clips.length?t('No added clips match your search.'):t('This model has no embedded animations.');
   $('animationCards').append(p);
  }
 }

 function render(){
  const job=getJob(),rigged=hasRig(job),done=job?.state==='done',creature=isCreatureRig(job);
  if(selectionTarget!==job?.id||!batchAvailable)resetSelection();
  selectionTarget=job?.id;
  $('animationModel').textContent=nameOf(job);
  checkRigSource(job);
  renderRigTarget(job);
  const editing=creatureEditor.sync(job,creatureRigAvailable&&!$('rigPanel').hidden,{tentacles:tentacleAvailable,swim:swimAvailable});
  syncSwimEditor(job,editing);
  if(editing){
   previews.clear();
   personal.setVisible(false,'');
   creatureMotions.update(job,false);
   return;
  }
  if(isCreatureRig(job)&&!isCreatureRigDraft(job)&&creatureClipTarget!==job.id){
   creatureClipTarget=job.id;
   setAnimationTab('Added');
  }
  const creatureMotionsEligible=creatureMotionsAvailable&&rigged&&job?.media?.available!==false
   && !isCreatureRigDraft(job)&&(done||job?.operation==='animation');
  $('animationTabCreature').hidden=!creatureMotionsEligible;
  if(!creatureMotionsEligible&&tab==='creature')setAnimationTab('Library');
  const q=$('animationSearch').value.toLocaleLowerCase(formatLocale),added=embeddedClips(job);
  const addedTab=tab==='added',personalTab=tab==='personal',creatureTab=tab==='creature';
  const compatibility=$('animationRigCompatibility');
  compatibility.hidden=!creature||addedTab||creatureTab;
  compatibility.textContent=personalTab
   ? t('Text-to-motion creates humanoid animations. You can save them here and apply them to a humanoid rig.')
   : t('These motions are for humanoid rigs. Preview them here or select a humanoid to apply them.');
  $('animationAddedCount').textContent=added.length;
  $('animationDurationControl').hidden=tab!=='library'||creature;
  $('animationCategory').hidden=tab!=='library';
  $('animationSearch').hidden=creatureTab;
  $('animationSearch').placeholder=addedTab?t('Search added clips…'):personalTab?t('Search my animations…'):t('Search standard animations…');
  $('personalAnimationComposer').hidden=!personalTab;
  $('personalAnimationLibraryHeading').hidden=!personalTab;
  $('personalAnimationCards').hidden=!personalTab;
  $('personalMotionNotice').hidden=!personalTab;
  $('personalMotionApplyHint').hidden=!personalTab||creature;
  $('animationCards').hidden=personalTab||creatureTab;
  $('rigPanel').classList.toggle('personal-motion-mode',personalTab);
  personal.setVisible(personalTab,q);
  creatureMotions.update(job,creatureTab&&!$('rigPanel').hidden);
  $('animationCards').classList.toggle('added-motion-list',addedTab);
  showClipNotice(job);
  previews.clear();$('animationCards').replaceChildren();
  if(creatureTab){updateSelectionControls(job);return;}
  if(personalTab){updateSelectionControls(job);personal.updateTarget();return;}
  if(addedTab){
   renderAdded(job,added,q);
   updateSelectionControls(job);
   return;
  }
  const list=catalog.filter(c=>(t(c.name).toLocaleLowerCase().includes(q)||c.name.toLocaleLowerCase().includes(q))&&(!$('animationCategory').value||c.category===$('animationCategory').value));
  $('animationAvailableCount').textContent=t(list.length===1?'{count} motion':'{count} motions',{count:list.length});
  for(const clip of list){
   const present=added.find(c=>c.recipeId===clip.id),card=document.createElement('article');card.className='animation-card motion-'+clip.id;
   const preview=document.createElement('div');preview.className='motion-preview';previews.attach(preview,clip);preview.append(icon('motion'));const chip=document.createElement('span');chip.className='motion-chip';chip.textContent=present?t('✓ ADDED'):t('3D PREVIEW');preview.append(chip);
   const title=document.createElement('h3');title.textContent=t(clip.name);const text=document.createElement('p');text.textContent=present&&Number.isFinite(present.duration)?t('Added · {duration} s',{duration:present.duration.toLocaleString(formatLocale,{maximumFractionDigits:2})}):t(clip.description);
   card.append(preview,title,text);
   if(selecting){
    const label=document.createElement('label');label.className='motion-select';
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.dataset.selectClip=clip.id;
    checkbox.setAttribute('aria-label',t('Select {title}',{title:t(clip.name)}));
    checkbox.onchange=()=>{
     if(checkbox.checked)selectedClips.add(clip.id);else selectedClips.delete(clip.id);
     updateSelectionControls(getJob());
    };
    label.append(checkbox,document.createElement('span'));
    card.append(label);
   }else{
    const add=document.createElement('button');add.type='button';add.className=present?'secondary':'primary';add.dataset.clip=clip.id;
    add.append(icon(present?'version':'plus'),document.createTextNode(present?t('Update'):t('Add to model')));
    add.onclick=()=>submitMotions([clip.id]);
    card.append(add);
   }
   if(present)card.classList.add('added');$('animationCards').append(card);
  }
  if(!list.length){const p=document.createElement('p');p.className='hint';p.textContent=t('No motions match your search.');$('animationCards').append(p);}
  updateSelectionControls(job);
 }
 const tabs=['Library','Personal','Creature','Added'];
 function setAnimationTab(name){
  tab=name.toLowerCase();
  for(const candidate of tabs){
   const button=$('animationTab'+candidate);
   const active=candidate===name;
   button.classList.toggle('active',active);
   button.setAttribute('aria-selected',String(active));
   button.tabIndex=active?0:-1;
  }
  resetSelection();
  $('animationSearch').value='';
 }
 for(const [index,name] of tabs.entries()){
  const button=$('animationTab'+name);
  button.onclick=()=>{setAnimationTab(name);render();};
  button.tabIndex=index===0?0:-1;
  button.onkeydown=event=>{const visible=tabs.filter(t=>!$('animationTab'+t).hidden);if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)||visible.length<2)return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?visible.length-1:(visible.indexOf(name)+(event.key==='ArrowRight'?1:-1)+visible.length)%visible.length;const target=$('animationTab'+visible[next]);target.click();target.focus();};
 }
 $('animationSearch').oninput=render;$('animationCategory').onchange=render;
 let signature='';
 return {
  closeRig,
  canRetryRigidHands(options){return Boolean(rigSetup?.ready&&rigidProfile(options?.profile));},
  retryRigidHands(options){
   const job=getJob(),profile=rigidProfile(options?.profile);
   if(!profile||!canEdit(job)||hasRig(job)||!rigSetup?.ready)return;
   beginRig(job,{...options,profile,articulated_fingers:false});
  },
  label(name){
   const generated=getJob()?.settings?.generated_animation_clips?.find(clip=>clip.clip===name)||personal.findClip(name);
   if(generated)return generated.name+(Number.isFinite(generated.duration)?` · ${generated.duration.toLocaleString(formatLocale)} s`:'');
   const clip=authoredMotion(name);
   return clip?`${clip.title} · ${clip.duration.toLocaleString(formatLocale)} s`:isCreatureRig(getJob())?t(name):name;
  },
  setCapabilities(status){
   batchAvailable=status.features?.includes('animation_batch')===true;
   removeAvailable=status.features?.includes('animation_clip_removal')===true;
   creatureRigAvailable=status.features?.includes('creature_rig')===true;
   tentacleAvailable=creatureRigAvailable&&status.features?.includes('creature_tentacles')===true;
   swimAvailable=creatureRigAvailable&&status.features?.includes('creature_swim')===true;
   creatureMotionsAvailable=status.features?.includes('creature_motions')===true;
   rigProfiles=availableRigProfiles(status);
  },
  modelLoaded(){
   if(isCreatureRigDraft(getJob())||tab==='added'||!Array.isArray(getJob()?.media?.animation_items))render();
   playUpdatedSwim();
  },
  update(){
   const job=getJob();
   if((rigJobId&&rigJobId!==job?.id)||(openingRig&&openingRig.jobId!==job?.id))closeRig();
   const key=JSON.stringify([job?.id,job?.state,job?.operation,job?.rig_phase,job?.media?.available,job?.result?.creature_motion,job?.result?.bones,job?.result?.rigged,job?.result?.revision,
    job?.result?.rig_profile,job?.result?.rig_skipped_clips,rigProfiles,job?.media?.bones,job?.media?.animation_items,
    job?.media?.animation_names,job?.media?.animation_revision,isBusy(),rigSetup?.ready,batchAvailable,removeAvailable,creatureRigAvailable,tentacleAvailable,swimAvailable,creatureMotionsAvailable]);
   if(signature!==key){signature=key;render();}
  },
  render,
 };
}
