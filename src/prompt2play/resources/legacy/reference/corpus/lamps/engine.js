// Trusted, deliberately small turn-based regression fixture; not model output.
class GameEngine {
  constructor({seed='lamps'}={}) { this.reset({seed}); }
  reset({seed='lamps'}={}) { this.state={seed,phase:'menu',paused:false,moves:0,lamps:[false,false,false]};this.events=[];this.sequence=0;return this.snapshot(); }
  snapshot() { return JSON.parse(JSON.stringify(this.state)); }
  act(action) {
    const s=this.state;
    if(action.type==='start'&&s.phase==='menu')s.phase='playing';
    else if(action.type==='pause'&&s.phase==='playing')s.paused=!!action.value;
    else if(action.type==='toggle'&&s.phase==='playing'&&!s.paused&&Number.isInteger(action.index)&&action.index>=0&&action.index<3){
      s.lamps[action.index]=!s.lamps[action.index];s.moves++;
      this.events.push({id:String(++this.sequence),type:'toggle',index:action.index});
      if(s.lamps.every(Boolean))s.phase='won';
    } else return {ok:false};
    return {ok:true};
  }
  drainEvents(){const result=this.events;this.events=[];return result;}
  dispose(){this.events=[];}
}
