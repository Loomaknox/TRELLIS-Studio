// Recipes are persisted by the local server, independently from object history.
import {detailRefinements} from './hd-master-finishing.js?v=detail-refinement-native';
import {optionHelp} from './advanced-controls.js?v=detail-study';

const $=id=>document.getElementById(id);
const steps={game_d:20,high_detail:20,humanoid_experimental:20,dense_master:20,fast:8,balanced:12,detail:20};
const startupKey='trellis.studio.startup-profile';
const profileNames={game_d:'Game Asset',dense_master:'HD Master'};
const finishingNames={
  studio_768:'Balanced Reconstruction',
  wtivo_1024:'Surface Closure',
  direct:'Direct Export',
  repair:'Repair Holes',
};
const finishingDetails={
  '':'Uses the profile’s standard mesh processing.',
  studio_768:'Studio 768 · Rebuilds the surface and retains fine details.',
  wtivo_1024:'WTiVo 1024 · Prioritizes closing surface gaps.',
  direct:'Adaptive reduction within the triangle ceiling.',
  repair:'Fills small gaps while retaining the source for variants.',
};
const finishingName=value=>detailRefinements[value]?.name||finishingNames[value];
const defaultFinishing=preset=>preset==='dense_master'?'studio_768':'';
const isReconstruction=value=>Boolean(detailRefinements[value])||value==='studio_768'||value==='wtivo_1024';
const number=new Intl.NumberFormat('en-US');
const inlineFinishingLimit=3000000;
const detailRefinementLimit=1000000;
const detailSourceResolutions=[512,1024,1536];
const retextureHelp='Generates new PBR materials from the reference on the refined geometry. Uses the texture settings below and adds processing time.';
export async function createProfileControls(advanced,{changed=()=>{},usePixal=()=>false,describeMethod=()=>'',useNativeMethod=()=>{}}={}){
  let profiles=[],selected=null,saving=false,edit=false,sourceRequired=false,previousKeep=false;
  let repairSupported=false, hdSupported=false, masterSupport={};
  let detailTexturing={};
  let startupProfile='', refinementInputs=null, standardFinishing='', pixalFallback=false, pixalAtlas=null;
  const retexture=$('retextureAfterRefinement');
  const retextureField=$('detailTexturingField');
  const retextureStatus=$('detailTexturingStatus');
  optionHelp(retexture.closest('label'), 'Retexture after Hi3D', retextureHelp);
  const textures=advanced.group('texture');
  if(textures)textures.querySelector('.option-grid').prepend(retextureField);
  const readFinishing=()=>$('preset').value==='dense_master'&&$('advancedMasterFinishing').value
    || $('denseMasterFinishing').value;
  const retextureEligible=()=>!usePixal()&&readFinishing()==='hi3d_1024'&&Number($('resolution').value)===1024;
  const wantsRetexture=()=>retextureEligible()&&retexture.checked;
  function read(){
    const {texture_seed,...options}=advanced.read();
    const preset=$('preset').value;
    const defaults=selected?.settings.preset===preset ? selected.settings : null;
    return {
      preset,resolution:Number($('resolution').value),
      triangles:Number($('triangles').value)||defaults?.triangles||
        ({game_d:28000,high_detail:250000,humanoid_experimental:250000,dense_master:1200000,
          character_pixal:28000,fast:25000,balanced:50000,detail:100000}[preset]),
      texture_size:Number($('textureSize').value)||defaults?.texture_size||(preset==='fast'?1024:2048),
      remove_bg:$('removeBg').checked,advanced:options,
    };
  }
  function budget(recipe=read()){
    const triangles=detailRefinements[readFinishing()]?Math.min(recipe.triangles,detailRefinementLimit):recipe.triangles;
    return {resolution:usePixal()?1024:recipe.resolution,triangles,texture_size:recipe.texture_size};
  }
  function syncRefinementBudget(active){
    const triangles=$('triangles');
    if(active){
      if(!refinementInputs){
        const exceedsLimit=Number(triangles.value)>detailRefinementLimit;
        refinementInputs={triangles:exceedsLimit?triangles.value:null};
        if(exceedsLimit)triangles.value=String(detailRefinementLimit);
      }
    }else if(refinementInputs){
      if(refinementInputs.triangles!==null)triangles.value=refinementInputs.triangles;
      refinementInputs=null;
    }
    triangles.placeholder=active?number.format(detailRefinementLimit):'';
  }
  function profileRecipe(recipe=read()){
    const finishing=readFinishing();
    if(isReconstruction(finishing)&&(finishing!=='studio_768'||recipe.resolution>=1024)){
      recipe={...recipe,triangles:budget(recipe).triangles,master_finishing:finishing};
    }
    if(finishing==='hi3d_1024')recipe={...recipe,retexture_after_refinement:wantsRetexture()};
    return recipe;
  }
  function resolved(s){
    const copy=structuredClone(s);
    for(const key of ['structure_steps','shape_steps','texture_steps'])if(copy.advanced[key]===0)copy.advanced[key]=steps[copy.preset];
    copy.master_finishing=copy.master_finishing||defaultFinishing(copy.preset);
    if(detailRefinements[copy.master_finishing])copy.triangles=Math.min(copy.triangles,detailRefinementLimit);
    copy.retexture_after_refinement=copy.retexture_after_refinement===true;
    return copy;
  }
  const equal=(a,b)=>{const x=resolved(a),y=resolved(b);return Object.keys(x).every(k=>k==='advanced'?Object.keys(x[k]).every(f=>x[k][f]===y[k][f]):x[k]===y[k]);};
  function sync(){
    if(!selected)return;
    const activePreset=$('preset').value;
    const experimental=activePreset==='humanoid_experimental', dense=activePreset==='dense_master';
    const finishing=$('denseMasterFinishing');
    const override=$('advancedMasterFinishing');
    if(!dense)override.value='';
    if(dense&&!finishing.value)finishing.value=defaultFinishing(activePreset);
    if(usePixal()&&detailRefinements[finishing.value]){
      finishing.value=standardFinishing||defaultFinishing(activePreset);
      pixalFallback=true;
    }else if(!usePixal()){
      pixalFallback=false;
    }
    const selectedFinish=readFinishing();
    const detail=detailRefinements[selectedFinish];
    const reconstruction=isReconstruction(selectedFinish);
    const requiresSource=experimental||dense||reconstruction;
    if(requiresSource!==sourceRequired){
      if(requiresSource){previousKeep=$('keepFinishingSource').checked;$('keepFinishingSource').checked=true;}
      else $('keepFinishingSource').checked=previousKeep;
      sourceRequired=requiresSource;
    }
    $('keepFinishingSource').disabled=requiresSource;
    $('denseMasterRepairField').hidden=false;
    $('advancedMasterField').hidden=!dense;
    const detailGroup=advanced.group('hi3d');
    if(detailGroup)detailGroup.hidden=!detail;
    retextureField.hidden=selectedFinish!=='hi3d_1024';
    retexture.disabled=!retextureEligible();
    retextureStatus.textContent=retexture.disabled
      ? 'Choose 1024³ for the 3D resolution to use this option.'
      : detailTexturing.available!==true ? detailTexturing.reason||'The local texturing pipeline is unavailable.' : '';
    retextureStatus.hidden=!retextureStatus.textContent;
    syncRefinementBudget(Boolean(detail));
    const textureSize=$('textureSize');
    if(usePixal()&&read().texture_size===4096){
      pixalAtlas=textureSize.value;
      textureSize.value='2048';
    }else if(!usePixal()&&pixalAtlas!==null){
      if(textureSize.value==='2048')textureSize.value=pixalAtlas;
      pixalAtlas=null;
    }
    const recipe=read();
    const actual = budget(recipe);
    const sourceOption=$('resolution').selectedOptions[0];
    const detailSourceSupported=detailSourceResolutions.includes(actual.resolution)&&sourceOption&&!sourceOption.disabled;
    const detailSourceReason=usePixal()?'Choose TRELLIS.2 · Single image.'
      : detailSourceSupported?'':'Choose a supported 3D resolution in Advanced.';
    finishing.hidden = !!override.value;
    finishing.disabled = finishing.hidden;
    override.disabled = !dense;
    $('masterFinishingOverride').hidden=!override.value;
    $('masterFinishingOverrideLabel').textContent=finishingName(override.value)||'';
    override.querySelector('[value="repair"]').disabled = !repairSupported;
    for (const option of finishing.options) {
      if(!option.value){
        option.disabled=option.hidden=dense;
        continue;
      }
      const info=masterSupport[option.value];
      if(detailRefinements[option.value]){
        option.disabled=!!detailSourceReason||info?.available!==true;
        option.title=option.disabled
          ? detailSourceReason||info?.reason||'Requires the Hi3D runtime.'
          : detailRefinements[option.value].detail;
      }else{
        option.disabled=actual.resolution<1024||!(info?.available??(dense&&option.value==='studio_768'&&hdSupported));
        option.textContent=finishingName(option.value)+(option.value==='wtivo_1024'&&option.disabled?' · Unavailable':'');
        option.title=option.disabled ? info?.reason || 'Requires 1024 or higher generation resolution.' : '';
      }
    }
    const selectedSupport=masterSupport[selectedFinish];
    const ceiling=detail?detailRefinementLimit:inlineFinishingLimit;
    const requestedTriangles=detail?Number($('triangles').value):recipe.triangles;
    $('triangles').max=String(reconstruction?ceiling:8000000);
    let hint=detail?.detail||finishingDetails[selectedFinish]||'';
    if (reconstruction&&finishing.selectedOptions[0]?.disabled) {
      hint=detail ? finishing.selectedOptions[0].title
        : actual.resolution<1024
        ? 'Choose 1024 or higher generation resolution in Advanced.'
        : selectedSupport?.reason || 'This reconstruction is unavailable.';
    } else if (reconstruction&&requestedTriangles>ceiling) {
      hint=`Set the triangle ceiling to ${number.format(ceiling)} or less in Advanced.`;
    } else if(detail&&!$('removeBg').checked){
      hint+=' Use a transparent reference or enable background removal.';
    }
    if(wantsRetexture()){
      hint+=' '+(retextureStatus.textContent||'A separate texture pass follows refinement.');
    }
    if(pixalFallback)hint+=' Hi3D requires TRELLIS.2 · Single image. This generation will use the finishing shown above.';
    if(pixalAtlas!==null&&textureSize.value==='2048')hint+=' Pixal3D uses a 2K atlas for this recipe.';
    $('denseMasterFinishingHint').textContent=hint;
    $('detailRefinementSource').hidden=!detail;
    if(detail){
      $('detailRefinementNativeResolution').textContent=`${actual.resolution}³`;
      $('detailRefinementPassResolution').textContent=`${detail.resolution}³`;
    }
    const detailOptions=Object.keys(detailRefinements).map(value=>finishing.querySelector(`[value="${value}"]`));
    const unavailable=$('detailRefinementUnavailable');
    unavailable.hidden=!!detail||finishing.hidden||!masterSupport.hi3d_512||!detailOptions.every(option=>option.disabled);
    unavailable.textContent=unavailable.hidden?'':detailOptions[0].title;
    $('finishingSourceHelp').hidden=requiresSource;
    const dirty=Boolean(override.value&&!selected.variant)||!equal(profileRecipe(recipe),selected.settings);
    $('profileId').value=recipe.preset===selected.settings.preset?selected.id||selected.sourceProfile||'':'';
    $('profileState').textContent=dirty?'MODIFIED':selected.variant?'VARIANT':selected.experimental?'EXPERIMENTAL':'';
    $('profileState').hidden=!$('profileState').textContent;
    $('profileState').classList.toggle('dirty',dirty);
    $('profileSummary').textContent=`${actual.resolution}³ · ${dense||reconstruction?'Up to ':''}${number.format(actual.triangles)} triangles · ${actual.texture_size/1024}K textures`;
    $('monoTrianglesLabel').textContent=dense||reconstruction?'Maximum triangles':'Target triangles';
    $('monoTrianglesHint').textContent=detail?'0 uses the profile ceiling, capped at 1,000,000.'
      : reconstruction?'Up to 3,000,000. 0 uses the profile ceiling.'
      : dense?'0 uses the profile ceiling.':'0 uses the profile target.';
    const caption=selected.variant?'Model settings':profileNames[selected.id]||selected.name;
    $('generationSummary').textContent=[caption,describeMethod(),detail?`${actual.resolution}³ source`:'',finishingName(selectedFinish)].filter(Boolean).join(' · ');
    $('updateProfile').hidden=selected.builtin;
    const startup=$('useProfileAtStartup');
    const isStartup=selected.id===startupProfile;
    startup.disabled=!selected.id||dirty||isStartup;
    startup.setAttribute('aria-pressed',String(isStartup));
    startup.textContent=isStartup?'Startup profile':'Use at startup';
    const profileBase=$('profileBase');
    for(const option of profileBase.querySelectorAll('[data-historical]'))if(option.value!==recipe.preset)option.remove();
    if(![...profileBase.options].some(option=>option.value===recipe.preset)){
      const option=document.createElement('option');
      option.value=recipe.preset;
      option.textContent='Historical settings';
      option.dataset.historical='true';
      profileBase.append(option);
    }
    profileBase.value=recipe.preset;
    changed();
  }
  function apply(id){
    selected=profiles.find(p=>p.id===id);if(!selected)return;
    $('profileChoice').querySelector('[data-variant]')?.remove();
    const s=selected.settings;
    refinementInputs=null;
    pixalFallback=false;
    pixalAtlas=null;
    standardFinishing=detailRefinements[s.master_finishing]?defaultFinishing(s.preset):s.master_finishing||defaultFinishing(s.preset);
    $('denseMasterFinishing').value=s.master_finishing||standardFinishing;
    $('advancedMasterFinishing').value='';
    retexture.checked=s.retexture_after_refinement===true;
    for(const [key,value] of Object.entries({preset:s.preset,resolution:s.resolution,triangles:s.triangles,textureSize:s.texture_size}))$(key).value=String(value);
    const textureSeed=advanced.read().texture_seed;
    $('removeBg').checked=s.remove_bg;advanced.apply({...s.advanced,texture_seed:textureSeed});
    $('profileChoice').value=id;$('profileId').value=id;
    if(s.preset==='humanoid_experimental')$('assetType').value='humanoid';
    if(detailRefinements[s.master_finishing])useNativeMethod();
    $('profileNotice').textContent='';sync();
  }
  async function request(url,options){const r=await fetch(url,options),data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Profiles unavailable.');return data;}
  function options(){
    $('profileChoice').replaceChildren();
    for(const builtin of [true,false]){
      const group=document.createElement('optgroup');group.label=builtin?'Built-in profiles':'My profiles';
      for(const p of profiles.filter(x=>x.builtin===builtin)){const o=document.createElement('option');o.value=p.id;o.textContent=p.builtin?profileNames[p.id]||p.name:p.name;group.append(o);}
      if(group.children.length)$('profileChoice').append(group);
    }
  }
  try{
    const data=await request('/api/profiles');profiles=data.profiles;
    let saved='';
    try{saved=localStorage.getItem(startupKey);}catch{}
    startupProfile=[saved,data.startup_profile,data.default_profile].find(id=>profiles.some(p=>p.id===id));
    options();apply(startupProfile);
    $('profileChoice').disabled=false;$('saveProfileAs').disabled=!advanced.ready;
  }catch(e){$('profileNotice').textContent=e.message+' Restart TRELLIS if needed.';}
  $('profileChoice').onchange=()=>apply($('profileChoice').value);
  $('useProfileAtStartup').onclick=()=>{
    try{
      localStorage.setItem(startupKey,selected.id);
      startupProfile=selected.id;
      $('profileNotice').textContent='Startup profile saved for this browser.';
      sync();
    }catch{
      $('profileNotice').textContent='This browser could not save the startup profile.';
    }
  };
  $('form').addEventListener('input',sync);$('form').addEventListener('change',sync);
  $('denseMasterFinishing').addEventListener('change',()=>{
    const method=$('denseMasterFinishing').value;
    pixalFallback=false;
    if(!detailRefinements[method])standardFinishing=method;
    $('advancedMasterFinishing').value='';
    sync();
  });
  $('clearMasterOverride').addEventListener('click',()=>{
    $('advancedMasterFinishing').value='';
    sync();
    $('denseMasterFinishing').focus();
  });
  $('profileBase').addEventListener('change',()=>{$('preset').value=$('profileBase').value;sync();});
  function show(update){if(!selected)return;edit=update;$('profileName').value=update?selected.name:'';$('profileDialogTitle').textContent=update?'Edit this profile':'Save a copy';$('profileDialogError').textContent='';$('profileDialog').showModal();$('profileName').focus();}
  $('saveProfileAs').onclick=()=>show(false);$('updateProfile').onclick=()=>show(true);
  $('closeProfile').onclick=()=>$('profileDialog').close();
  $('profileForm').onsubmit=async e=>{
    e.preventDefault();if(saving||!selected)return;
    const invalid=[...$('form').querySelectorAll('input[type=number]')].find(x=>!x.checkValidity());
    if(invalid){$('profileDialogError').textContent='Correct the numeric fields before saving the profile.';return;}
    saving=true;$('confirmProfile').disabled=true;
    try{
      const profile=await request(edit?`/api/profiles/${selected.id}`:'/api/profiles',{
        method:edit?'PUT':'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:$('profileName').value,settings:profileRecipe()})});
      const data=await request('/api/profiles');profiles=data.profiles;options();apply(profile.id);
      $('profileDialog').close();$('profileNotice').textContent='Profile saved on this computer.';
    }catch(e){$('profileDialogError').textContent=e.message;}
    finally{saving=false;$('confirmProfile').disabled=false;}
  };
  return {sync,reset:()=>apply('game_d'),
    setFinishingCapabilities(available, hdAvailable, methods, texturing){
      const supported=methods||{};
      const texturingSupport=texturing||{};
      if(repairSupported===available&&hdSupported===hdAvailable&&JSON.stringify(masterSupport)===JSON.stringify(supported)
        &&JSON.stringify(detailTexturing)===JSON.stringify(texturingSupport))return;
      repairSupported=available;
      hdSupported=hdAvailable;
      masterSupport=supported;
      detailTexturing=texturingSupport;
      sync();
    },
    appendFinishing(form){
      const value=readFinishing();
      if (value==='repair') form.set('repair_surface','true');
      if (detailRefinements[value]||value==='wtivo_1024'||(value==='studio_768'&&masterSupport.studio_768?.available)) {
        form.set('master_finishing',value);
      } else if (value==='studio_768') form.set('hd_reconstruction','true');
      if(!usePixal()&&(value==='hi3d_1024'||selected?.settings.retexture_after_refinement)){
        form.set('retexture_after_refinement', String(wantsRetexture()));
      }
    },
    restoreFinishing(settings){
      refinementInputs=null;
      pixalFallback=false;
      pixalAtlas=null;
      const method=settings.master_finishing||(settings.hd_reconstruction?'studio_768':defaultFinishing(settings.preset));
      standardFinishing=detailRefinements[method]?defaultFinishing(settings.preset):method;
      $('denseMasterFinishing').value=method;
      $('advancedMasterFinishing').value=settings.preset!=='dense_master'||settings.master_finishing||settings.hd_reconstruction
        ? '' : settings.repair_surface ? 'repair' : 'direct';
      retexture.checked=settings.retexture_after_refinement===true;
    },
    budget,
    get finishingReady(){
      const value=readFinishing();
      if (value==='repair') return repairSupported;
      if (!value||value==='direct') return true;
      const withinLimit=detailRefinements[value]?Number($('triangles').value)<=detailRefinementLimit
        : budget().triangles<=inlineFinishingLimit;
      return !$('denseMasterFinishing').selectedOptions[0]?.disabled&&withinLimit
        &&(!wantsRetexture()||detailTexturing.available===true);
    },
    restoreSource(value){sourceRequired=false;previousKeep=!!value;$('keepFinishingSource').checked=!!value;sync();},
    detach(sourceProfile){
      const matchingProfile=profiles.find(profile=>profile.id===sourceProfile&&profile.settings.preset===$('preset').value);
      selected={id:'',name:'Variant',builtin:true,variant:true,settings:profileRecipe(),sourceProfile:matchingProfile?.id};
      $('profileChoice').querySelector('[data-variant]')?.remove();
      const option=document.createElement('option');option.value='';option.textContent='This model’s settings';option.disabled=true;option.dataset.variant='true';$('profileChoice').append(option);$('profileChoice').value='';
      sync();$('profileNotice').textContent='Model settings restored. Save a copy to create a profile.';
    },
    get ready(){return profiles.length>0;}};
}
