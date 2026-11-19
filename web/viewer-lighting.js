import * as THREE from 'three';
import {icon} from './card-menu.js?v=3.4.0';
const KEY='trellis.viewerLighting';
export const DEFAULT_LIGHTING={azimuth:45,elevation:45,intensity:1.4,fill:.9,exposure:1.1,colour:'#ffffff',shadows:false,guide:false};
const PRESETS={Studio:DEFAULT_LIGHTING,Soft:{...DEFAULT_LIGHTING,azimuth:-25,elevation:65,intensity:.8,fill:1,exposure:1.05},Dramatic:{...DEFAULT_LIGHTING,azimuth:110,elevation:30,intensity:2.1,fill:.2,exposure:1,colour:'#fff0d9'}};
function normalise(raw){const c={...DEFAULT_LIGHTING};for(const [key,min,max]of [['azimuth',-180,180],['elevation',5,85],['intensity',0,4],['fill',0,2],['exposure',.25,2]])if(typeof raw?.[key]==='number'&&Number.isFinite(raw[key]))c[key]=Math.min(max,Math.max(min,raw[key]));if(/^#[a-f0-9]{6}$/i.test(raw?.colour))c.colour=raw.colour;for(const key of ['shadows','guide'])if(typeof raw?.[key]==='boolean')c[key]=raw[key];return c;}
export function readLighting(){try{return normalise(JSON.parse(localStorage.getItem(KEY)));}catch{return {...DEFAULT_LIGHTING};}}

// The floor is part of the interactive preview. Presentation captures copy the model and lights separately.
export function createViewerStage(scene, viewport) {
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(9, 9), new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      floorTint: {value: new THREE.Color(0x2e473f)},
      haloTint: {value: new THREE.Color(0xacdf66)},
      ringTint: {value: new THREE.Color(0xe6ffa6)},
      showGrid: {value: true},
    },
    vertexShader: `
      varying vec2 floorPosition;
      void main() {
        floorPosition = position.xy;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: `
      varying vec2 floorPosition;
      uniform vec3 floorTint;
      uniform vec3 haloTint;
      uniform vec3 ringTint;
      uniform bool showGrid;

      float glow(vec2 offset, vec2 extent) {
        vec2 uv = offset / extent;
        return 1.0 - smoothstep(0.0, 1.0, dot(uv, uv));
      }

      void main() {
        float radius = length(floorPosition);
        float edge = abs(radius - 1.0);
        float aa = clamp(fwidth(radius), 0.0005, 0.015);
        float ring = 1.0 - smoothstep(0.002, 0.002 + aa, edge);
        float rim = 1.0 - smoothstep(0.0, 0.092, edge);
        float falloff = 1.0 - smoothstep(0.35, 3.65, radius);
        float seams = 0.0;
        if (showGrid) {
          vec2 tile = floorPosition * 4.0;
          vec2 lineDistance = abs(fract(tile - 0.5) - 0.5) / max(fwidth(tile), vec2(0.001));
          seams = 1.0 - smoothstep(0.1, 1.1, min(lineDistance.x, lineDistance.y));
        }

        // The light streak stretches across the feet, while its reflection reaches the front rim.
        vec2 across = normalize(vec2(viewMatrix[0][0], -viewMatrix[2][0]));
        vec2 forward = vec2(across.y, -across.x);
        vec2 floorView = vec2(dot(floorPosition, across), dot(floorPosition, forward));
        float core = glow(floorView - vec2(0.0, -0.05), vec2(0.58, 0.14));
        float pool = glow(floorView - vec2(0.0, 0.10), vec2(0.48, 0.78));
        float reflection = glow(floorView - vec2(0.0, 0.48), vec2(0.41, 1.25));
        float splash = glow(floorView - vec2(0.0, 0.94), vec2(0.31, 0.32));

        float halo = 0.21 * rim + 0.32 * pool + 0.21 * reflection + 0.22 * splash;
        float highlights = 0.67 * ring + 0.79 * core;
        float surface = (0.09 + 0.16 * seams) * falloff;
        vec3 colour = mix(floorTint, haloTint, clamp(halo * 1.35, 0.0, 1.0));
        colour = mix(colour, ringTint, min(1.0, highlights));
        gl_FragColor = vec4(colour, min(0.98, surface + halo + highlights));
        #include <colorspace_fragment>
      }`,
  }));
  // The optional shadow plane renders over the stage without introducing a second light source.
  floor.renderOrder = -2;
  floor.rotation.x = -Math.PI / 2;
  floor.visible = false;
  scene.add(floor);

  return {
    fit(bounds) {
      const center = bounds.getCenter(new THREE.Vector3());
      const size = bounds.getSize(new THREE.Vector3());
      const span = Math.max(size.x, size.y, size.z, 0.01);
      const radius = span * 0.64;
      floor.position.set(center.x, Math.min(0, bounds.min.y) - span * 0.0002, center.z);
      floor.scale.setScalar(radius);
    },
    setGridVisible(visible) {
      floor.material.uniforms.showGrid.value = visible;
    },
    setVisible(visible) {
      floor.visible = visible;
      viewport.classList.toggle('viewer-stage-ready', visible);
    },
  };
}

export function createLightingRig(scene,renderer){
 const fill=scene.children.find(x=>x.isHemisphereLight)||new THREE.HemisphereLight(0xffffff,0x394331,.7);if(!fill.parent)scene.add(fill);
 const key=new THREE.DirectionalLight(0xffffff,1.4);key.name='Preview key light';key.shadow.mapSize.set(1024,1024);key.shadow.bias=-.00008;scene.add(key,key.target);
 const floor=new THREE.Mesh(new THREE.PlaneGeometry(1,1),new THREE.ShadowMaterial({opacity:.2}));floor.rotation.x=-Math.PI/2;floor.receiveShadow=true;floor.visible=false;floor.renderOrder=-1;scene.add(floor);
 const arrow=new THREE.ArrowHelper(new THREE.Vector3(1,1,1).normalize(),new THREE.Vector3(),1,0xc4f58a);arrow.visible=false;scene.add(arrow);
 const sun=new THREE.Mesh(new THREE.SphereGeometry(.025,12,8),new THREE.MeshBasicMaterial({color:0xffefc0,depthTest:false}));sun.renderOrder=15;sun.visible=false;scene.add(sun);
 let root=null,config=readLighting(),span=1,center=new THREE.Vector3(0,.5,0),ground=0;
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
 function apply(c){config=normalise(c);const a=THREE.MathUtils.degToRad(config.azimuth),e=THREE.MathUtils.degToRad(config.elevation),direction=new THREE.Vector3(Math.cos(e)*Math.sin(a),Math.sin(e),Math.cos(e)*Math.cos(a));
  key.visible=!!root;key.color.set(config.colour);key.intensity=config.intensity;key.position.copy(center).addScaledVector(direction,span*3);key.target.position.copy(center);key.target.updateMatrixWorld();
  fill.intensity=config.fill;scene.environmentIntensity=config.fill;scene.environmentRotation.y=a;renderer.toneMappingExposure=config.exposure;
  key.castShadow=config.shadows;floor.visible=!!root&&config.shadows;arrow.visible=!!root&&config.guide;sun.visible=!!root&&config.guide;
  const distance=span*2;key.shadow.camera.left=-distance;key.shadow.camera.right=distance;key.shadow.camera.top=distance;key.shadow.camera.bottom=-distance;key.shadow.camera.near=Math.max(.0001,span*.01);key.shadow.camera.far=span*10;key.shadow.normalBias=span*.001;key.shadow.camera.updateProjectionMatrix();
  floor.position.set(center.x,ground-.0001*span,center.z);floor.scale.setScalar(span*4);arrow.position.copy(center);arrow.setDirection(direction);arrow.setLength(span*.7,span*.1,span*.045);sun.position.copy(center).addScaledVector(direction,span*.7);sun.scale.setScalar(span);sun.material.color.set(config.colour);
  root?.traverse(x=>{if(x.isMesh){x.castShadow=config.shadows;x.receiveShadow=config.shadows;}});
 }
 function fit(model){root=model;if(root){root.updateMatrixWorld(true);const box=new THREE.Box3().setFromObject(root,true);if(!box.isEmpty()){center=box.getCenter(new THREE.Vector3());const size=box.getSize(new THREE.Vector3());span=Math.max(size.x,size.y,size.z,.01);ground=Math.min(0,box.min.y);}}apply(config);}
 apply(config);
 return {apply,fit,dispose(){scene.remove(key,key.target,floor,arrow,sun);key.shadow.map?.dispose();floor.geometry.dispose();floor.material.dispose();arrow.line.geometry.dispose();arrow.line.material.dispose();arrow.cone.geometry.dispose();arrow.cone.material.dispose();sun.geometry.dispose();sun.material.dispose();}};
}
export function createViewerLighting({scene,renderer,getModel}){
 const rig=createLightingRig(scene,renderer),panel=document.createElement('div');panel.id='lightingPanel';panel.className='lighting-panel';panel.setAttribute('popover','auto');panel.setAttribute('role','dialog');panel.setAttribute('aria-label','Preview lighting');
 panel.innerHTML=`<div class="lighting-head"><span><svg class="ui-icon" aria-hidden="true"><use href="/web/icons.svg#sun"/></svg>Preview lighting</span><button id="closeLighting" type="button" aria-label="Close lighting"></button></div><div id="lightingPresets" class="lighting-presets"></div><div id="lightingSliders"></div><div class="light-colour-row"><span>Light colour</span><div id="lightingColours"></div><input id="lightColour" type="color" aria-label="Light colour" value="#ffffff"></div><div class="lighting-checks"><label class="check"><input id="lightShadows" type="checkbox"><span>Ground shadow</span></label><label class="check"><input id="lightGuide" type="checkbox"><span>Light guide</span></label></div><footer><span id="lightingPresetName">Studio</span><button id="resetLighting" class="quiet" type="button">Reset</button></footer>`;document.body.append(panel);
 const $=id=>panel.querySelector('#'+id),button=document.getElementById('lightingToggle');let current=readLighting();
 const fields=[['azimuth','Direction',-180,180,1,'°'],['elevation','Elevation',5,85,1,'°'],['intensity','Key light',0,4,.1,''],['fill','Fill light',0,2,.05,''],['exposure','Exposure',.25,2,.05,'']];
 for(const [key,label,min,max,step,unit]of fields){const row=document.createElement('label');row.className='lighting-slider';const line=document.createElement('span'),text=document.createElement('span'),value=document.createElement('output'),input=document.createElement('input');text.textContent=label;value.id='lightValue-'+key;line.append(text,value);input.type='range';input.min=min;input.max=max;input.step=step;input.id='light-'+key;input.setAttribute('aria-label',label);input.oninput=()=>{current[key]=Number(input.value);apply(true);};row.append(line,input);$('lightingSliders').append(row);}
 for(const [name,settings]of Object.entries(PRESETS)){const b=document.createElement('button');b.type='button';b.dataset.preset=name;b.append(icon(name==='Soft'?'cloud':name==='Dramatic'?'contrast':'sun'),document.createTextNode(name));b.onclick=()=>{current={...settings,shadows:current.shadows,guide:current.guide};apply(true);};$('lightingPresets').append(b);}
 for(const [name,colour]of [['Warm','#ffe0b5'],['Neutral','#ffffff'],['Cool','#c4ddff']]){const b=document.createElement('button');b.type='button';b.title=name+' light';b.setAttribute('aria-label',name+' light');b.style.color=colour;b.append(icon('sun'));b.onclick=()=>{current.colour=colour;apply(true);};$('lightingColours').append(b);}
 function apply(save=false){current=normalise(current);rig.apply(current);for(const [key,label,min,max,step,unit]of fields){$('light-'+key).value=current[key];$('lightValue-'+key).value=current[key].toFixed(unit?0:key==='intensity'?1:2)+unit;}$('lightColour').value=current.colour;$('lightShadows').checked=current.shadows;$('lightGuide').checked=current.guide;
  let preset='Custom';for(const [name,settings]of Object.entries(PRESETS))if(['azimuth','elevation','intensity','fill','exposure','colour'].every(k=>current[k]===settings[k]))preset=name;
  $('lightingPresetName').textContent=preset;for(const b of $('lightingPresets').children)b.setAttribute('aria-pressed',b.dataset.preset===preset);
  if(save){try{localStorage.setItem(KEY,JSON.stringify(current));}catch{}window.dispatchEvent(new CustomEvent('trellis-lighting-change',{detail:current}));}}
 $('lightColour').oninput=()=>{current.colour=$('lightColour').value;apply(true);};$('lightShadows').onchange=()=>{current.shadows=$('lightShadows').checked;apply(true);};$('lightGuide').onchange=()=>{current.guide=$('lightGuide').checked;apply(true);};$('resetLighting').onclick=()=>{current={...DEFAULT_LIGHTING};apply(true);};$('closeLighting').onclick=()=>panel.hidePopover();
 button.onclick=()=>{if(panel.matches(':popover-open')){panel.hidePopover();return;}panel.showPopover();const r=button.getBoundingClientRect(),box=panel.getBoundingClientRect();panel.style.left=Math.max(10,Math.min(innerWidth-box.width-10,r.left+r.width/2-box.width/2))+'px';panel.style.top=Math.max(10,Math.min(innerHeight-box.height-10,r.top-box.height-13))+'px';};
 panel.addEventListener('toggle',event=>button.setAttribute('aria-expanded',event.newState==='open'));window.addEventListener('resize',()=>{if(panel.matches(':popover-open'))panel.hidePopover();});window.addEventListener('storage',event=>{if(event.key===KEY){current=readLighting();apply();}});apply();
 return {fit(){rig.fit(getModel());},clear(){rig.fit(null);},get settings(){return {...current};}};
}
