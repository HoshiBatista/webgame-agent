/* Execute the exact real-Forge assembled, trusted authored camp corpus only.
 * Explicit DOM/focus/time/storage models + CPU Canvas are not a browser. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const crypto=require('node:crypto'),assert=require('node:assert/strict');
const {makeEnvironment}=require('./camp_ui_harness.cjs');
const corpus=path.resolve(__dirname,'..'),root=path.resolve(corpus,'../../..');
const evidenceDir=path.join(root,'docs/evidence/corpus');
const pipeline=JSON.parse(fs.readFileSync(path.join(evidenceDir,'camp.json'),'utf8'));
assert.equal(pipeline.kind,'recorded-corpus-pipeline-replay');assert.equal(pipeline.game,'camp');
assert.equal(pipeline.actual_model_calls,0);
const html=pipeline.artifact_html;
assert.equal(typeof html,'string','Run python scripts/test_corpus.py first to assemble the trusted corpus');
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
assert.equal(sha(html),pipeline.validation.artifact.html_sha256,'Stored pipeline artifact hash differs');
const modules=['engine.js','renderer.js','audio.js','ui.js'].map(name=>{
  const source=fs.readFileSync(path.join(corpus,name),'utf8');
  assert.equal(sha(source),pipeline.validation.artifact.files_sha256[name],`Pipeline artifact has stale ${name}`);
  return source;
});
const expectedScript=('"use strict";\n(() => {\n'+modules.join('\n')+'\nconst __mounted = mountGame(document.getElementById("game-root"));\n})();').replace(/<\/script/gi,'<\\/script');
const script=html.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(script);assert.equal(script[1],expectedScript,'Never execute source not exactly derived from the four fixed trusted modules');
const spec=JSON.parse(fs.readFileSync(path.join(corpus,'spec.json'),'utf8'));
function load(){
  const h=makeEnvironment(html);
  vm.runInContext(script[1],h.sandbox,{filename:'recorded-camp-assembled.html',timeout:10000});
  h.api=h.window.__ASHEN_TEST__;assert.ok(h.api);assert.ok(h.window.__GAME_TEST__?.ready);
  h.dispose=()=>h.api.dispose();return h;
}
function adapter(h){
  const bridge=()=>h.window.__GAME_TEST__;
  return {
    setManualMode:value=>bridge().setManualMode(value),reset:options=>bridge().reset(options),snapshot:()=>bridge().snapshot(),
    act:action=>bridge().act(action),advance:frames=>bridge().advance(frames),
    exportSave:()=>bridge().exportSave(),importSave:text=>bridge().importSave(text),
    setStorageFault:mode=>h.setStorageMode(mode==='normal'?'ok':mode),
    storageSnapshot:()=>({available:true,mode:h.state.storageMode==='ok'?'normal':h.state.storageMode,
      blocked_reads:h.storageCalls.filter(x=>x.operation==='get'&&x.mode==='denied').length,
      blocked_writes:h.storageCalls.filter(x=>x.operation==='set'&&['quota','denied'].includes(x.mode)).length,
      blocked_removals:h.storageCalls.filter(x=>x.operation==='remove'&&x.mode==='denied').length,denied_accesses:0}),
    click:selector=>h.click(selector),focus:selector=>h.$(selector).focus(),key:key=>h.key(key),
    readElement:(selector,property)=>{
      const list=h.document.querySelectorAll(selector),element=list[0];if(property==='count')return list.length;
      assert.ok(element,`Missing ${selector}`);if(property==='focused')return h.document.activeElement===element;
      if(property==='text')return element.textContent;if(property==='value')return element.value;
      if(property==='disabled')return !!element.disabled;if(property==='hidden')return !!element.hidden;
      throw new Error('Unsupported DOM observation');
    }
  };
}
async function main(){
  const {runScenario}=await import(path.join(root,'validator/scenario_runner.mjs'));
  const cases=[];
  for(const declaration of spec.qa_scenarios){
    const h=load();try{
      const result=await runScenario(adapter(h),{...declaration,steps:declaration.steps.map(step=>JSON.parse(step))});
      cases.push({id:declaration.id,kind:'declared-scenario',...result});
    }finally{h.dispose();}
  }
  async function integration(id,run){
    const h=load();try{await run(h);cases.push({id,kind:'authored-integration',ok:true});}
    catch(error){cases.push({id,kind:'authored-integration',ok:false,message:error.message});}
    finally{h.dispose();}
  }
  await integration('camp-real-dom-first-loop',async h=>{
    const enter=()=>{
      h.click('[data-action="depart"]');h.click('#ash-overlay [data-class="mage"]');
      h.change('#ash-seed-input','embers');h.click('#ash-overlay [data-action="new"]');
    };
    h.click('[data-npc="warden"]');h.click('#ash-overlay [data-quest="watch_1"]');
    assert.equal(h.api.getCampaign().meta.quests.watch_1.status,'active');
    h.click('#ash-overlay [data-action="resume"]');enter();
    const route=JSON.parse(fs.readFileSync(path.join(corpus,'first-loop-route.json'),'utf8'));
    for(const step of route.steps)for(let i=0;i<(step.repeat||1);i++)assert.equal(h.window.__GAME_TEST__.act(step.action),true);
    h.click('[data-npc="warden"]');h.click('#ash-overlay [data-quest="watch_1"][data-quest-action="claim"]');
    h.click('#ash-overlay [data-building="hearth"]');
    assert.equal(h.api.getCampaign().meta.buildings.hearth,1);
    h.click('#ash-overlay [data-action="resume"]');enter();
    assert.equal(h.api.getEngine().state.player.maxHp,32);assert.equal(h.api.getEngine().state.player.xp,0);
    assert.equal(h.api.getSaveState(),'saved');
  });
  await integration('camp-late-import-before-storage-event',async h=>{
    h.window.__GAME_TEST__.act({type:'acceptQuest',id:'watch_1'});
    const original=h.api.getCampaign(),before=original.serialize(),Campaign=original.constructor;
    const selected=new Campaign();selected.acceptQuest('garden_1');const selectedText=selected.serialize();
    const remote=new Campaign();remote.acceptQuest('forge_1');const remoteText=remote.serialize();
    const input=h.$('#ash-import');let finish;
    input.files=[{size:selectedText.length,text:()=>new Promise(resolve=>{finish=resolve;})}];
    h.event(input,'change');h.local.set(h.api.getSaveKey(),remoteText);finish(selectedText);await h.settle();
    assert.equal(h.local.get(h.api.getSaveKey()),remoteText);
    assert.equal(h.api.getCampaign(),original);assert.equal(original.serialize(),before);
    assert.equal(h.api.getSaveState(),'blocked');assert.equal(h.api.getScreen(),'pause');
  });
  await integration('camp-mount-disposal-releases-owned-loop-and-listeners',async h=>{
    assert.ok(h.frames.size>0);const owner=h.api.root;
    h.api.dispose();h.api.dispose();assert.equal(h.frames.size,0);assert.equal(owner.isConnected,false);
    assert.equal(h.window.__GAME_TEST__,undefined);assert.equal(h.window.__ASHEN_TEST__,undefined);
    const writes=h.storageCalls.filter(call=>call.operation==='set').length;
    h.event(h.window,'pagehide');h.key('KeyE');h.advance(2);
    assert.equal(h.storageCalls.filter(call=>call.operation==='set').length,writes,'Disposed listeners still wrote storage');
  });
  const report={kind:'trusted-camp-html-ui-regression',artifact:pipeline.validation.artifact,
    status:cases.every(test=>test.ok)?'passed':'failed',cases,case_count:cases.length,
    limitations:['Only the fixed reviewed source corpus was executed; no model-produced source is allowed in this host VM',
      'LinkeDOM and explicit focus/time/storage models do not test browser layout, WebView or real cross-process atomicity',
      'CPU Canvas code runs, but visual quality, actual audio playback and mobile-device performance are not claimed']};
  fs.writeFileSync(path.join(evidenceDir,'camp-ui-runtime.json'),JSON.stringify(report,null,2)+'\n');
  process.stdout.write(JSON.stringify(report)+'\n');if(report.status!=='passed')process.exitCode=1;
}
main().catch(error=>{console.error(error);process.exitCode=1;});
