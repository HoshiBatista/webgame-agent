// Actual UI-owned campaign bridge. No parallel engine and no state injection.
function uiCampaignAction(action){
  if(uiDisposed||!action||typeof action!=='object')return false;
  if(action.type==='pause'){
    if(action.value)showPause();else resumeGame();return true;
  }
  if(action.type==='freshCampaign')return uiFreshCampaign(action);
  if(action.type==='start')return startRun({seed:action.seed??campaign._forgeSeed,classId:action.classId??campaign._forgeClass});
  if(action.type==='choose'){
    if(!engine||engine.state.status!=='choice')return false;
    const before=campaign.serialize();choosePerk(action.id);return before!==campaign.serialize();
  }
  if(action.type==='return')return returnToCamp();
  if(action.type==='abandon'){
    const before=campaign.serialize();onAction('abandon-confirmed');return before!==campaign.serialize();
  }
  if(['acceptQuest','claimQuest','upgradeBuilding'].includes(action.type)){
    if(campaign.mode!=='camp')return false;
    const ok=campaign[action.type](action.id);
    if(ok){sessionRevision++;saveRun();renderHUD();sound.play(action.type==='acceptQuest'?'loot':'level');}
    toast(campaign.notice);return ok;
  }
  return perform(action);
}
function uiFreshCampaign({seed='embers',classId='mage'}={}){
  // Same explicit new-campaign action exposed by the corpus UI menu.
  const replacement=new GameEngine({seed,classId});
  installCampaign(replacement);saveRun();renderHUD();return true;
}
function uiSnapshot(){
  const snapshot=campaign.snapshot();snapshot.paused=screen==='pause';
  snapshot.persistence={status:saveState};return snapshot;
}
const uiBridge={ready:true,snapshot:uiSnapshot,act:uiCampaignAction,
  reset:options=>{uiFreshCampaign(options||{});return uiSnapshot();},
  setManualMode:enabled=>{uiManualMode=!!enabled;moveQueue=[];nextAutoStep=0;lastFrame=0;},
  advance:()=>{throw new Error('This turn-based game has no simulation advance operation');},
  exportSave:()=>campaign.serialize(),
  importSave:text=>({ok:loadRun(text)})};
window.__GAME_TEST__=uiBridge;
const uiController={dispose(){
  if(uiDisposed)return;uiDisposed=true;importTicket++;sessionRevision++;moveQueue=[];
  cancelAnimationFrame(uiRaf);for(const off of uiListeners.splice(0))off();
  sound.pageActive=false;
  if(sound.music)sound.music.dispose();
  if(sound.ctx){const ctx=sound.ctx;sound.ctx=null;ctx.onstatechange=null;try{Promise.resolve(ctx.close()).catch(()=>{});}catch(_){}}
  if(window.__GAME_TEST__===uiBridge)delete window.__GAME_TEST__;
  if(window.__ASHEN_TEST__&&window.__ASHEN_TEST__.root===root)delete window.__ASHEN_TEST__;
  style.remove();root.remove();
}};
if(window.__ASHEN_TEST_MODE__&&window.__ASHEN_TEST__)window.__ASHEN_TEST__.dispose=uiController.dispose;
return uiController;
}
