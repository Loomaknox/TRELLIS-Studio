import {formatLocale, t} from './i18n.js';

const $=id=>document.getElementById(id);
const typeNames=new Map();
export const assetTypeName=value=>t(typeNames.get(value)||'')||value||t('Static prop');
export async function createAssetDetails(){
  const response=await fetch('/api/asset-taxonomy');if(!response.ok)throw Error(t('Asset classification is unavailable. Restart TRELLIS.'));
  const data=await response.json();
  function choice(value,label){const o=document.createElement('option');o.value=value;o.textContent=label;return o;}
  function populate(id,groups,empty){const select=$(id);select.replaceChildren();if(empty)select.append(choice('',t(empty)));
    for(const group of groups){const g=document.createElement('optgroup');g.label=t(group.label);for(const item of group.options){const value=typeof item==='string'?item:item.value,label=typeof item==='string'?item:item.label;g.append(choice(value,t(label)));}select.append(g);}}
  for(const group of data.asset_types)for(const item of group.options)typeNames.set(item.value,item.label);
  for(const [value,label]of Object.entries(data.system_types))typeNames.set(value,label);
  populate('category',data.categories,'Uncategorised');populate('assetType',data.asset_types);
  populate('detailAssetType',[...data.asset_types,{label:'Source & workflow',options:Object.entries(data.system_types).map(([value,label])=>({value,label}))}]);
  const filter=$('libraryFilter');for(const value of ['object','architecture','imported','rigged'])filter.querySelector(`option[value="${value}"]`)?.remove();
  const filterTypes=document.createElement('optgroup');filterTypes.label=t('Asset type');for(const [value,label]of typeNames)filterTypes.append(choice('type:'+value,t(label)));filter.append(filterTypes);
  function setValue(id,value){const select=$(id);select.querySelector('[data-legacy]')?.remove();if(![...select.options].some(o=>o.value===value)){const o=choice(value,value);o.dataset.legacy='true';select.append(o);}select.value=value;}
  function hint(){const type=$('assetType').value;
    $('assetHint').textContent=t(['humanoid','robot'].includes(type)?'Show the full character in a clear A/T pose, with limbs separated. Generation creates a static mesh; add a rig in Animate.':
      ['creature','animal'].includes(type)?'Show the entire body, with legs and appendages separated. Generation creates a static mesh.':
      type==='architecture'?'Non-enterable background building. Show the entire facade, roof and secondary forms.':
      type==='terrain_block'?'An isolated ground patch. Mesh output without a heightmap.':
      'Show one complete subject against a plain neutral background. Asset type is a classification; moving parts and game behaviours require separate setup.');
  }
  $('assetType').addEventListener('change',hint);hint();
  function update(j){const r=j?.result||{},m=j?.metadata||{};
    $('detailTitle').textContent=m.display_name||j?.settings.name||t('No model selected');
    $('detailSubtitle').textContent=j?assetTypeName(m.asset_type||j.settings.asset_type):t('Choose a model from your collection');
    $('detailThumbnail').src=j?`/api/jobs/${j.id}/files/${j.settings.asset_type==='terrain_unity'?'heightmap.png':'input.png'}?v=${j.result?.revision||j.state}`:'/web/asset-placeholder.svg';
    $('detailThumbnail').onerror=()=>{$('detailThumbnail').onerror=null;$('detailThumbnail').src='/web/asset-placeholder.svg';};
    $('detailTriangles').textContent=r.triangles?Number(r.triangles).toLocaleString(formatLocale):'—';
    const adaptive=r.adaptive_finishing,adaptiveNotice=$('adaptiveFinishingReport');
    const finishingNotes=[];
    if(r.surface_repair){
      finishingNotes.push(t('Surface rebuilt from the saved master to close holes.'));
    }
    if(adaptive?.trials?.length){
      const sample=adaptive.trials.at(-1);
      const outcome=t(adaptive.target_met?'tolerance met':'tolerance missed within the triangle ceiling');
      const reference=t(adaptive.reference||'master mesh');
      const error=sample.p99_voxels.toLocaleString(formatLocale,{minimumFractionDigits:2,maximumFractionDigits:2});
      const tolerance=Number(adaptive.tolerance_voxels).toLocaleString(formatLocale);
      finishingNotes.push(t('Adaptive finishing · {outcome} · sampled error against {reference} {error} / {tolerance} source voxels.',{outcome,reference,error,tolerance}));
    }
    adaptiveNotice.hidden=!finishingNotes.length;
    adaptiveNotice.textContent=finishingNotes.join(' ');
    const normalBake = r.normal_bake;
    const normalNotice = $('normalBakeReport');
    normalNotice.hidden = normalBake?.state !== 'applied';
    if (!normalNotice.hidden) {
      normalNotice.textContent = t('Master detail baked into a {width} × {height} normal map. View in PBR.',normalBake);
    }
    $('detailHeight').textContent=r.height_m?Number(r.height_m*100).toLocaleString(formatLocale,{maximumFractionDigits:1})+' cm':'—';
    $('detailClips').textContent=String(r.animations??r.animation_set?.length??j?.settings.animation_clips?.length??0);
    const report=r.print_report;$('printReportCard').hidden=!report;
    if(report){$('printSurfaceState').textContent=t(report.closed_surface?'Closed surface verified':'Surface repair needed');
      const voxel=Number(report.effective_voxel_mm).toLocaleString(formatLocale,{minimumFractionDigits:2,maximumFractionDigits:2});
      $('printReportSummary').textContent=t('{count} connected shell(s) · voxel {voxel} mm · STL in mm',{count:report.connected_shells,voxel});
      $('printWarnings').replaceChildren(...report.warnings.map(text=>{
        const li=document.createElement('li');
        const disconnected=/^(\d+) disconnected shells remain\. Check for floating parts or internal cavities\.$/.exec(text);
        li.textContent=disconnected?t('{count} disconnected shells remain. Check for floating parts or internal cavities.',{count:disconnected[1]}):t(text);
        return li;
      }));
      $('printReportDownload').href=`/api/jobs/${j.id}/files/print-report.json`;}
  }
  return {setValue,hint,update};
}
