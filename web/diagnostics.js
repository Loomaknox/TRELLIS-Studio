import {formatLocale, language, localizeStatic, t} from './i18n.js';
import {icon} from './card-menu.js?v=3.4.0';
const nameOf=j=>j?.metadata?.display_name||j?.settings.name||t('Model');
function findingMessage(item) {
 if (item.clip !== undefined) return t(item.message, {
  clip: item.clip, bone: t(item.bone || ''), speed:item.speed?.toLocaleString(formatLocale),
  time: item.time_s?.toLocaleString(formatLocale,{maximumFractionDigits:3}),
  degrees: item.degrees?.toLocaleString(formatLocale),
  distance: item.distance_cm?.toLocaleString(formatLocale),
 });
 if (language !== 'fr') return item.message;
 const image = /^Image (\d+) cannot be decoded\.$/.exec(item.message);
 if (image) return t('Image {count} cannot be decoded.', { count: image[1] });
 const separator = item.message.lastIndexOf(': ');
 if (separator === -1) return t(item.message);
 const name = item.message.slice(0, separator);
 const summary = item.message.slice(separator + 2);
 const key = summary.replace(/^[0-9,]+ /, '{count} ');
 const translated = t(key);
 if (translated === key) return item.message;
 return name + ' : ' + t(key, { count: item.count?.toLocaleString(formatLocale) });
}

