/* Trusted corpus compatibility surface. All rules remain in the reviewed
 * AshenEngine/AshenCampaign above. Never used as a generation template. */
class GameEngine extends AshenCampaign {
  constructor({seed='embers',classId='mage'}={}) {
    super(); this._forgeSeed=String(seed);this._forgeClass=classId;this._forgePaused=false;
  }
  reset({seed=this._forgeSeed,classId=this._forgeClass}={}) {
    Object.assign(this,new GameEngine({seed,classId}));return this.snapshot();
  }
  act(action) {
    if(!action||typeof action!=='object')return false;
    if(action.type==='pause'){this._forgePaused=!!action.value;return true;}
    if(this._forgePaused)return false;
    if(action.type==='start')return this.startRun({seed:action.seed??this._forgeSeed,classId:action.classId??this._forgeClass});
    if(action.type==='acceptQuest')return this.acceptQuest(action.id);
    if(action.type==='claimQuest')return this.claimQuest(action.id);
    if(action.type==='upgradeBuilding')return this.upgradeBuilding(action.id);
    if(action.type==='choose')return this.choose(action.id);
    if(action.type==='return')return this.returnToCamp();
    if(action.type==='abandon'){
      const ok=this.abandonRun();if(ok&&this.mode==='result')this.returnToCamp();return ok;
    }
    return super.act(action);
  }
  snapshot() {
    const campaign=JSON.parse(this.serialize());
    // Reload intentionally discards presentation events, never game rules.
    const events=campaign.engine?campaign.engine.state.events.map(event=>({...event,id:String(event.id)})):[];
    if(campaign.engine)campaign.engine.state.events=[];
    return {campaign,bonuses:this.getBonuses(),quests:this.getQuestViews(),buildings:this.getBuildingViews(),
      paused:this._forgePaused,events};
  }
  exportSave(){return this.serialize();}
  loadSave(text){return this.importSave(text).ok;}
  importSave(text){
    try{
      const restored=GameEngine.fromSave(text);
      restored._forgeSeed=this._forgeSeed;restored._forgeClass=this._forgeClass;
      Object.assign(this,restored);return {ok:true};
    }catch(_){return {ok:false};}
  }
  static fromSave(text){
    const restored=AshenCampaign.fromSave(text);
    Object.setPrototypeOf(restored,GameEngine.prototype);
    restored._forgeSeed=restored.engine?restored.engine.state.seed:'embers';
    restored._forgeClass=restored.engine?restored.engine.state.player.classId:'mage';
    restored._forgePaused=false;return restored;
  }
  dispose(){this._forgePaused=true;}
}
