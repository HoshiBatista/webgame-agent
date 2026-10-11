/* Compatibility adapter for the exact reviewed Durak engine above.
 * The original state machine remains authoritative; this file adds no rules. */
class GameEngine {
  constructor({seed='durak-corpus',playerCount=2}={}) {
    this.seed=String(seed);this.playerCount=playerCount;this.state=null;
    this.paused=false;this.events=[];this.session=0;
  }
  static get rules(){return globalThis.DurakEngine;}
  static get bots(){return globalThis.DurakBots;}
  reset({seed=this.seed,playerCount=this.playerCount}={}) {
    this.seed=String(seed);this.playerCount=playerCount;this.state=null;
    this.paused=false;this.events=[];this.session++;return this.snapshot();
  }
  act(action) {
    if(!action||typeof action!=='object'||Array.isArray(action))return false;
    if(action.type==='start'){
      try{this.state=GameEngine.rules.newGame({seed:action.seed??this.seed,playerCount:action.playerCount??this.playerCount});}
      catch(_){return false;}
      this.seed=this.state.seed;this.playerCount=this.state.players.length;
      this.paused=false;this.session++;this.recordEvent('deal');return true;
    }
    if(action.type==='pause'){this.paused=Boolean(action.value);return true;}
    if(this.paused||!this.state||this.state.phase==='finished')return false;
    // QA transports plain JSON across realms; reconstruct the canonical data
    // in the engine realm before the original strict plain-object validator.
    let chosen;try{chosen=JSON.parse(JSON.stringify(action));}catch(_){return false;}
    if(action.type==='stepBot') {
      if(this.state.actor===null||this.state.actor===0)return false;
      chosen=GameEngine.bots.chooseAction(GameEngine.rules.view(this.state,this.state.actor));
    } else if(action.type==='continue'){
      if(this.state.phase!=='roundEnd')return false;
    } else if(this.state.actor!==0||this.state.phase==='roundEnd')return false;
    try{const next=GameEngine.rules.step(this.state,chosen);this.state=next;this.recordEvent(chosen.type);return true;}
    catch(_){return false;}
  }
  recordEvent(type){this.events=[{id:this.session+':'+this.state.revision,type:this.state.phase==='finished'?(this.state.result.durak===0?'lose':'win'):type}];}
  snapshot() {
    // This public observation contains no opponent cards or deck order.
    const position=this.state?GameEngine.rules.view(this.state,0):null;
    const totalCards=this.state?this.state.deck.length+this.state.discard.length+
      this.state.players.reduce((n,p)=>n+p.hand.length,0)+
      this.state.table.reduce((n,p)=>n+1+Number(p.defense!==null),0):36;
    return {position,paused:this.paused,totalCards,events:JSON.parse(JSON.stringify(this.events))};
  }
  drainEvents(){const events=this.events;this.events=[];return events;}
  serialize(){return JSON.stringify({format:1,state:this.state,history:[]});}
  exportSave(){return this.serialize();}
  static parseSave(text){
    if(typeof text!=='string'||new TextEncoder().encode(text).byteLength>512000)return null;
    try{
      const saved=JSON.parse(text);
      if(!saved||saved.format!==1||!saved.state||!GameEngine.rules.validate(saved.state).ok)return null;
      return {state:saved.state,history:Array.isArray(saved.history)?saved.history.filter(x=>typeof x==='string'&&x.length<=240).slice(-80):[]};
    }catch(_){return null;}
  }
  loadSave(text){return this.importSave(text).ok;}
  importSave(text){
    const saved=GameEngine.parseSave(text);if(!saved)return {ok:false};
    this.state=saved.state;this.seed=this.state.seed;this.playerCount=this.state.players.length;
    this.paused=false;this.events=[];this.session++;return {ok:true};
  }
  dispose(){this.paused=true;this.events=[];}
}
