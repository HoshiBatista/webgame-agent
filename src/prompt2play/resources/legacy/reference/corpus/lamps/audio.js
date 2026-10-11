// Small procedural cue source, owned by the fixture UI.
class GameAudio {
  constructor(ctx){this.ctx=ctx;this.enabled=false;this.nodes=new Set();this.ids=new Set();}
  setState(s){if('enabled'in s)this.enabled=!!s.enabled;}
  handleEvents(events){for(const e of events){if(this.ids.has(e.id))continue;this.ids.add(e.id);if(!this.enabled||!this.ctx)continue;const osc=this.ctx.createOscillator(),gain=this.ctx.createGain();osc.connect(gain);gain.connect(this.ctx.destination);osc.frequency.value=e.type==='jump'?440:660;gain.gain.setValueAtTime(.05,this.ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.001,this.ctx.currentTime+.12);osc.start();osc.stop(this.ctx.currentTime+.13);this.nodes.add(osc);osc.onended=()=>{osc.disconnect();gain.disconnect();this.nodes.delete(osc);};}if(this.ids.size>128)this.ids.clear();}
  tick(){}
  dispose(){for(const node of this.nodes){try{node.stop();}catch{}node.disconnect();}this.nodes.clear();this.ids.clear();}
}
