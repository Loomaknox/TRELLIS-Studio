import {icon} from './card-menu.js?v=2.6.1';
import {createPersonalMotionPreviews} from './personal-animation-previews.js?v=3.4.0';

export function createPersonalAnimationLibrary({api,getJob,canAdd,applyMotion,onCount}){
 const $=id=>document.getElementById(id),host=$('personalAnimationCards'),cards=new Map();
 let previews=null;
 const activeStates=new Set(['queued','running']);
 let items=[],engine=null,loaded=false,loading=false,reloadAgain=false,posting=false,visible=false,pollTimer=0,filter='',transferId=null,loadError='';
 const text=(tag,className,value)=>{const el=document.createElement(tag);el.className=className;el.textContent=value;return el;};
 const notice=(message,error=false)=>{$('personalMotionNotice').textContent=message;$('personalMotionNotice').classList.toggle('error',error);};
 const labelState=state=>({queued:'Queued',running:'Generating',done:'Saved',error:'Failed',cancelled:'Cancelled'})[state]||'Pending';
 const hasMotion=(target,motion)=>{
  if(!target)return false;
  if(Array.isArray(target.media?.animation_items))return !!motion.clip_name&&target.media.animation_items.some(clip=>clip.name===motion.clip_name);
  return target.settings?.generated_animation_clips?.some(clip=>clip.id===motion.id)??false;
 };
 const inView=()=>visible&&!$('rigPanel').hidden&&!document.hidden;
 function updateSubmit(){
  $('personalMotionGenerate').disabled=!engine?.ready||posting||!$('personalMotionPrompt').value.trim();
  $('personalMotionGenerate').querySelector('span').textContent=posting?'Submitting…':'Generate animation';
  $('personalMotionPromptCount').textContent=`${$('personalMotionPrompt').value.length} / 1000`;
 }
 function updateEngine(){
  const status=$('personalMotionEngine');status.classList.toggle('unavailable',loaded&&!engine?.ready);status.classList.toggle('ready',!!engine?.ready);
  $('personalMotionEngineLabel').textContent=loadError?'Library unavailable':!loaded?'Checking motion engine…':engine?.ready?(engine.label||'Motion engine ready'):'Motion generation unavailable';
  const message=loadError||engine?.message||'';
  $('personalMotionEngineDetail').textContent=message;$('personalMotionEngineDetail').hidden=!message;
  $('personalMotionRetry').hidden=!loadError&&!!engine?.ready;
  updateSubmit();
 }
 function populate(motion){
  $('personalAnimationComposer').open=true;
  $('personalMotionPrompt').value=motion.prompt||'';$('personalMotionName').value=motion.name||'';
  $('personalMotionDuration').value=motion.duration||5;$('personalMotionSeed').value=Number.isInteger(motion.seed)?motion.seed:'';
  updateDuration();updateSubmit();$('personalMotionPrompt').focus();$('personalAnimationComposer').scrollIntoView({block:'nearest',behavior:'smooth'});
 }
 function updateDuration(){$('personalMotionDurationValue').value=Number($('personalMotionDuration').value).toLocaleString('en-US')+' s';}
 async function transfer(motion){
  const target=getJob();if(!canAdd(target)||transferId||motion.state!=='done'||hasMotion(target,motion))return;
  transferId=motion.id;updateTarget();notice(`Adding “${motion.name}” to the selected model…`);
  try{
   const result=await applyMotion(target,motion);
   notice(result.ok?'Animation added. Your saved motion stays ready to reuse.':result.error,!result.ok);
  }catch(error){notice(error.message,true);}
  finally{transferId=null;updateTarget();}
 }
 function makeCard(motion){
  const card=text('article','animation-card personal-motion-card','');card.dataset.animationId=motion.id;
  const preview=text('div','motion-preview personal-motion-preview',''),chip=text('span','motion-chip','');preview.append(icon('motion'),chip);
  const body=text('div','personal-motion-card-body',''),title=text('h3','',''),prompt=text('p','personal-motion-prompt','');
  const meta=text('div','personal-motion-meta',''),stage=text('p','personal-motion-stage','');stage.setAttribute('role','status');
  const progress=document.createElement('progress');progress.max=100;progress.setAttribute('aria-label','Animation generation progress');
  const actions=text('div','personal-motion-actions',''),add=text('button','primary',''),secondary=text('button','quiet personal-motion-secondary','');
  add.type=secondary.type='button';add.append(icon('plus'),document.createTextNode('Add to model'));actions.append(add,secondary);body.append(title,prompt,meta,stage,progress,actions);card.append(preview,body);
  const entry={card,preview,chip,title,prompt,meta,stage,progress,add,secondary,motion,previewUrl:null,release:null};
  add.onclick=()=>transfer(entry.motion);
  secondary.onclick=async()=>{
   const current=entry.motion;
   if(!activeStates.has(current.state)){populate(current);return;}
   secondary.disabled=true;
   try{await api(`/api/my-animations/${encodeURIComponent(current.id)}/cancel`,{method:'POST'});await reload();}
   catch(error){notice(error.message,true);}
   finally{secondary.disabled=false;}
  };
  cards.set(motion.id,entry);return entry;
 }
 function render(){
  const matching=items.filter(motion=>`${motion.name} ${motion.prompt}`.toLocaleLowerCase('en').includes(filter));
  for(const [id,entry] of cards)if(!matching.some(motion=>motion.id===id)){entry.release?.();entry.card.remove();cards.delete(id);}
  host.querySelector('.personal-motion-empty')?.remove();
  for(const [index,motion] of matching.entries()){
   const entry=cards.get(motion.id)||makeCard(motion);entry.motion=motion;
   entry.card.dataset.state=motion.state;entry.title.textContent=motion.name||'Untitled motion';entry.title.title=motion.name||'';entry.prompt.textContent=motion.prompt||'';entry.prompt.title=motion.prompt||'';
   entry.chip.textContent=motion.state==='done'?(motion.preview_url?'GENERATED · 3D':'GENERATED'):labelState(motion.state).toUpperCase();
   entry.meta.textContent=[Number.isFinite(motion.duration)?`${motion.duration.toLocaleString('en-US')} s`:null,Number.isFinite(motion.fps)?`${motion.fps} fps`:null].filter(Boolean).join(' · ');
   entry.stage.textContent=motion.error||((activeStates.has(motion.state)||motion.state==='cancelled')?motion.stage||labelState(motion.state):'');entry.stage.hidden=!entry.stage.textContent;
   entry.progress.hidden=!activeStates.has(motion.state);if(Number.isFinite(motion.progress)&&motion.progress>0)entry.progress.value=motion.progress;else entry.progress.removeAttribute('value');
   entry.add.hidden=motion.state!=='done';entry.secondary.textContent=activeStates.has(motion.state)?'Cancel generation':'Use prompt';
   if(motion.state==='done'&&motion.preview_url&&entry.previewUrl!==motion.preview_url){
    entry.release?.();entry.preview.querySelectorAll('canvas,.personal-preview-toggle').forEach(el=>el.remove());entry.previewUrl=motion.preview_url;delete entry.preview.dataset.error;
    previews??=createPersonalMotionPreviews();entry.release=previews.attach(entry.preview,motion);
   }
   if(motion.state==='done'&&!motion.preview_url)entry.preview.dataset.error='Preview unavailable';
   entry.preview.classList.toggle('personal-preview-pending',motion.state!=='done');
   const current=host.children[index];if(current!==entry.card)host.insertBefore(entry.card,current||null);
  }
  if(!matching.length){
   const empty=text('div','personal-motion-empty','');empty.append(icon(loaded?'motion':'rotate'));
   empty.append(text('h3','',!loaded?'Loading your library…':loadError?'Your library could not be loaded':filter?'No matching animations':'Your first motion starts here'));
   empty.append(text('p','',loadError?'Retry the connection to see your saved motions.':filter?'Try another name or movement.':'Describe an action above. Each generated motion stays here, ready for another character.'));
   host.append(empty);
  }
  $('animationAvailableCount').textContent=`${matching.length} ${matching.length===1?'motion':'motions'}`;onCount(items.length);updateTarget();
 }
 function updateTarget(){
  const target=getJob(),allowed=canAdd(target)&&!transferId;
  for(const entry of cards.values()){
   const present=hasMotion(target,entry.motion),adding=transferId===entry.motion.id;
   entry.add.disabled=!allowed||present;entry.add.title=present?'This animation is already on the selected model':!target?'Select a rigged model to add this motion':!canAdd(target)?'A completed rigged model is required':'Add this animation to the selected model';
   entry.add.replaceChildren(icon(adding?'rotate':present?'check':'plus'),document.createTextNode(adding?'Adding…':present?'Added':'Add to model'));
  }
 }
 function schedule(){clearTimeout(pollTimer);pollTimer=0;if(inView())pollTimer=setTimeout(reload,items.some(motion=>activeStates.has(motion.state))?1800:10000);}
 async function reload(){
  if(loading){reloadAgain=true;return;}loading=true;$('personalMotionRefresh').disabled=true;
  try{
   const data=await api('/api/my-animations',{cache:'no-store'});
   const firstLoad=!loaded;
   items=Array.isArray(data.animations)?data.animations:[];engine=data.engine||{ready:false};loaded=true;loadError='';
   if(firstLoad&&!items.length)$('personalAnimationComposer').open=true;
   const slider=$('personalMotionDuration');slider.min=data.min_duration??2;slider.max=data.max_duration??10;slider.step=data.step??.5;
   $('personalMotionMinDuration').textContent=slider.min+' seconds';$('personalMotionMaxDuration').textContent=slider.max+' seconds';updateDuration();
  }catch(error){loaded=true;loadError=error.message;engine={ready:false};}
  finally{loading=false;$('personalMotionRefresh').disabled=false;updateEngine();if(visible)render();schedule();if(reloadAgain){reloadAgain=false;queueMicrotask(reload);}}
 }
 $('personalMotionForm').onsubmit=async event=>{
  event.preventDefault();if(posting||!engine?.ready||!$('personalMotionForm').reportValidity())return;
  const prompt=$('personalMotionPrompt').value.trim();if(!prompt)return;
  const payload={prompt,duration:Number($('personalMotionDuration').value)};
  const name=$('personalMotionName').value.trim(),seed=$('personalMotionSeed').value;if(name)payload.name=name;if(seed!=='')payload.seed=Number(seed);
  posting=true;updateSubmit();notice('Submitting your movement…');
  try{await api('/api/my-animations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});$('personalAnimationComposer').open=false;notice('Animation queued. You can keep working while it generates.');await reload();}
  catch(error){notice(error.message,true);}
  finally{posting=false;updateSubmit();}
 };
 $('personalMotionPrompt').oninput=updateSubmit;$('personalMotionDuration').oninput=updateDuration;
 $('personalMotionRetry').onclick=reload;$('personalMotionRefresh').onclick=reload;
 for(const button of document.querySelectorAll('[data-motion-example]')){for(const existing of button.querySelectorAll('svg.ui-icon'))existing.remove();button.prepend(icon('motion'));button.onclick=()=>{$('personalMotionPrompt').value=button.dataset.motionExample;updateSubmit();$('personalMotionPrompt').focus();};}
 const onVisibility=()=>{previews?.setActive(inView());if(inView())reload();else{clearTimeout(pollTimer);pollTimer=0;}};
 new MutationObserver(onVisibility).observe($('rigPanel'),{attributes:true,attributeFilter:['hidden']});document.addEventListener('visibilitychange',onVisibility);
 updateSubmit();
 return {
  setVisible(value,query=''){visible=value;filter=query;previews?.setActive(inView());if(value){render();if(!loaded)reload();else schedule();}else{clearTimeout(pollTimer);pollTimer=0;}},
  search(query){filter=query;if(visible)render();},findClip(name){return items.find(motion=>motion.clip_name===name);},updateTarget,reload,
 };
}
