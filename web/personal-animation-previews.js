import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {clone} from 'three/addons/utils/SkeletonUtils.js';
import {icon} from './card-menu.js?v=2.6.1';

// One shared renderer serves only visible cards. The GLBs contain real generated clips.
export function createPersonalMotionPreviews(){
 const width=280,height=290,cards=new Set(),cache=new Map(),loader=new GLTFLoader();
 let renderer,raf=0,last=0,active=true;
 try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});}
 catch{return {attach(container){container.dataset.error='3D preview unavailable';},clear(){},setActive(){}};}
 renderer.setSize(width,height,false);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(33,width/height,.01,100);
 scene.add(new THREE.HemisphereLight(0xeef7ff,0x404c35,2.6));
 const key=new THREE.DirectionalLight(0xfff5dd,3);key.position.set(2,4,3);scene.add(key);
 const rim=new THREE.DirectionalLight(0xd4efbb,2);rim.position.set(-2,2,-2);scene.add(rim);
 const grid=new THREE.GridHelper(20,40,0x74835d,0x3c4b33);grid.material.transparent=true;grid.material.opacity=.35;scene.add(grid);
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const pending=new Map();
 const observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){pending.get(entry.target)?.();pending.delete(entry.target);observer.unobserve(entry.target);}},{rootMargin:'120px'});
 const v=new THREE.Vector3();
 function draw(card,time){
  if(!card.model||!card.context)return;
  scene.add(card.model);card.mixer.setTime(time%Math.max(card.duration,.001));card.model.updateMatrixWorld(true);
  const center=card.center.clone();
  if(card.root){card.root.getWorldPosition(v);center.x+=v.x-card.rootStart.x;center.z+=v.z-card.rootStart.z;}
  grid.position.y=card.floor;camera.position.copy(center).add(card.eye);camera.lookAt(center);renderer.render(scene,camera);
  card.context.clearRect(0,0,width,height);card.context.drawImage(renderer.domElement,0,0);scene.remove(card.model);
 }
 function tick(now){
  raf=0;if(!active||document.hidden||!cards.size)return;
  if(now-last>=85){last=now;for(const card of cards){const r=card.container.getBoundingClientRect();if(r.width&&r.bottom>0&&r.top<innerHeight&&(card.playing||card.hover&&!card.paused&&!reduced.matches))draw(card,(now-card.started)/1000);}}
  raf=requestAnimationFrame(tick);
 }
 function schedule(){if(!raf&&active&&!document.hidden&&cards.size)raf=requestAnimationFrame(tick);}
 document.addEventListener('visibilitychange',schedule);
 function load(url){if(!cache.has(url)){const promise=loader.loadAsync(url).catch(error=>{cache.delete(url);throw error;});cache.set(url,promise);}return cache.get(url);}
 function disposeUnused(){
  for(const [url,promise] of cache){if([...cards].some(card=>card.url===url))continue;cache.delete(url);promise.then(gltf=>{
   const geometries=new Set(),materials=new Set(),textures=new Set();gltf.scene.traverse(o=>{if(o.geometry)geometries.add(o.geometry);for(const m of [].concat(o.material||[])){materials.add(m);for(const value of Object.values(m))if(value?.isTexture)textures.add(value);}});
   geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>t.dispose());
  }).catch(()=>{});}
 }
 return {
  attach(container,motion){
   const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`Generated animation preview: ${motion.name}`);
   const toggle=document.createElement('button');toggle.type='button';toggle.className='personal-preview-toggle';toggle.append(icon('play'),document.createTextNode('Play'));toggle.setAttribute('aria-label',`Play preview: ${motion.name}`);toggle.setAttribute('aria-pressed','false');toggle.disabled=true;
   container.append(canvas,toggle);container.dataset.loading='true';
   const card={container,canvas,context:canvas.getContext('2d'),url:motion.preview_url,playing:false,paused:false,hover:false,started:performance.now()};cards.add(card);
   const setHover=hover=>{card.hover=hover;if(hover&&!card.playing){card.paused=false;card.started=performance.now();}schedule();};
   container.onpointerenter=()=>setHover(true);container.onpointerleave=()=>setHover(false);
   toggle.onclick=()=>{card.playing=!card.playing;card.paused=!card.playing;card.started=performance.now();toggle.replaceChildren(icon(card.playing?'pause':'play'),document.createTextNode(card.playing?'Pause':'Play'));toggle.setAttribute('aria-label',`${card.playing?'Pause':'Play'} preview: ${motion.name}`);toggle.setAttribute('aria-pressed',String(card.playing));schedule();};
   const startLoad=()=>load(card.url).then(gltf=>{
    if(!cards.has(card))return;
    const animation=gltf.animations.find(clip=>clip.name===motion.clip_name);
    if(!animation)throw Error('Animation clip unavailable');
    card.model=clone(gltf.scene);card.model.traverse(o=>{if(o.isMesh)o.frustumCulled=false;});
    card.model.updateMatrixWorld(true);const box=new THREE.Box3().setFromObject(card.model,true),size=box.getSize(new THREE.Vector3()),h=Math.max(size.y,.2);
    card.center=box.getCenter(new THREE.Vector3());card.center.y=box.min.y+h*.52;
    card.eye=new THREE.Vector3(h*.9,h*.28,h*1.95);card.floor=box.min.y-.002;
    card.root=motion.preview_root?card.model.getObjectByName(motion.preview_root):null;
    card.rootStart=card.root?.getWorldPosition(new THREE.Vector3())||new THREE.Vector3();
    card.mixer=new THREE.AnimationMixer(card.model);card.mixer.clipAction(animation).play();card.duration=animation.duration;
    delete container.dataset.loading;toggle.disabled=false;draw(card,0);schedule();
   }).catch(()=>{if(cards.has(card)){delete container.dataset.loading;container.dataset.error='Preview unavailable';toggle.hidden=true;}});
   pending.set(container,startLoad);observer.observe(container);
   return ()=>{observer.unobserve(container);pending.delete(container);cards.delete(card);card.mixer?.stopAllAction();card.model?.traverse(o=>{if(o.isSkinnedMesh)o.skeleton.dispose();});disposeUnused();};
  },
  setActive(value){active=value;if(!active&&raf){cancelAnimationFrame(raf);raf=0;}else schedule();},
  clear(){observer.disconnect();pending.clear();for(const c of cards){c.mixer?.stopAllAction();c.model?.traverse(o=>{if(o.isSkinnedMesh)o.skeleton.dispose();});}cards.clear();disposeUnused();if(raf)cancelAnimationFrame(raf);raf=0;},
 };
}
