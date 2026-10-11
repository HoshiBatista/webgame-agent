'use strict';
// Execute only exact Forge output from the fixed trusted corpus sources.
// LinkeDOM, explicit timers/storage and WebAudio commands are not a browser.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),vm=require('node:vm');
const {loadGame}=require('./ui_harness.cjs');
const corpus=path.resolve(__dirname,'..'),root=path.resolve(corpus,'../../..');
const evidenceDir=path.join(root,'docs/evidence/corpus');
const replay=JSON.parse(fs.readFileSync(path.join(evidenceDir,'durak.json'),'utf8'));
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
assert.equal(replay.kind,'recorded-corpus-pipeline-replay');assert.equal(replay.game,'durak');assert.equal(replay.actual_model_calls,0);
const html=replay.artifact_html;
assert.equal(typeof html,'string','First run python scripts/test_corpus.py to obtain the exact Forge artifact');
assert.equal(sha(html),replay.validation.artifact.html_sha256);
const modules=['engine.js','renderer.js','audio.js','ui.js'].map(name=>{
  const source=fs.readFileSync(path.join(corpus,name),'utf8');
  assert.equal(sha(source),replay.validation.artifact.files_sha256[name],'Stale recorded source: '+name);return source;
});
const expected=('"use strict";\n(() => {\n'+modules.join('\n')+'\nconst __mounted = mountGame(document.getElementById("game-root"));\n})();').replace(/<\/script/gi,'<\\/script');
assert.equal(html.match(/<script>([\s\S]*?)<\/script>/)?.[1],expected,'Only the four exact allowlisted authored modules may execute in the trusted VM');
const spec=JSON.parse(fs.readFileSync(path.join(corpus,'spec.json'),'utf8'));
function load(options={}){return loadGame({...options,html});}
function adapter(h){
  const bridge=()=>h.window.__GAME_TEST__;
  const lifecycle={available:true,synthetic:true,mode:'normal',hidden:false,hides:0,shows:0};
  return {
    setManualMode:value=>bridge().setManualMode(value),reset:o=>bridge().reset(o),snapshot:()=>bridge().snapshot(),
    act:a=>bridge().act(a),advance:n=>bridge().advance(n),exportSave:()=>bridge().exportSave(),importSave:t=>bridge().importSave(t),
    remount:()=>bridge().remount(),
    lifecycle(event){const hidden=event==='hide';h.visibility(hidden);h.event(h.window,hidden?'pagehide':'pageshow');lifecycle.mode=hidden?'hidden':'visible';lifecycle.hidden=hidden;lifecycle[hidden?'hides':'shows']++;},
    lifecycleSnapshot:()=>({...lifecycle}),
    clearLifecycle(){if(h.state.hidden){h.visibility(false);h.event(h.window,'pageshow');}lifecycle.mode='normal';lifecycle.hidden=false;},
    setStorageFault:mode=>h.setStorageMode(mode==='normal'?'ok':mode),
    storageSnapshot:()=>({available:true,mode:h.state.storageMode==='ok'?'normal':h.state.storageMode,
      blocked_reads:h.storageCalls.filter(x=>x.type==='get'&&x.mode==='denied').length,
      blocked_writes:h.storageCalls.filter(x=>x.type==='set'&&['quota','denied'].includes(x.mode)).length,
      blocked_removals:h.storageCalls.filter(x=>x.type==='remove'&&x.mode==='denied').length,denied_accesses:0}),
    click:selector=>h.click(selector),focus:selector=>h.$(selector).focus(),key:key=>h.key(key),
    readElement(selector,property){const list=h.document.querySelectorAll(selector),el=list[0];if(property==='count')return list.length;assert.ok(el);
      if(property==='focused')return h.document.activeElement===el;if(property==='text')return el.textContent;
      if(property==='value')return el.value;if(property==='disabled')return !!el.disabled;if(property==='hidden')return !!el.hidden;
      throw new Error('Unsupported DOM observation');}
  };
}
async function main(){
  const startedAt=new Date().toISOString(),{runScenario}=await import(path.join(root,'validator/scenario_runner.mjs'));
  const cases=[];
  for(const declaration of spec.qa_scenarios){
    const h=load();try{
      const result=await runScenario(adapter(h),{...declaration,steps:declaration.steps.map(s=>JSON.parse(s))});
      cases.push({id:declaration.id,kind:'declared-scenario',...result});
    }finally{h.dispose();}
  }
  async function integration(id,run,kind='authored-integration'){const h=load();try{await run(h);cases.push({id,kind,ok:true});}
    catch(error){cases.push({id,kind,ok:false,message:error.message});}finally{h.dispose();}}
  await integration('durak-stale-callback-after-remount',async h=>{
    const bridge=h.window.__GAME_TEST__;
    bridge.act({type:'start',seed:'corpus-durak-1',playerCount:2});bridge.act({type:'attack',card:'S6'});
    assert.equal(h.timers.size,1);const old=[...h.timers.values()][0].callback;
    assert.equal(bridge.remount().ok,true);assert.equal(h.timers.size,1);
    const current=[...h.timers.keys()][0],before=JSON.stringify(bridge.snapshot().position);
    old();assert.equal(JSON.stringify(bridge.snapshot().position),before);assert.ok(h.timers.has(current));
    h.advance(1200);assert.equal(bridge.snapshot().position.revision,2);assert.equal(h.timers.size,0);
  });
  await integration('durak-two-tabs-durable-conflict',async h=>{
    const bridge=h.window.__GAME_TEST__;bridge.setManualMode(true);bridge.act({type:'start',seed:'corpus-durak-1',playerCount:2});
    const second=load({storage:h.storage});try{
      second.window.__GAME_TEST__.setManualMode(true);second.window.__GAME_TEST__.act({type:'start',seed:'newer-other-tab',playerCount:3});
      const saved=h.storage.get(h.app.storageKey);assert.equal(bridge.act({type:'attack',card:'S6'}),true);
      assert.equal(bridge.snapshot().position.revision,1);assert.equal(bridge.snapshot().persistence.status,'conflict');
      assert.equal(h.storage.get(h.app.storageKey),saved,'The old active tab must not overwrite the new deal');
    }finally{second.dispose();}
  });
  await integration('durak-late-resume-after-mute',async h=>{
    const bridge=h.window.__GAME_TEST__;bridge.setManualMode(true);bridge.act({type:'start',seed:'corpus-durak-1',playerCount:2});
    let resolveResume;
    h.window.AudioContext.prototype.resume=function(){this.resumeCalls++;return new Promise(resolve=>{resolveResume=()=>{this.state='running';resolve();};});};
    h.click('#btn-sound');assert.equal(h.contexts.length,1);assert.equal(h.contexts[0].state,'suspended');
    assert.equal(h.audioEvents.filter(e=>e.type==='start').length,0,'No effects may queue while audio is suspended');
    h.click('#btn-sound');resolveResume();await h.settle();
    assert.equal(h.$('#btn-sound').getAttribute('aria-pressed'),'false');assert.equal(h.contexts[0].state,'suspended');
    assert.ok(h.contexts[0].nodes.every(n=>!n.started||n.connections.length===0));
  });
  await integration('durak-keyboard-focus-does-not-play-other-selection',async h=>{
    const bridge=h.window.__GAME_TEST__;bridge.setManualMode(true);bridge.act({type:'start',seed:'corpus-durak-1',playerCount:2});
    h.click('[data-card="S6"]');const focused=h.$('[data-card="H7"]');focused.focus();
    const event=h.event(focused,'keydown',{key:'Enter',code:'Enter'});
    // LinkeDOM has no native activation; model it only after unprevented keydown.
    if(!event.defaultPrevented)focused.click();
    assert.equal(bridge.snapshot().position.revision,0);assert.equal(h.document.activeElement.getAttribute('data-card'),'H7');
    h.click('#btn-play');assert.equal(bridge.snapshot().position.table[0].attack,'H7');
  });
  await integration('durak-seeded-reset-visible-start',async h=>{
    const bridge=h.window.__GAME_TEST__;bridge.setManualMode(true);
    const start=seed=>{bridge.reset({seed});const button=h.$('[data-testid="start"]');
      assert.equal(Boolean(button.closest('[hidden]')),false,'Seeded reset must expose the real visible start control');
      button.click();return JSON.stringify(bridge.snapshot().position);};
    const first=start('corpus-durak-1');assert.equal(start('corpus-durak-1'),first,'Same seed and real Start must produce the same deal');
    assert.notEqual(start('different-visible-start-seed'),first);
  });
  await integration('durak-standard-audio-interface',async h=>{
    // The exact allowed audio module is also instantiated through the common
    // constructor. This is module-interface evidence, not an extra browser.
    const Audio=vm.runInContext(modules[2]+'\nGameAudio;',h.sandbox);
    const context=new h.window.AudioContext();await context.resume();
    const audio=new Audio(context,context.destination);
    assert.equal(typeof audio.tick,'function');audio.setState({enabled:true,volume:0,sfxVolume:.4,musicEnabled:false});
    audio.handleEvents([{id:'a',type:'attack'}]);const starts=h.audioEvents.filter(e=>e.type==='start').length;
    assert.ok(starts>0,'Zero music volume must not prevent new sound effects');
    audio.handleEvents([{id:'a',type:'attack'}]);assert.equal(h.audioEvents.filter(e=>e.type==='start').length,starts);
    audio.handleEvents(Array.from({length:40},(_,i)=>({id:'burst-'+i,type:'attack'})));
    assert.ok(context.nodes.filter(n=>n.started&&n.connections.length>0).length<=32,'Active source count remains bounded during a burst');
    audio.setState({volume:.8});assert.ok(context.nodes.some(n=>n.kind==='gain'&&n.gain.value===0),'MusicEnabled false gates only the music bus');
    assert.equal(audio.settings.sfxVolume,.4);audio.setState({sfxVolume:0});
    assert.equal(audio.settings.volume,.8);assert.equal(audio.sfxGain.gain.value,0);
    audio.setState({enabled:false});const muted=h.audioEvents.filter(e=>e.type==='start').length;
    audio.handleEvents([{id:'muted',type:'deal'}]);audio.setState({enabled:true,sfxVolume:.4});audio.handleEvents([{id:'muted',type:'deal'}]);
    assert.equal(h.audioEvents.filter(e=>e.type==='start').length,muted,'Muted events must be consumed, not queued or replayed');
    audio.dispose();audio.dispose();assert.equal(context.state,'running','Audio must not close a context it does not own');
    assert.ok(context.nodes.every(n=>n.connections.length===0));audio.tick();audio.handleEvents([{id:'disposed',type:'attack'}]);
    assert.equal(h.audioEvents.filter(e=>e.type==='start').length,muted);await context.close();
  },'trusted-module-interface');
  const failed=cases.filter(c=>!c.ok).length;
  const report={kind:'trusted-exact-html-durak-ui',status:failed?'failed':'passed',case_count:cases.length,
    html_case_count:cases.filter(c=>c.kind!=='trusted-module-interface').length,module_interface_case_count:cases.filter(c=>c.kind==='trusted-module-interface').length,
    started_at:startedAt,finished_at:new Date().toISOString(),
    html_sha256:sha(html),html_bytes:Buffer.byteLength(html),cases,passed:cases.filter(c=>c.ok).length,failed,
    limitations:['Complete recorded authored DOM game, not live generation','LinkeDOM plus explicit focus/timer/storage/WebAudio command models; no browser layout, actual touch or WebView',
      'Synthetic visibility/page events are not operating-system backgrounding or BFCache','Shared-storage comparison is best effort, not atomic cross-process synchronization','No subjective music/audio listening']};
  fs.writeFileSync(path.join(evidenceDir,'durak-ui-runtime.json'),JSON.stringify(report,null,2)+'\n');
  process.stdout.write(JSON.stringify(report)+'\n');if(report.failed)process.exitCode=1;
}
main().catch(error=>{console.error(error);process.exitCode=1;});
