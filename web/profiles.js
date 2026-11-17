// Recipes are persisted by the local server, independently from object history.
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
  studio_768:'Studio 768 · Rebuilds the surface and retains fine details.',
  wtivo_1024:'WTiVo 1024 · Prioritizes closing surface gaps.',
  direct:'Adaptive reduction within the triangle ceiling.',
  repair:'Fills small gaps while retaining the source for variants.',
};
const number=new Intl.NumberFormat('en-US');
const inlineFinishingLimit=3000000;
export async function createProfileControls(advanced,{changed=()=>{},usePixal=()=>false,describeMethod=()=>''}={}){
  let profiles=[],selected=null,saving=false,edit=false,sourceRequired=false,previousKeep=false;
  let repairSupported=false, hdSupported=false, masterSupport={};
  let startupProfile='';
  const readFinishing=()=>$('preset').value==='dense_master'
    ? $('advancedMasterFinishing').value || $('denseMasterFinishing').value : '';
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
    return {resolution:usePixal()?1024:recipe.resolution,triangles:recipe.triangles,texture_size:recipe.texture_size};
  }
  function resolved(s){const copy=structuredClone(s);for(const key of ['structure_steps','shape_steps','texture_steps'])if(copy.advanced[key]===0)copy.advanced[key]=steps[copy.preset];return copy;}
  const equal=(a,b)=>{const x=resolved(a),y=resolved(b);return Object.keys(x).every(k=>k==='advanced'?Object.keys(x[k]).every(f=>x[k][f]===y[k][f]):x[k]===y[k]);};
  function sync(){
    if(!selected)return;
    const activePreset=$('preset').value;
    const experimental=activePreset==='humanoid_experimental', dense=activePreset==='dense_master';
    const requiresSource=experimental||dense;
    if(requiresSource!==sourceRequired){
      if(requiresSource){previousKeep=$('keepFinishingSource').checked;$('keepFinishingSource').checked=true;}
      else $('keepFinishingSource').checked=previousKeep;
      sourceRequired=requiresSource;
    }
    $('keepFinishingSource').disabled=requiresSource;
    $('denseMasterRepairField').hidden=!dense;
    $('advancedMasterField').hidden=!dense;
    const finishing = $('denseMasterFinishing');
    const override = $('advancedMasterFinishing');
    const actual = budget();
    finishing.hidden = !!override.value;
    finishing.disabled = !dense||finishing.hidden;
    override.disabled = !dense;
    $('masterFinishingOverride').hidden=!override.value;
    $('masterFinishingOverrideLabel').textContent=finishingNames[override.value]||'';
    override.querySelector('[value="repair"]').disabled = !repairSupported;
    for (const option of finishing.options) {
      const info=masterSupport[option.value];
      option.disabled=actual.resolution<1024||!(info?.available??(option.value==='studio_768'&&hdSupported));
      option.textContent=finishingNames[option.value]+(option.value==='wtivo_1024'&&option.disabled?' · Unavailable':'');
      option.title=option.disabled ? info?.reason || 'Requires 1024 or higher generation resolution.' : '';
    }
    const selectedFinish=readFinishing();
    const selectedSupport=masterSupport[selectedFinish];
    const reconstruction=selectedFinish==='studio_768'||selectedFinish==='wtivo_1024';
    $('triangles').max=String(reconstruction?inlineFinishingLimit:8000000);
    let hint=finishingDetails[selectedFinish]||'';
    if (reconstruction&&finishing.selectedOptions[0]?.disabled) {
      hint=actual.resolution<1024
        ? 'Choose 1024 or higher generation resolution in Advanced.'
        : selectedSupport?.reason || 'This reconstruction is unavailable.';
    } else if (reconstruction&&actual.triangles>inlineFinishingLimit) {
      hint='Set the triangle ceiling to 3,000,000 or less in Advanced.';
    }
    $('denseMasterFinishingHint').textContent=hint;
    $('finishingSourceHelp').hidden=requiresSource;
    const recipe=read(),dirty=!equal(recipe,selected.settings);
    $('profileId').value=recipe.preset===selected.settings.preset?selected.id||selected.sourceProfile||'':'';
    $('profileState').textContent=dirty?'MODIFIED':selected.variant?'VARIANT':selected.experimental?'EXPERIMENTAL':'';
    $('profileState').hidden=!$('profileState').textContent;
    $('profileState').classList.toggle('dirty',dirty);
    $('profileSummary').textContent=`${actual.resolution}³ · ${dense?'Up to ':''}${number.format(actual.triangles)} triangles · ${actual.texture_size/1024}K textures`;
    $('monoTrianglesLabel').textContent=dense?'Maximum triangles':'Target triangles';
    $('monoTrianglesHint').textContent=reconstruction?'Up to 3,000,000. 0 uses the profile ceiling.'
      : dense?'0 uses the profile ceiling.':'0 uses the profile target.';
    const caption=selected.variant?'Model settings':profileNames[selected.id]||selected.name;
    $('generationSummary').textContent=[caption,describeMethod(),finishingNames[selectedFinish]].filter(Boolean).join(' · ');
    $('updateProfile').hidden=selected.builtin;
    const startup=$('useProfileAtStartup');
    const isStartup=selected.id===startupProfile;
    startup.disabled=!selected.id||dirty||isStartup;
    startup.setAttribute('aria-pressed',String(isStartup));
    startup.textContent=isStartup?'Startup profile':'Use at startup';
    if(![...$('profileBase').options].some(o=>o.value===recipe.preset)){const option=document.createElement('option');option.value=recipe.preset;option.textContent='Historical settings';$('profileBase').append(option);}$('profileBase').value=recipe.preset;
    changed();
  }
  function apply(id){
    selected=profiles.find(p=>p.id===id);if(!selected)return;
    $('profileChoice').querySelector('[data-variant]')?.remove();
    const s=selected.settings;
    $('denseMasterFinishing').value='studio_768';
    $('advancedMasterFinishing').value='';
    for(const [key,value] of Object.entries({preset:s.preset,resolution:s.resolution,triangles:s.triangles,textureSize:s.texture_size}))$(key).value=String(value);
    const textureSeed=advanced.read().texture_seed;
    $('removeBg').checked=s.remove_bg;advanced.apply({...s.advanced,texture_seed:textureSeed});
    $('profileChoice').value=id;$('profileId').value=id;
    if(s.preset==='humanoid_experimental')$('assetType').value='humanoid';
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
  $('denseMasterFinishing').addEventListener('change',()=>{$('advancedMasterFinishing').value='';sync();});
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
        body:JSON.stringify({name:$('profileName').value,settings:read()})});
      const data=await request('/api/profiles');profiles=data.profiles;options();apply(profile.id);
      $('profileDialog').close();$('profileNotice').textContent='Profile saved on this computer.';
    }catch(e){$('profileDialogError').textContent=e.message;}
    finally{saving=false;$('confirmProfile').disabled=false;}
  };
  return {sync,reset:()=>apply('game_d'),
    setFinishingCapabilities(available, hdAvailable, methods){
      const supported=methods||{};
      if(repairSupported===available&&hdSupported===hdAvailable&&JSON.stringify(masterSupport)===JSON.stringify(supported))return;
      repairSupported=available;
      hdSupported=hdAvailable;
      masterSupport=supported;
      sync();
    },
    appendFinishing(form){
      const value=readFinishing();
      if (value==='repair') form.set('repair_surface','true');
      if (value==='wtivo_1024'||(value==='studio_768'&&masterSupport.studio_768?.available)) {
        form.set('master_finishing',value);
      } else if (value==='studio_768') form.set('hd_reconstruction','true');
    },
    restoreFinishing(settings){
      $('denseMasterFinishing').value=settings.master_finishing==='wtivo_1024'?'wtivo_1024':'studio_768';
      $('advancedMasterFinishing').value=settings.master_finishing||settings.hd_reconstruction
        ? '' : settings.repair_surface ? 'repair' : 'direct';
    },
    budget,
    get finishingReady(){
      const value=readFinishing();
      if (value==='repair') return repairSupported;
      if (!value||value==='direct') return true;
      return !$('denseMasterFinishing').selectedOptions[0]?.disabled&&budget().triangles<=inlineFinishingLimit;
    },
    restoreSource(value){sourceRequired=false;previousKeep=!!value;$('keepFinishingSource').checked=!!value;sync();},
    detach(sourceProfile){
      const matchingProfile=profiles.find(profile=>profile.id===sourceProfile&&profile.settings.preset===$('preset').value);
      selected={id:'',name:'Variant',builtin:true,variant:true,settings:read(),sourceProfile:matchingProfile?.id};
      $('profileChoice').querySelector('[data-variant]')?.remove();
      const option=document.createElement('option');option.value='';option.textContent='This model’s settings';option.disabled=true;option.dataset.variant='true';$('profileChoice').append(option);$('profileChoice').value='';
      sync();$('profileNotice').textContent='Model settings restored. Save a copy to create a profile.';
    },
    get ready(){return profiles.length>0;}};
}
