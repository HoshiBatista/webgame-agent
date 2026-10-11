/* Execute ONLY the five trusted, fixed-path authored reference engines.
   This is developer regression code, not the production generated-game runner. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const names=['emberwatch','lamps','runner','camp','durak'];
function engineClass(name){
  assert.ok(names.includes(name));
  const source=fs.readFileSync(path.join(__dirname,name,'engine.js'),'utf8');
  return vm.runInNewContext(source+'\nGameEngine;',{TextEncoder});
}
async function main(){
  const {runScenario}=await import(path.join(__dirname,'../..','validator/scenario_runner.mjs'));
  const results=[],skipped=[];
  for(const name of names){
    const Engine=engineClass(name);let engine;
    const spec=JSON.parse(fs.readFileSync(path.join(__dirname,name,'spec.json'),'utf8'));
    const adapter={setManualMode:()=>{},reset:({seed})=>{engine=new Engine({seed:name==='emberwatch'?Number(seed):seed});},snapshot:()=>engine.snapshot(),
      act:action=>engine.act(action),advance:frames=>{for(let i=0;i<frames;i++){engine.act({type:'tick'});engine.drainEvents();}},
      exportSave:()=>engine.exportSave(),importSave:text=>engine.importSave(text),
      readElement:()=>{throw new Error('DOM unavailable in trusted engine-only corpus');},
      click:()=>{throw new Error('DOM unavailable');},focus:()=>{throw new Error('DOM unavailable');},key:()=>{throw new Error('DOM unavailable');}};
    for(const declaration of spec.qa_scenarios){
      const scenario={...declaration,steps:declaration.steps.map(x=>JSON.parse(x))};
      if(scenario.steps.some(step=>['storage_fault','lifecycle','reload'].includes(step.op))){
        skipped.push({game:name,id:scenario.id,reason:'Actual storage/UI behavior runs in the separate mandatory trusted HTML UI gate'});continue;
      }
      const result=await runScenario(adapter,scenario);results.push({game:name,id:scenario.id,...result});
      assert.ok(result.ok,`${name}/${scenario.id}: ${result.message}`);
    }
  }
  const {play}=require('./strategy.cjs');
  const campaigns=[play({seed:20261011,difficulty:'normal',strategy:'mixed',useMeteor:true}),play({seed:12345,difficulty:'normal',strategy:'arrows',useMeteor:false})];
  assert.equal(campaigns[0].status,'won');assert.equal(campaigns[1].status,'lost');
  const durak=require('./durak/qa/matches.cjs').runMatches(engineClass('durak'));
  process.stdout.write(JSON.stringify({kind:'trusted-engine-regression',scenario_count:results.length,scenarios:results,skipped_scenarios:skipped,campaigns,durak,
    limitations:['Explicit recorded sources only, no provider output was executed','Engine bridge tests do not test browser UI, Canvas rendering, actual audio or WebView']})+'\n');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
