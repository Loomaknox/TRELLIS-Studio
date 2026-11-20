import {localizeStatic,t} from './i18n.js';
/** A reference projection while computing; never a fabricated intermediate mesh. */
export function createGenerationWait(viewport,{getMode,setMode}={}){
  const layer=document.createElement('section');
  layer.className='generation-wait';layer.hidden=true;
  layer.setAttribute('aria-label',t('Computation progress'));
  layer.innerHTML=`<div class="generation-projection" aria-hidden="true">
    <div class="generation-projection-halo"></div><div class="generation-projection-plane">
      <img alt=""><svg class="generation-projection-placeholder" viewBox="0 0 100 100" fill="none" stroke="currentColor" stroke-width="1"><path d="M50 10 85 30v40L50 90 15 70V30ZM15 30l35 20 35-20M50 50v40M50 10v40"/><path opacity=".3" d="M32 20v60m36-60v60M15 50l35 20 35-20"/></svg>
      <div class="generation-projection-scan"></div><i class="generation-projection-corner c1"></i><i class="generation-projection-corner c2"></i><i class="generation-projection-corner c3"></i><i class="generation-projection-corner c4"></i>
    </div><svg class="generation-projection-beams" viewBox="0 0 420 360" preserveAspectRatio="none"><path d="M42 345 96 52M42 345 324 52M378 345 96 52M378 345 324 52"/></svg>
    <span class="generation-projection-label">REFERENCE PROJECTION</span>
  </div><div class="generation-wait-card"><div class="generation-wait-heading"><span class="generation-wait-eyebrow"><i></i><span>LOCAL CREATION</span></span><span class="generation-wait-percent"></span></div><h3></h3><p class="generation-wait-stage" role="status" aria-live="polite"></p><div class="generation-wait-track" role="progressbar" aria-label="Computation progress" aria-valuemin="0" aria-valuemax="100"><span></span></div><p class="generation-wait-hint"></p></div>`;
  localizeStatic(layer);
  viewport.append(layer);
  const image=layer.querySelector('img'),title=layer.querySelector('h3'),stage=layer.querySelector('.generation-wait-stage');
  const hint=layer.querySelector('.generation-wait-hint'),percent=layer.querySelector('.generation-wait-percent'),track=layer.querySelector('.generation-wait-track');
  const eyebrow=layer.querySelector('.generation-wait-eyebrow>span'),projectionLabel=layer.querySelector('.generation-projection-label');
  let projectionUrl='',attemptKey='',owner=null,restoreMode=null,suppressed=null;
  image.onload=()=>{layer.classList.add('has-reference');projectionLabel.textContent=t('REFERENCE PROJECTION');};
  image.onerror=()=>{layer.classList.remove('has-reference');projectionLabel.textContent=t('PREPARING YOUR PREVIEW');};
  function restore(){if(restoreMode!==null&&getMode?.()==='hologram')setMode?.(restoreMode);restoreMode=null;owner=null;}
  function update(job,{hasModel=false,referenceUrl=''}={}){
    const active=job&&['queued','running'].includes(job.state);
    if(owner&&(!active||owner!==job.id||!hasModel))restore();
    layer.hidden=!active;viewport.classList.toggle('has-generation-wait',!!active);
    if(!active){suppressed=null;return;}
    const queued=job.state==='queued';
    layer.classList.toggle('is-queued',queued);layer.classList.toggle('is-compact',hasModel);
    if(hasModel&&!queued&&!owner&&suppressed!==job.id&&getMode&&setMode){owner=job.id;restoreMode=getMode();setMode('hologram');}
    const nextAttempt=job.id+':'+job.state+':'+String(job.stage||'');
    if(referenceUrl!==projectionUrl||(!layer.classList.contains('has-reference')&&nextAttempt!==attemptKey)){
      attemptKey=nextAttempt;projectionUrl=referenceUrl;layer.classList.remove('has-reference');
      projectionLabel.textContent=t('PREPARING YOUR PREVIEW');
      if(referenceUrl)image.src=referenceUrl+(referenceUrl.includes('?')?'&':'?')+'stage='+encodeURIComponent(job.stage||job.state);
      else image.removeAttribute('src');
    }
    const sourceKind=job.settings?.source_kind||'';
    const generating=!['import','rig','animation','animation_copy','generated_animation','refinish'].includes(sourceKind)&&!job.operation;
    title.textContent=queued?t('Ready for its turn'):generating?t('Creating your model'):t('Preparing your model');
    eyebrow.textContent=queued?t('IN THE QUEUE'):hasModel?t('MODEL IN PROGRESS'):t('LOCAL CREATION');
    const nextStage=queued?t('Waiting for the current computation to finish.'):t(job.stage||'Processing your model…');
    if(stage.textContent!==nextStage)stage.textContent=nextStage;
    const progress=Number(job.progress),determinate=!queued&&Number.isFinite(progress)&&progress>=0;
    percent.textContent=determinate?Math.min(100,Math.round(progress))+'%':queued?t('Queued'):'';
    if(determinate){track.setAttribute('aria-valuenow',String(Math.max(0,Math.min(100,progress))));track.firstElementChild.style.width=Math.max(1,Math.min(100,progress))+'%';}
    else{track.removeAttribute('aria-valuenow');track.firstElementChild.style.width='0%';}
    hint.textContent=hasModel?t('Your source remains available. The result opens when ready.'):queued?t('You can keep exploring your collection.'):t('Your 3D preview will appear when the model is ready.');
  }
  return {update,userModeChanged(){if(owner){suppressed=owner;owner=null;restoreMode=null;}},dispose(){restore();viewport.classList.remove('has-generation-wait');layer.remove();}};
}
