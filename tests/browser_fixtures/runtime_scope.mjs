// Trusted platform conformance regression. Negative synthetic clicks are named
// explicitly; none is evidence of generated-game completion/playability.
import fs from 'node:fs';
import crypto from 'node:crypto';
import {chromium} from '/validator/node_modules/playwright/index.mjs';
import {bridgeAdapter} from '/validator/bridge_adapter.mjs';
import {installLifecycleProbe} from '/validator/lifecycle_probe.mjs';
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const html=fs.readFileSync('/input/game.html','utf8'),config=JSON.parse(fs.readFileSync('/input/config.json','utf8'));
const harnessFiles=Object.fromEntries(fs.readdirSync('/validator').filter(name=>name.endsWith('.mjs')).sort().map(name=>[name,sha(fs.readFileSync('/validator/'+name))]));
if(JSON.stringify(harnessFiles)!==JSON.stringify(config.harness_files_sha256)) throw new Error('Platform qualification image source changed; rebuild before execution');
const checks=[],snapshots=[],evidence=[];
const record=(name,condition,detail={})=>checks.push({name,passed:condition,detail});
function installScopeProbe(){
 const entries=[],add=EventTarget.prototype.addEventListener,remove=EventTarget.prototype.removeEventListener;
 const label=(target,type)=>target===document&&type==='keydown'?'scope-document-key':target?.dataset?.testid?.startsWith('scope-')?target.dataset.testid:null;
 EventTarget.prototype.addEventListener=function(type,fn,options){const name=label(this,type);if(name)entries.push({target:this,name,type,fn,active:true});return add.call(this,type,fn,options);};
 EventTarget.prototype.removeEventListener=function(type,fn,options){for(const entry of entries)if(entry.target===this&&entry.type===type&&entry.fn===fn)entry.active=false;return remove.call(this,type,fn,options);};
 Object.defineProperty(window,'__SCOPE_EVENTS_PROBE__',{value:Object.freeze({
  snapshot(){return entries.map(({name,type,active,target})=>({name,type,active,connected:Boolean(target.isConnected)}));},
  syntheticNeverClick(){const entry=entries.find(x=>x.name==='scope-never'&&x.active);if(!entry)throw new Error('Detached scope test target missing');entry.target.click();},
  syntheticOldClicks(){for(const entry of entries)if(entry.name==='scope-deferred'&&!entry.active)entry.target.click();},
 }),writable:false,configurable:false});
}
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||undefined,args:['--no-sandbox','--disable-dev-shm-usage','--disable-background-networking','--alsa-output-device=null']});
for(const width of [1280,390]){
 const touch=width===390,context=await browser.newContext({viewport:{width,height:844},isMobile:touch,hasTouch:touch,serviceWorkers:'block',acceptDownloads:false});
 await context.addInitScript(installScopeProbe);await context.addInitScript(installLifecycleProbe);await context.tracing.start({screenshots:true,snapshots:true,sources:false});
 const page=await context.newPage();page.setDefaultTimeout(5000);const errors=[],network=[];let initial=true;
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',async route=>{if(initial&&route.request().url()==='http://review.invalid/index.html'&&route.request().isNavigationRequest()){initial=false;return route.fulfill({contentType:'text/html',body:html,headers:{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src data: blob:; object-src 'none'; base-uri 'none'"}});}network.push(route.request().url());return route.abort();});
 try{
  await page.goto('http://review.invalid/index.html');await page.waitForFunction(()=>window.__GAME_TEST__?.identity,{timeout:5000});
  const pointer=selector=>touch?page.locator(selector).tap():page.locator(selector).click();
  const drag=async()=>{
   const box=await page.locator('[data-testid="scope-drag"]').boundingBox();if(!box)throw new Error('Scoped drag control missing');const from={x:box.x+box.width/2,y:box.y+box.height/2},to={x:from.x,y:from.y+80};
   if(touch){const cdp=await context.newCDPSession(page);await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[from]});for(let i=1;i<=8;i++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:from.x,y:from.y+(to.y-from.y)*i/8}]});await page.waitForTimeout(15);}await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await cdp.detach();}
   else{await page.mouse.move(from.x,from.y);await page.mouse.down();await page.mouse.move(to.x,to.y,{steps:8});await page.mouse.up();}
  };
  const bridge=bridgeAdapter(page),state=async label=>{const s=await bridge.snapshot();snapshots.push({name:`${label}:${width}`,snapshot:s});return s;};
  const probe=()=>page.evaluate(()=>window.__SCOPE_EVENTS_PROBE__.snapshot());
  await pointer('[data-testid="start"]');let s=await state('start');
  record(`foreign-registration-rejected:${width}`,s.foreignRejected&&s.foreignDocumentRejected,{snapshot:s});
  await pointer('[data-testid="scope-deferred"]');s=await state('ordinary-pointer');
  record(`detached-before-append-real-input:${width}`,s.clicks===1,{real_input:touch?'touch':'mouse',snapshot:s});
  record(`visible-render:${width}`,(await page.locator('[data-testid="scope-count"]').innerText()).includes('Clicks 1'),{actual_dom:true});
  await page.keyboard.press('1');s=await state('ordinary-key');record(`scoped-key:${width}`,s.keys===1,{actual_key:'1'});
  const scrollBefore=await page.evaluate(()=>scrollY);await drag();s=await state('scoped-drag');const scrollAfter=await page.evaluate(()=>scrollY);
  record(`scoped-vertical-drag-real-input:${width}`,s.dragged===1,{real_input:touch?'touch-drag':'mouse-drag',snapshot:s});
  record(`drag-does-not-pan-document:${width}`,Math.abs(scrollAfter-scrollBefore)<2,{scroll_before:scrollBefore,scroll_after:scrollAfter,actual_vertical_drag:true});
  const before=await page.evaluate(()=>window.__GAME_TEST__.diagnostics().input_events);
  await page.evaluate(()=>window.__SCOPE_EVENTS_PROBE__.syntheticNeverClick());s=await state('never-appended-negative');
  const after=await page.evaluate(()=>window.__GAME_TEST__.diagnostics().input_events);
  record(`never-appended-synthetic-negative:${width}`,s.never===0&&before===after,{synthetic_api_negative:true,runtime_events_before:before,runtime_events_after:after});
  await pointer('[data-testid="scope-foreign"]');
  // Mobile touch does not consistently transfer focus after pointer capture.
  // Real Tab navigation establishes the documented keyboard focus guard.
  for(let attempt=0;attempt<10&&!await page.locator('[data-testid="scope-foreign"]').evaluate(node=>node===document.activeElement);attempt++)await page.keyboard.press('Tab');
  const foreignFocused=await page.locator('[data-testid="scope-foreign"]').evaluate(node=>node===document.activeElement);
  await page.keyboard.press('1');s=await state('foreign-real-input');record(`foreign-connected-real-input-ignored:${width}`,foreignFocused&&s.foreign===0&&s.keys===1,{real_pointer_and_key:true,actual_tab_focus_navigation:true,foreign_focused:foreignFocused});
  await pointer('[data-testid="scope-move"]');await pointer('[data-testid="scope-deferred"]');s=await state('moved-out');record(`moved-out-real-input-ignored:${width}`,s.clicks===1&&s.moved,{real_pointer:true});
  await pointer('[data-testid="scope-return"]');await pointer('[data-testid="scope-deferred"]');s=await state('returned');record(`returned-control-real-input:${width}`,s.clicks===2&&!s.moved,{real_pointer:true});
  await bridge.lifecycle('hide');await pointer('[data-testid="scope-deferred"]');await page.keyboard.press('1');s=await state('hidden');record(`synthetic-hide-blocks-real-input:${width}`,s.clicks===2&&s.keys===1&&s.paused,{synthetic_document_lifecycle:true,real_pointer_and_key:true});
  await bridge.lifecycle('show');await pointer('[data-testid="scope-deferred"]');await page.keyboard.press('1');s=await state('shown');record(`synthetic-show-restores-real-input:${width}`,s.clicks===3&&s.keys===2&&!s.paused,{synthetic_document_lifecycle:true,real_pointer_and_key:true});
  await pointer('[data-testid="scope-unsubscribe"]');await pointer('[data-testid="scope-deferred"]');s=await state('unsubscribed');record(`returned-remover:${width}`,s.unsubscribed&&s.clicks===3,{real_pointer:true});
  let listeners=await probe();record(`ordinary-listener-removed:${width}`,listeners.filter(x=>x.name==='scope-deferred'&&x.active).length===0,{listeners});
  await pointer('[data-testid="restart"]');s=await state('restart');listeners=await probe();
  record(`restart-cleanup:${width}`,s.clicks===0&&s.keys===0&&s.dragged===0&&s.never===0&&listeners.filter(x=>x.name==='scope-deferred'&&x.active).length===1&&listeners.filter(x=>x.name==='scope-document-key'&&x.active).length===1&&listeners.filter(x=>x.name==='scope-never'&&x.active).length===1,{listeners,snapshot:s});
  await page.evaluate(()=>window.__SCOPE_EVENTS_PROBE__.syntheticOldClicks());s=await state('old-session-synthetic-negative');record(`old-session-detached-negative:${width}`,s.clicks===0,{synthetic_api_negative:true});
  await pointer('[data-testid="scope-deferred"]');await page.keyboard.press('1');s=await state('fresh-session');record(`fresh-session-real-input-once:${width}`,s.clicks===1&&s.keys===1,{real_pointer_and_key:true});
  await drag();s=await state('fresh-session-drag');record(`fresh-session-drag-once:${width}`,s.dragged===1,{real_drag:true});
  fs.writeFileSync(`/evidence/qualified-${width}.png`,await page.screenshot({fullPage:true}));
  await page.evaluate(()=>window.__GAME_TEST__.dispose());listeners=await probe();record(`dispose-removes-all-owned-listeners:${width}`,listeners.every(x=>!x.active),{listeners});
  await page.evaluate(()=>window.__SCOPE_EVENTS_PROBE__.syntheticOldClicks());
 }catch(error){record(`runtime-conformance-error:${width}`,false,{message:String(error.message).slice(0,1000)});fs.writeFileSync(`/evidence/failure-${width}.png`,await page.screenshot({fullPage:true}));}
 finally{record(`page-errors:${width}`,errors.length===0,{errors});record(`offline:${width}`,network.length===0,{network});fs.writeFileSync(`/evidence/console-${width}.json`,JSON.stringify(errors));fs.writeFileSync(`/evidence/network-${width}.json`,JSON.stringify(network));await context.tracing.stop({path:`/evidence/trace-${width}.zip`});await context.close();}
}
for(const name of fs.readdirSync('/evidence').sort()){const data=fs.readFileSync('/evidence/'+name);evidence.push({path:name,sha256:sha(data),bytes:data.length});}
process.stdout.write(JSON.stringify({schema_version:1,scope:'Trusted platform API conformance: real input plus explicitly named synthetic negative/lifecycle checks; not a generated-game benchmark',passed:checks.every(x=>x.passed),html_sha256:sha(Buffer.from(html)),runtime:config.runtime,validator_image_sha256:config.image,harness_files_sha256:harnessFiles,script_sha256:sha(fs.readFileSync('/review/challenge.mjs')),browser_version:browser.version(),checks,snapshots,evidence_files:evidence}));await browser.close();
