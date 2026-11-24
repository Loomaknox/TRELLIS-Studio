import {formatLocale, t} from './i18n.js';
import {button,dialog,el,field,input,select,action} from './workbench-ui.js?v=3.4.0';
export function createCollectionTransfer({api,getRecords,getSelection,workspace,exports,refresh}){
 const ui=dialog('transferDialog',t('Back up & transfer'),t('YOUR COLLECTION, ANYWHERE'),t('Keep models, reference images, recipes, embedded animations and library details together.'),'transfer-dialog');const tabs=el('div','wb-tabs'),backup=button(t('Create backup'),'download','active'),restore=button(t('Restore archive'),'import');tabs.append(backup,restore);const out=el('section'),incoming=el('section');incoming.hidden=true;ui.body.append(tabs,out,incoming);const scope=select([['folder',t('Current folder')],['selected',t('Selected models')],['all',t('Entire library')]],'folder'),history=input('checkbox','');out.append(field(t('Include models'),scope),field(t('Include saved checkpoints'),history,t('Checkpoints may substantially increase archive size.')),el('p','hint',t('The archive contains your assets and profiles. Generation engines and model weights stay in the installation.')));const summary=el('div','transfer-summary');out.append(summary);const create=button(t('Prepare collection backup'),'download','primary');ui.foot.append(create);const file=input('file','',{accept:'.zip,application/zip'});file.id='restoreArchiveFile';const name=input('text',t('Restored collection'),{maxlength:80});const content=el('div','transfer-preview');incoming.append(field(t('TRELLIS collection archive'),file),field(t('Restore into a new collection'),name),content);const confirm=button(t('Restore collection'),'import','primary');confirm.hidden=true;ui.foot.append(confirm);let inspected=null;
 const disk=button(t('Inspect export copies'),'search');
 const copies=el('div','transfer-summary');
 out.append(disk,copies);
 disk.onclick=()=>action(ui,disk,async()=>{
   const result=await api('/api/exports/staging-inventory');
   const mib=bytes=>(bytes/1048576).toLocaleString(formatLocale,{maximumFractionDigits:1});
   copies.replaceChildren(el('strong','',t('Export copies · {size} MiB',{size:mib(result.total_bytes)})));
   for (const entry of result.entries) {
     const details=document.createElement('details');
     details.append(el('summary','',entry.export_id+'/'+entry.path+' · '+mib(entry.bytes)+' MiB'));
     const list=document.createElement('ul');
     for (const file of entry.members) list.append(el('li','',file.path+' · '+mib(file.bytes)+' MiB'));
     details.append(list);
     const release=button(t('Free this verified copy'),'trash');
     release.onclick=()=>action(ui,release,async()=>{
       await api('/api/exports/'+entry.export_id+'/release-copy/'+entry.path,{method:'POST'});
       disk.click();
     });
     details.append(release);copies.append(details);
   }
 });
 incoming.append(el('p','hint',t('Portable backups restore geometry, materials and clips. HD refinishing also requires the matching local master cache.')));
 function ids(){const all=getRecords().filter(j=>j.state==='done');if(scope.value==='selected')return all.filter(j=>getSelection().includes(j.id)).map(j=>j.id);if(scope.value==='folder')return all.filter(j=>workspace.matches(j)).map(j=>j.id);return all.map(j=>j.id);}
 function update(){const selected=ids();summary.replaceChildren(el('strong','',t(selected.length===1?'{count} completed model':'{count} completed models',{count:selected.length})),el('small','',t('Geometry · source images · profiles · animation clips · folders & metadata')));create.disabled=!selected.length;}
 function tab(importing){incoming.hidden=!importing;out.hidden=importing;create.hidden=importing;confirm.hidden=!importing||!inspected;backup.classList.toggle('active',!importing);restore.classList.toggle('active',importing);}
 backup.onclick=()=>tab(false);restore.onclick=()=>tab(true);scope.onchange=update;create.onclick=()=>{const records=getRecords().filter(j=>ids().includes(j.id));ui.close();exports.openArchive(records,history.checked);};
 file.onchange=async()=>{if(!file.files.length)return;file.disabled=true;confirm.hidden=true;inspected=null;content.replaceChildren(el('p','hint',t('Uploading and verifying every archived file…')));ui.notice.textContent='';try{const form=new FormData();form.set('file',file.files[0]);inspected=await api('/api/transfers/inspect',{method:'POST',body:form});content.replaceChildren(el('h3','',t(inspected.models.length===1?'{count} model verified':'{count} models verified',{count:inspected.models.length})),el('p','hint',[t(inspected.folders===1?'{count} folder':'{count} folders',{count:inspected.folders}),t(inspected.profiles===1?'{count} profile':'{count} profiles',{count:inspected.profiles}),t('{size} MB',{size:(inspected.bytes/1024**2).toLocaleString(formatLocale,{minimumFractionDigits:1,maximumFractionDigits:1})})].join(' · ')));const list=el('ul','transfer-models');for(const model of inspected.models)list.append(el('li','',model.name));content.append(list,el('p','hint',t('Restoration creates new model identifiers and a new collection. Existing models remain available.')));confirm.hidden=false;}catch(e){ui.notice.textContent=t(e.message);content.replaceChildren();}finally{file.disabled=false;}};
 confirm.onclick=()=>action(ui,confirm,async()=>{const result=await api('/api/transfers/'+inspected.id+'/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.value})});await workspace.reload();workspace.selectFolder(result.folder_id);await refresh();ui.close();});
 return {open(){scope.value=getSelection().length?'selected':workspace.current==='*'?'all':'folder';update();tab(false);ui.show();}};
}
