/* Trusted authored deterministic strategy bot. No HP/gold/wave/status overrides. */
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const sandbox={};vm.createContext(sandbox);vm.runInContext(fs.readFileSync(path.join(__dirname,'emberwatch/engine.js'),'utf8')+'\nglobalThis.Engine=GameEngine;',sandbox);const Engine=sandbox.Engine;
const plans={
  mixed:[['P4','archer'],['P5','cannon'],['P6','frost'],['P7','arcane'],['P11','cannon'],['P2','archer'],['P10','arcane'],['P3','frost'],['P9','arcane'],['P8','archer'],['P13','cannon'],['P1','archer'],['P12','archer'],['P14','arcane']],
  west:[['P1','archer'],['P2','cannon'],['P4','frost'],['P3','arcane'],['P5','cannon'],['P6','archer'],['P11','arcane'],['P7','frost'],['P10','cannon'],['P9','arcane'],['P8','archer'],['P13','cannon'],['P12','archer'],['P14','arcane']],
  arrows:[['P4','archer'],['P5','archer'],['P6','archer'],['P7','archer'],['P11','archer'],['P2','archer'],['P10','archer'],['P3','archer'],['P9','archer'],['P8','archer'],['P13','archer'],['P1','archer'],['P12','archer'],['P14','archer']]
};
function invest(engine,strategy){
  const s=engine.getState(),plan=plans[strategy],desired=Math.min(14,2+Math.floor(s.wave*1.1));
  let changed=true;
  while(changed){changed=false;
    if(s.towers.length<desired){const next=plan.find(([pad])=>!s.towers.some(t=>t.padId===pad));if(next&&engine.act({type:'build',padId:next[0],towerType:next[1]}).ok){changed=true;continue;}}
    const candidates=s.towers.filter(t=>t.level<3).sort((a,b)=>a.level-b.level || (a.type==='frost')-(b.type==='frost') || plan.findIndex(p=>p[0]===a.padId)-plan.findIndex(p=>p[0]===b.padId));
    for(const tower of candidates)if(engine.act({type:'upgrade',padId:tower.padId}).ok){changed=true;break;}
  }
}
function meteor(engine){
  const s=engine.getState();if(s.meteor.cooldown>0||s.enemies.length===0)return;
  let target=null,best=0,count=0;
  for(const e of s.enemies){if(e.x<0||e.x>1000||e.y<0||e.y>640)continue;
    let score=0,near=0;for(const o of s.enemies)if(Math.hypot(o.x-e.x,o.y-e.y)<=s.meteor.radius+o.radius){score+=Math.min(o.hp,180+s.wave*22)*(o.type==='boss'?1.2:1);near++;}
    if(score>best){target=e;best=score;count=near;}
  }
  if(target&&(count>=4||target.type==='boss'||(target.distance>s.pathLength*.68&&best>100)))engine.act({type:'meteor',x:target.x,y:target.y});
}
function play({seed=12345,difficulty='normal',strategy='mixed',useMeteor=true}={}){
  const engine=new Engine({seed,difficulty});engine.act({type:'start'});const waves=[];let frames=0,seen=0,checkpointsValidated=0;
  const completedCount=wave=>Array.from({length:wave},(_,i)=>engine.getWaveInfo(i+1).total).reduce((n,count)=>n+count,0);
  while(!['won','lost'].includes(engine.getState().phase)&&frames<60*2400){
    const s=engine.getState();
    if(s.phase==='build'){
      if(s.wave>seen){waves.push({wave:s.wave,lives:s.lives,gold:s.gold,towers:s.towers.length,kills:s.kills});seen=s.wave;}
      invest(engine,strategy);
      assert.equal(s.kills+s.stats.leaks,completedCount(s.wave),`Enemy accounting before wave ${s.wave+1}, ${difficulty}, seed ${seed}`);
      const save=engine.exportSave(),probe=new Engine();
      assert.ok(save,`Missing checkpoint before wave ${s.wave+1}`);
      assert.equal(probe.loadSave(save).ok,true,`Cannot resume actual checkpoint before wave ${s.wave+1}, ${difficulty}, seed ${seed}`);
      for(const key of ['wave','gold','lives','kills','score','time'])assert.equal(probe.getState()[key],s[key],`Checkpoint changed ${key}`);
      checkpointsValidated++;assert.equal(engine.act({type:'wave'}).ok,true);
    }
    if(useMeteor&&frames%12===0)meteor(engine);
    engine.update(1/60);engine.drainEvents();frames++;
  }
  const s=engine.getState();assert.ok(['won','lost'].includes(s.phase),`Simulation did not terminate: ${difficulty}, seed ${seed}`);
  if(s.phase==='won')assert.equal(s.kills+s.stats.leaks,completedCount(s.totalWaves),`Final enemy accounting: ${difficulty}, seed ${seed}`);
  return {seed,difficulty,strategy,useMeteor,status:s.phase,wave:s.wave,lives:s.lives,gold:s.gold,kills:s.kills,towers:s.towers.map(t=>({pad:t.padId,type:t.type,level:t.level})),damage:Math.round(s.stats.damageDealt),leaks:s.stats.leaks,meteors:s.stats.meteorsUsed,seconds:Math.round(frames/60),checkpointsValidated,waves};
}
module.exports={play,invest,meteor,Engine};
