/* Internal, browser-free QA. Explicit Web Audio test doubles, NOT an audio renderer.
 * Tracks synthesis data, scheduling, automation and node lifetime; never claims
 * browser playback quality, post-effect levels, or real-device listening coverage.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class TestParam {
  constructor(context, owner, name, initial = 0) { this.context = context; this.owner = owner; this.name = name; this._value = initial; this.events = []; }
  set value(value) { assert(Number.isFinite(value), `${this.name}: non-finite value`); this._value = value; }
  get value() { return this._value; }
  record(method, value, when, extra) {
    assert(Number.isFinite(value), `${this.name}: ${method} value must be finite`);
    assert(Number.isFinite(when) && when >= 0, `${this.name}: ${method} time must be nonnegative`);
    if (method === 'exponentialRampToValueAtTime') assert(value > 0, `${this.name}: exponential target must be positive`);
    this.events.push({method,value,when,extra,issuedAt:this.context.currentTime});
    this.context.automation.push({node:this.owner.id,param:this.name,method,value,when,extra,issuedAt:this.context.currentTime});
    return this;
  }
  setValueAtTime(v,t) { return this.record('setValueAtTime',v,t); }
  linearRampToValueAtTime(v,t) { return this.record('linearRampToValueAtTime',v,t); }
  exponentialRampToValueAtTime(v,t) { return this.record('exponentialRampToValueAtTime',v,t); }
  setTargetAtTime(v,t,constant) { assert(Number.isFinite(constant) && constant > 0); return this.record('setTargetAtTime',v,t,constant); }
  setValueCurveAtTime(values,t,duration) {
    assert(Number.isFinite(duration) && duration > 0); for (const v of values) assert(Number.isFinite(v));
    return this.record('setValueCurveAtTime',values[0],t,{values:Array.from(values),duration});
  }
  cancelScheduledValues(t) { assert(Number.isFinite(t) && t >= 0); this.events = this.events.filter(e => e.when < t); return this; }
  cancelAndHoldAtTime(t) { return this.cancelScheduledValues(t); }
}

class TestNode {
  constructor(context, kind) {
    this.context=context; this.kind=kind; this.id=++context.serial; this.connections=new Set(); this.connectionHistory=new Set(); this.disconnected=false;
    context.nodes.push(this);
    const specs = {gain:1,frequency:440,detune:0,Q:1,playbackRate:1,delayTime:0,pan:0,threshold:-24,knee:30,ratio:12,attack:.003,release:.25};
    for(const [key,value] of Object.entries(specs)) this[key]=new TestParam(context,this,key,value);
    this.type='sine'; this.buffer=null; this.loop=false; this.onended=null; this.startTime=null; this.stopTime=null; this.ended=false;
  }
  connect(target) { assert(target instanceof TestNode || target instanceof TestParam,'Unknown audio connection'); this.connections.add(target); this.connectionHistory.add(target); this.disconnected=false; return target; }
  disconnect(target) { if(target) this.connections.delete(target); else this.connections.clear(); this.disconnected=this.connections.size===0; }
  start(when=0,offset=0,duration) {
    assert(this.startTime===null,'Audio source started twice'); assert(Number.isFinite(when)&&when>=0); assert(Number.isFinite(offset)&&offset>=0);
    if(duration!==undefined) assert(Number.isFinite(duration)&&duration>=0);
    this.startTime=when; this.offset=offset; this.duration=duration;
    this.context.sources.push(this);
    this.context.starts.push({node:this.id,kind:this.kind,when,issuedAt:this.context.currentTime,mode:this.context.label});
  }
  stop(when=0) { assert(Number.isFinite(when)&&when>=0,'Invalid stop time'); this.stopTime=when; }
  setPeriodicWave(wave) { this.wave=wave; }
  addEventListener(name,fn) { if(name==='ended') this.onended=fn; }
  removeEventListener(name,fn) { if(name==='ended'&&this.onended===fn)this.onended=null; }
  naturalEnd() {
    if(this.kind==='bufferSource'&&!this.loop&&this.buffer) {
      const duration=this.duration===undefined?Math.max(0,this.buffer.duration-this.offset):this.duration;
      const rates=this.playbackRate.events.filter(e=>e.when<=this.startTime);
      const rate=rates.length?rates[rates.length-1].value:this.playbackRate.value;
      return this.startTime+duration/Math.max(.001,rate);
    }
    return Infinity;
  }
  endAt() { return Math.min(this.stopTime===null?Infinity:this.stopTime,this.naturalEnd()); }
}

class TestAudioContext {
  constructor({sampleRate=44100,state='running'}={}) {
    this.sampleRate=sampleRate; this.state=state; this.currentTime=0; this.serial=0;
    this.nodes=[]; this.sources=[]; this.buffers=[]; this.starts=[]; this.automation=[]; this.label='initial';
    this.destination=new TestNode(this,'destination'); this.maxActive=0;
  }
  createGain() {return new TestNode(this,'gain');}
  createOscillator() {return new TestNode(this,'oscillator');}
  createBufferSource() {return new TestNode(this,'bufferSource');}
  createBiquadFilter() {return new TestNode(this,'biquad');}
  createDynamicsCompressor() {return new TestNode(this,'compressor');}
  createConvolver() {return new TestNode(this,'convolver');}
  createDelay() {return new TestNode(this,'delay');}
  createStereoPanner() {return new TestNode(this,'panner');}
  createWaveShaper() {return new TestNode(this,'waveshaper');}
  createChannelMerger() {return new TestNode(this,'merger');}
  createChannelSplitter() {return new TestNode(this,'splitter');}
  createPeriodicWave(real,imag,options) {for(const v of [...real,...imag])assert(Number.isFinite(v));return {real,imag,options};}
  createBuffer(channels,length,sampleRate) {
    assert(Number.isInteger(channels)&&channels>0); assert(Number.isInteger(length)&&length>0); assert(Number.isFinite(sampleRate)&&sampleRate>0);
    const data=Array.from({length:channels},()=>new Float32Array(length));
    const b={numberOfChannels:channels,length,sampleRate,duration:length/sampleRate,getChannelData:c=>data[c],copyToChannel:(arr,c,offset=0)=>data[c].set(arr,offset),copyFromChannel:(arr,c,offset=0)=>arr.set(data[c].subarray(offset,offset+arr.length))};
    this.buffers.push(b); return b;
  }
  advance(to) {
    assert(to>=this.currentTime); this.currentTime=to;
    for(const node of this.sources) if(!node.ended&&node.endAt()<=to) {node.ended=true;if(node.onended)node.onended({target:node});}
    this.maxActive=Math.max(this.maxActive,this.sources.filter(n=>!n.ended&&n.startTime<=to&&n.endAt()>to).length);
  }
  resume(){this.state='running';return Promise.resolve();}
  suspend(){this.state='suspended';return Promise.resolve();}
  close(){this.state='closed';return Promise.resolve();}
}

function setup({sampleRate=44100,state='running'}={}) {
  const ctx=new TestAudioContext({sampleRate,state}), timers=new Map();let serial=0;
  const globals={console,Float32Array,Uint8Array,Math,performance:{now:()=>ctx.currentTime*1000},
    setInterval:(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms,repeat:true});return id;},clearInterval:id=>timers.delete(id),
    setTimeout:(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms,repeat:false});return id;},clearTimeout:id=>timers.delete(id)};
  globals.window=globals;globals.globalThis=globals;
  const source=fs.readFileSync(path.join(__dirname,'music.js'),'utf8');
  const sandbox=vm.createContext(globals);vm.runInContext(source+'\nglobalThis.__Music=AshenMusic;',sandbox,{timeout:10000,filename:'music.js'});
  const music=new sandbox.__Music(ctx,ctx.destination);
  const step=(seconds,interval=.025)=>{const until=ctx.currentTime+seconds;while(ctx.currentTime<until-1e-8){ctx.advance(Math.min(until,ctx.currentTime+interval));music.tick();}};
  return{ctx,music,step,timers};
}

function scanBuffers(ctx) {
  let samples=0,nonzero=0,peak=0,energy=0;
  for(const b of ctx.buffers)for(let channel=0;channel<b.numberOfChannels;channel++)for(const x of b.getChannelData(channel)){
    assert(Number.isFinite(x),'Generated audio buffer has NaN/Infinity');samples++;if(Math.abs(x)>1e-7)nonzero++;peak=Math.max(peak,Math.abs(x));energy+=x*x;
  }
  return {buffers:ctx.buffers.length,samples,nonzero,peak,rms:samples?Math.sqrt(energy/samples):0};
}

function paramAt(param, t) {
  const events = [...param.events].sort((a,b)=>a.when-b.when);
  let value=param.value, at=0, target=null;
  const advance=x=>target ? target.value+(value-target.value)*Math.exp(-(x-at)/target.constant) : value;
  for(const e of events){
    if(t<e.when){
      if(e.method==='linearRampToValueAtTime'&&e.when>at)return value+(e.value-value)*(t-at)/(e.when-at);
      if(e.method==='exponentialRampToValueAtTime'&&e.when>at&&value>0)return value*Math.pow(e.value/value,(t-at)/(e.when-at));
      return advance(t);
    }
    if(e.method==='setTargetAtTime'){value=advance(e.when);at=e.when;target={value:e.value,constant:e.extra};}
    else {value=e.value;at=e.when;target=null;}
  }
  return advance(t);
}

function dryReference() {
  const seconds=18,sampleRate=22050,{ctx,music,step}=setup({sampleRate});
  ctx.label='reference-explore';music.setState({enabled:true,volume:.55,mode:'explore'});step(seconds);
  const output=new Float64Array(Math.ceil(seconds*sampleRate));
  const gainPaths=(node,visited=new Set())=>{
    if(visited.has(node)||node.kind==='convolver')return[];
    if(node.kind==='destination')return[[]];
    const seen=new Set(visited);seen.add(node);const paths=[];
    for(const next of node.connectionHistory){
      if(!(next instanceof TestNode))continue;
      for(const tail of gainPaths(next,seen))paths.push(node.kind==='gain'?[node.gain,...tail]:tail);
    }
    return paths;
  };
  let mixedSources=0;const pitches=new Set();
  for(const source of ctx.sources){
    if(source.kind!=='bufferSource'||!source.buffer||source.startTime>=seconds)continue;
    const paths=gainPaths(source);if(!paths.length)continue;
    const buffer=source.buffer, rate=paramAt(source.playbackRate,source.startTime)*Math.pow(2,paramAt(source.detune,source.startTime)/1200);
    pitches.add(Number(rate.toFixed(5)));mixedSources++;
    const first=Math.max(0,Math.ceil(source.startTime*sampleRate)),last=Math.min(output.length,Math.ceil(source.endAt()*sampleRate));
    for(let i=first;i<last;i++){
      const t=i/sampleRate,position=(source.offset+(t-source.startTime)*rate)*buffer.sampleRate;
      const index=Math.floor(position),fraction=position-index;
      if(index<0||index>=buffer.length)continue;
      let signal=0;for(let c=0;c<buffer.numberOfChannels;c++){const data=buffer.getChannelData(c);signal+=data[index]*(1-fraction)+(data[index+1]||0)*fraction;}signal/=buffer.numberOfChannels;
      let gain=0;for(const params of paths)gain+=params.reduce((v,p)=>v*paramAt(p,t),1);
      output[i]+=signal*gain;
    }
  }
  assert(mixedSources>0,'Reference mix contains no supported buffer sources');
  let peak=0,energy=0,clipped=0,nonzero=0;const rmsPerSecond=[];
  for(let i=0;i<output.length;i++){const x=output[i];assert(Number.isFinite(x),'Reference mix contains NaN/Infinity');peak=Math.max(peak,Math.abs(x));energy+=x*x;if(Math.abs(x)>1)clipped++;if(Math.abs(x)>1e-6)nonzero++;}
  for(let second=0;second<seconds;second++){let sum=0;for(let i=second*sampleRate;i<(second+1)*sampleRate;i++)sum+=output[i]**2;rmsPerSecond.push(Math.sqrt(sum/sampleRate));}
  assert(nonzero>sampleRate,'Reference mix is silent or too short');
  const pcm=Buffer.alloc(44+output.length*2);pcm.write('RIFF',0);pcm.writeUInt32LE(pcm.length-8,4);pcm.write('WAVEfmt ',8);pcm.writeUInt32LE(16,16);pcm.writeUInt16LE(1,20);pcm.writeUInt16LE(1,22);pcm.writeUInt32LE(sampleRate,24);pcm.writeUInt32LE(sampleRate*2,28);pcm.writeUInt16LE(2,32);pcm.writeUInt16LE(16,34);pcm.write('data',36);pcm.writeUInt32LE(output.length*2,40);
  for(let i=0;i<output.length;i++)pcm.writeInt16LE(Math.round(Math.max(-1,Math.min(1,output[i]))*32767),44+i*2);
  fs.writeFileSync(path.join(__dirname,'qa-music-dry.wav'),pcm);
  console.log(JSON.stringify({test:'dry-reference-only',seconds,sampleRate,mixedSources,distinctPlaybackRates:pitches.size,peak,rms:Math.sqrt(energy/output.length),clippedSamples:clipped,rmsPerSecond,runtimeDSP:false,omitted:['convolution reverb branch','dynamics compression','browser/device output'],artifact:'qa-music-dry.wav'}));
  music.dispose();
}

function testLongRun() {
  const {ctx,music,step}=setup();music.setState({enabled:true,volume:1,mode:'boss'});
  const buffers=ctx.buffers.length,cache=music._cache.size,owned=music._ownedNodes.length;
  step(194);
  assert.equal(ctx.buffers.length,buffers);assert.equal(music._cache.size,cache);assert.equal(music._ownedNodes.length,owned);assert(music._voices.size<=48);
  for(const theme of [music._themeA,music._themeB])for(const bar of theme)assert.equal(bar.reduce((sum,event)=>sum+event[1],0),6,'A score bar must contain six eighth-notes');
  const report={seconds:194,completeScoreLoops:2,sources:ctx.starts.length,maxActive:ctx.maxActive,liveVoices:music._voices.size,cache,buffers,ownedNodes:owned};
  ctx.advance(ctx.currentTime+1800);const before=ctx.starts.length;music.tick();report.longGapBurst=ctx.starts.length-before;assert(report.longGapBurst<20);
  ctx.state='suspended';music.tick();assert.equal(music._voices.size,0);ctx.state='running';music.tick();
  music.dispose();assert.equal(music._voices.size,0);assert.equal(music._cache.size,0);assert.equal(music._ownedNodes.length,0);
  console.log(JSON.stringify({test:'two-score-loops-and-suspend',...report,disposeClearsOwnedCollections:true}));
}

function main(){
  const {ctx,music,step,timers}=setup();
  const modes=['menu','explore','battle','boss','victory','defeat'];const reports=[];
  for(const mode of modes){
    ctx.label=mode;music.setState({enabled:true,volume:.55,mode});
    const before=ctx.starts.length;step(12);
    const notes=ctx.starts.slice(before);assert(notes.length>0,`${mode}: no scheduled notes`);
    reports.push({mode,sources:notes.length,kindCounts:Object.fromEntries(['oscillator','bufferSource'].map(k=>[k,notes.filter(n=>n.kind===k).length]))});
  }
  const buffers=scanBuffers(ctx);if(buffers.buffers)assert(buffers.nonzero>0,'Generated buffers are silent');
  console.log(JSON.stringify({test:'score-and-buffers',reports,buffers,maxActiveSources:ctx.maxActive}));

  music.setState({enabled:true,volume:.55,mode:'explore'});
  const beforeRepeated=ctx.starts.length;
  for(let i=0;i<200;i++)music.setState({enabled:true,volume:.55,mode:'explore'});
  assert.equal(ctx.starts.length,beforeRepeated,'Unchanged settings synchronously start duplicate notes');
  ctx.label='stable-repeat';const repeatStart=ctx.starts.length;step(12);
  const repeatedNotes=ctx.starts.length-repeatStart;
  assert(repeatedNotes<1000,'Frequent setState appears to duplicate music loops');

  const beforeMuteAutomation=ctx.automation.length;
  music.setState({enabled:false,volume:.55,mode:'explore'});const mutedAt=ctx.currentTime;
  const beforeMute=ctx.starts.length;step(3);assert.equal(ctx.starts.length,beforeMute,'Disabled music schedules new notes');
  const runningAfterMute=ctx.sources.filter(n=>!n.ended&&n.startTime<=ctx.currentTime&&n.endAt()>ctx.currentTime);
  console.log(JSON.stringify({test:'repeat-and-mute',repeatedNotes,activeSourcesAfterThreeSecondsMuted:runningAfterMute.length,timers:timers.size,mutedAt,muteAutomation:ctx.automation.slice(beforeMuteAutomation).filter(a=>a.param==='gain').map(a=>({method:a.method,value:a.value,delay:a.when-mutedAt,constant:a.extra}))}));

  ctx.advance(ctx.currentTime+3600);ctx.label='resume';const beforeResume=ctx.starts.length;
  music.setState({enabled:true,volume:.55,mode:'explore'});music.tick();
  const resumed=ctx.starts.slice(beforeResume);assert(resumed.length<100,'Resume schedules a catch-up burst');
  assert(resumed.every(n=>n.when>=ctx.currentTime-.5),'Resume schedules historical notes');step(3);
  music.dispose();const beforeDisposed=ctx.starts.length;step(3);assert.equal(ctx.starts.length,beforeDisposed,'Disposed music schedules notes');
  const live=ctx.sources.filter(n=>!n.ended&&n.connections.size>0);
  assert.equal(live.length,0,'Live connected source remains after disposal');
  console.log(JSON.stringify({test:'resume-and-dispose',resumedImmediately:resumed.length,liveConnectedSourcesAfterDispose:live.length,timers:timers.size}));
  testLongRun();
  if(process.argv.includes('--dry-reference'))dryReference();
  console.log('PASS: explicit Web Audio doubles. No real audio playback or browser rendering claimed.');
}

if(require.main===module)main();
module.exports={TestAudioContext,TestNode,TestParam,setup,scanBuffers,paramAt,dryReference};
