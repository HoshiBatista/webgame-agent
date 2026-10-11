'use strict';
// Privileged rule oracle for exactly the authored Durak engine. It can inspect
// full card ownership; the real bot still receives only its filtered view.
const assert=require('node:assert/strict');
const plain=value=>JSON.parse(JSON.stringify(value));
function cards(state){return [...state.deck,...state.discard,...state.players.flatMap(p=>p.hand),...state.table.flatMap(p=>[p.attack,...(p.defense===null?[]:[p.defense])])];}
function inspectView(Engine,state,viewer){
  const view=Engine.rules.view(state,viewer),before=JSON.stringify(state);
  assert.equal(Object.hasOwn(view,'seed'),false);assert.equal(Object.hasOwn(view,'deck'),false);
  assert.equal(view.viewer,viewer);assert.deepEqual(plain(view.hand),plain(state.players[viewer].hand));
  assert.ok(view.players.every(p=>!Object.hasOwn(p,'hand')));
  const disposable=Engine.rules.view(state,viewer);disposable.hand.length=0;disposable.players[0].count=999;
  assert.equal(JSON.stringify(state),before,'Mutating an observation cannot alter the original position');
  return view;
}
function runMatches(Engine){
  const games=[];let actions=0,observations=0,voluntaryTakes=0,pickups=0;
  for(const playerCount of [2,3,4])for(let index=0;index<12;index++){
    const engine=new Engine({seed:`forge-durak-${playerCount}-${index}`,playerCount});
    assert.equal(engine.act({type:'start'}),true);let count=0,forced=0;
    while(engine.state.phase!=='finished'){
      assert.ok(count++<2000,'Finite reference match must finish within the authored budget');
      const before=plain(engine.state), ids=cards(before);
      assert.equal(ids.length,36);assert.equal(new Set(ids).size,36);
      assert.equal(Engine.rules.validate(engine.state).ok,true);
      let action;
      if(before.phase==='roundEnd')action={type:'continue'};
      else{
        const view=inspectView(Engine,engine.state,before.actor);observations++;
        if(before.actor===0&&view.phase==='defend'&&forced<2&&view.legalActions.some(a=>a.type==='defend')){
          action={type:'take'};forced++;voluntaryTakes++;
          const saved=engine.serialize();assert.equal(engine.importSave(saved).ok,true);
          assert.deepEqual(plain(engine.state),before,'Save/reload before a voluntary decision preserves the exact rules');
        }else action=before.actor===0?Engine.bots.chooseAction(view):{type:'stepBot'};
      }
      assert.equal(engine.act(action),true,JSON.stringify({playerCount,index,action}));actions++;
      const after=plain(engine.state),nextIds=cards(after);
      assert.deepEqual(nextIds.sort(),ids.sort(),'Every accepted action conserves all exact card identities');
      if(before.phase==='roundEnd'&&before.roundResult.kind==='taken'){
        const defender=after.players[before.defender].hand;
        for(const id of before.table.flatMap(p=>[p.attack,...(p.defense===null?[]:[p.defense])]))assert.equal(defender.filter(c=>c===id).length,1);
        const settled=JSON.stringify(after);assert.equal(engine.act({type:'continue'}),false);
        assert.equal(JSON.stringify(engine.state),settled,'Repeating settlement cannot draw or pick up again');pickups++;
      }
    }
    const final=engine.state;
    assert.equal(final.deck.length,0);assert.equal(final.table.length,0);assert.ok(final.result);
    const hands=final.players.filter(p=>p.hand.length>0);
    assert.equal(hands.length,final.result.draw?0:1);
    if(!final.result.draw)assert.equal(hands[0].id,final.result.durak);
    games.push({playerCount,seed:`forge-durak-${playerCount}-${index}`,actions:count,voluntaryTakes:forced,durak:final.result.durak,draw:final.result.draw});
  }
  assert.ok(voluntaryTakes>=36,'Human choices must actually exercise legal voluntary take, not only the default bot policy');
  return {kind:'trusted-durak-full-match-matrix',games:games.length,actions,filteredObservations:observations,voluntaryTakes,pickups,details:games,
    limitations:['Finite deterministic authored seeds, not a proof of all possible card games','Privileged test oracle sees full ownership; every bot input is filtered','No browser, DOM, audio audition or live-model quality evidence']};
}
module.exports={runMatches};