export function createDiagnostics({api}){
 const dialog=document.createElement('dialog');dialog.id='diagnosticsDialog';dialog.className='studio-dialog diagnostics-dialog';dialog.setAttribute('aria-labelledby','diagnosticsTitle');dialog.innerHTML=`<header class="studio-dialog-head"><div><span class="eyebrow">MODEL HEALTH</span><h2 id="diagnosticsTitle">Model diagnostics</h2><p id="diagnosticModelName"></p></div><button type="button" class="dialog-x" data-close aria-label="Close diagnostics"></button></header><div class="diagnostic-summary" id="diagnosticSummary"></div><div id="diagnosticContent" class="diagnostic-content"></div><footer class="studio-dialog-actions"><span id="diagnosticTime"></span><a id="downloadDiagnostic" class="secondary action-link" hidden download></a><button id="rerunDiagnostics" class="secondary" type="button">Re-run checks</button></footer>`;localizeStatic(dialog);document.body.append(dialog);const $=id=>dialog.querySelector('#'+id);let job=null,version=0;
 let edgePreview=null;
 const el=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;};
 function section(title){const s=el('section','diagnostic-section');const h=el('h3','',title);s.append(h);$('diagnosticContent').append(s);return s;}
 function metrics(parent,entries){const g=el('dl','diagnostic-metrics');for(const [key,value]of entries)g.append(el('dt','',key),el('dd','',String(value)));parent.append(g);}
 function closePreview(){edgePreview?.dispose();edgePreview=null;}
 const scan=document.createElement('button');
 scan.type='button';scan.className='secondary';scan.textContent=t('Inspect skin in motion');
 $('rerunDiagnostics').before(scan);
 let deep=false;
 scan.onclick=()=>{deep=true;run(true);};
 function surfaceDetails(report,own){
  const panel=section(t('Skin and pose review'));
  const data=report.pose_surfaces;
  const view=el('div','prepare-preview diagnostic-edge-view');view.hidden=true;
  panel.append(view);
  const notice=el('p','hint');panel.append(notice);
  async function show(index,time,lines,point){
   closePreview();view.hidden=false;notice.textContent='';
   try{
    const {createPreparationPreview}=await import('./preparation-preview.js?v=3.4.0');
    const p=await createPreparationPreview(view,`/api/jobs/${job.id}/files/model.glb?v=${report.source_sha256}`);
    if(own!==version){p.dispose();return;}closePreview();edgePreview=p;
    p.pose(index,time);
    const radius=Math.max(.003,report.summary.height_m*.009);
    for(const xyz of point){
     for(let axis=0;axis<3;axis++){
      const a=xyz.slice(),b=xyz.slice();a[axis]-=radius;b[axis]+=radius;lines.push(...a,...b);
     }
    }
    p.showEdges({positions:{intersection:lines}});
   }catch(e){notice.textContent=t(e.message);}
  }
  function button(label,action){const b=el('button','quiet',label);b.type='button';b.onclick=action;panel.append(b);}
  if(data){
   panel.append(el('p','hint',t('Sampled {count} primitives, {clips} clips (9 poses each); skipped {omitted} primitives and {missing} clips.',{
    count:data.sampled_primitives,clips:data.checked_clips,omitted:data.skipped_primitives,missing:data.skipped_clips})));
   const hit=data.worst_crossing;
   if(hit){
    const label=`${hit.primitives.join(' × ')} · ${hit.clip || t('Rest pose')} · ${hit.time_s.toFixed(3)} s`;
    button(label,()=>{const lines=[];for(const tri of hit.triangles_m){for(let i=0;i<3;i++)lines.push(...tri[i],...tri[(i+1)%3]);}
     show(hit.clip_index,hit.time_s,lines,[]);});
   }
   for(const weight of data.weights)button(t('{mesh} · {count} suspect skin weights',{mesh:weight.primitive,count:weight.count}),
     ()=>show(null,0,[],weight.locations_m));
  }
  for(const [index,clip] of (report.animation_scan?.clips || []).entries()){
   const regions=clip.surface_contacts?.regions || {};
   for(const metric of Object.values(regions)){
    const value=(metric.distance_m*100).toLocaleString(formatLocale,{maximumFractionDigits:2});
    button(`${clip.clip} · ${t(metric.region)} · ${value} cm · ${metric.time_s.toFixed(3)} s`,
      ()=>show(index,metric.time_s,[],[metric.location_m]));
   }
  }
  for(const issue of report.issues.filter(x=>x.clip && Number.isFinite(x.time_s))){
   const index=report.animations.findIndex(c=>c.name===issue.clip);
   if(index>=0)button(findingMessage(issue),()=>show(index,issue.time_s,[],issue.location_m?[issue.location_m]:[]));
  }
 }
 function edgeSection(report,own){
  const data=report.edge_overlay;
  if(!data||!Object.values(data.positions).some(positions=>positions.length))return;
  const area=section(t('Edge locations'));
  const view=el('div','prepare-preview diagnostic-edge-view');view.hidden=true;
  view.setAttribute('role','region');view.setAttribute('aria-label',t('3D mesh with marked edges'));
  const toggle=el('button','secondary',t('Show edge overlay'));toggle.type='button';toggle.setAttribute('aria-expanded','false');
  const legend=el('p','diagnostic-edge-legend');
  if(data.positions.boundary.length)legend.append(el('span','boundary',t('Amber · boundary')));
  if(data.positions.nonmanifold.length)legend.append(el('span','nonmanifold',t('Pink · nonmanifold')));
  if(data.positions.intersection?.length)legend.append(el('span','',t('Cyan · suspected intersections')));
  if(data.sampled)legend.append(el('span','', t('Sampled edge locations')));
  const notice=el('p','tool-error');notice.setAttribute('role','status');
  area.append(legend,toggle,view,notice);
  const id=job.id;
  toggle.onclick=async()=>{
   if(edgePreview){
    closePreview();view.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.textContent=t('Show edge overlay');return;
   }
   toggle.disabled=true;notice.textContent='';view.hidden=false;
   try{
    const {createPreparationPreview}=await import('./preparation-preview.js?v=3.4.0');
    const preview=await createPreparationPreview(view,`/api/jobs/${id}/files/model.glb?v=${report.source_sha256}`);
    if(own!==version){preview.dispose();return;}
    edgePreview=preview;preview.showEdges(data);toggle.setAttribute('aria-expanded','true');toggle.textContent=t('Hide edge overlay');
   }catch(error){
    if(own===version){view.hidden=true;notice.textContent=t('Unable to display this model in 3D. {error}',{error:t(error.message)});}
   }finally{toggle.disabled=false;}
  };
 }
 async function run(force){if(!job)return;const own=++version;closePreview();$('rerunDiagnostics').disabled=true;$('diagnosticContent').replaceChildren(el('p','tool-loading',t('Checking topology, UVs, materials and dimensions…')));$('diagnosticSummary').textContent=t('Analysis in progress');$('downloadDiagnostic').hidden=true;
  try{const d=await api(`/api/jobs/${job.id}/diagnostics?pose_surfaces=${deep}&force=${force?'true':'false'}`);if(own!==version)return;const s=d.summary;$('diagnosticContent').replaceChildren();$('diagnosticSummary').className='diagnostic-summary '+d.status;$('diagnosticSummary').replaceChildren(icon(d.status==='attention'?'alert':'shield'),el('strong','',d.status==='attention'?t('Needs attention'):t('Measured checks complete')),el('span','',t('{findings} finding(s) · {meshes} mesh(es) · {clips} clips',{findings:d.issues.filter(i=>i.severity!=='info').length,meshes:s.meshes,clips:s.clips})));
   const geometry=section(t('Geometry & scale'));metrics(geometry,[[t('Triangles'),s.triangles.toLocaleString(formatLocale)],[t('Vertices'),s.vertices.toLocaleString(formatLocale)],[t('Width × height × depth'),s.dimensions_m.map(x=>(x*100).toLocaleString(formatLocale,{maximumFractionDigits:2})+' cm').join(' × ')],[t('Boundary edges'),s.boundary_edges.toLocaleString(formatLocale)],[t('Nonmanifold edges'),s.nonmanifold_edges.toLocaleString(formatLocale)],[t('Degenerate faces'),s.degenerate_faces.toLocaleString(formatLocale)],[t('Connected shells'),s.connected_shells],[t('Surface'),s.closed_surface?t('Closed'):t('Open / needs inspection')]]);
   if(Number.isInteger(s.suspected_crossing_pairs))metrics(geometry,[[t('Suspected crossing face pairs'),s.suspected_crossing_pairs.toLocaleString(formatLocale)]]);
   if(d.intersection_scope)geometry.append(el('p','hint',t(d.intersection_scope)));
   edgeSection(d,own);
   if(deep||d.animations.length)surfaceDetails(d,own);
   const uv=section(t('UVs, materials & motion'));metrics(uv,[[t('UV coordinates'),s.has_uv?t('Present'):t('Missing or incomplete')],[t('Collapsed UV faces'),s.degenerate_uv_faces.toLocaleString(formatLocale)],[t('Materials'),s.materials],[t('Embedded textures'),s.textures],[t('Skeleton joints'),s.bones],[t('Animation clips'),s.clips]]);if(d.textures.length){const list=el('details','diagnostic-extra');list.append(el('summary','',t('Texture inventory ({count})',{count:d.textures.length})));for(const t of d.textures)list.append(el('p','texture-detail',`${t.name} · ${t.width} × ${t.height} · ${t.mode}`));uv.append(list);}
   const findings=section(t('Findings'));findings.classList.add('diagnostic-findings');if(!d.issues.length)findings.append(el('p','',t('No issues were detected by these checks.')));const extra=d.issues.length>8?el('details','diagnostic-extra'):null;if(extra)extra.append(el('summary','',t('Show {count} more findings',{count:d.issues.length-8})));for(const [index,item] of d.issues.entries()){const row=el('div','diagnostic-finding '+item.severity);row.append(icon(item.severity==='info'?'info':'alert'),el('p','',findingMessage(item)));(index>=8&&extra?extra:findings).append(row);}if(extra)findings.append(extra);
   const scope=section(t('What these checks cover'));scope.classList.add('diagnostic-scope');scope.append(el('p','',t(d.scope)),el('p','',t('Not evaluated: {items}.',{items:d.not_checked.map(value=>t(value)).join(' · ')})));$('diagnosticTime').textContent=t('Checked {time}',{time:new Date(d.created*1000).toLocaleString(formatLocale)});$('downloadDiagnostic').hidden=false;$('downloadDiagnostic').href=`/api/jobs/${job.id}/diagnostics/report?pose_surfaces=${deep}`;$('downloadDiagnostic').replaceChildren(icon('download'),document.createTextNode(t('Report JSON')));
  }catch(error){if(own===version){$('diagnosticSummary').textContent=t('Analysis unavailable');$('diagnosticContent').replaceChildren(el('p','tool-error',t(error.message)));}}finally{if(own===version)$('rerunDiagnostics').disabled=false;}}
 dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{++version;closePreview();});$('rerunDiagnostics').onclick=()=>run(true);
 return {open(selected){if(!selected||selected.state!=='done')return;deep=false;job=selected;$('diagnosticModelName').textContent=nameOf(job);if(!dialog.open)dialog.showModal();run(false);}};
}
