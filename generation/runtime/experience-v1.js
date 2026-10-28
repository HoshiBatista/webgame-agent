/* Generic synthesis, vector playback and input. All media content comes from the game recipe. */
(() => {
  'use strict';
  const recipeNode = document.getElementById('gf-assets');
  const recipe = recipeNode ? JSON.parse(recipeNode.textContent) : null;
  const images = new Map(), instruments = new Map(), sounds = new Map();
  const imageLoads=[], graphicsErrors=[];
  let context, master, analyser, timer, button, tools, hostControlled = false;
  let muted = false, hostMuted = false, unlocked = false, playing = false, musicStart = 0, nextCycle = 0;
  let lastScheduled = -1, pausedPosition = 0, voicesPlayed = 0, drawCalls = 0, audioError = '';
  const voices = new Set(), lastEffect = new Map();
  try { muted = localStorage.getItem('gameforge:sound-muted') === '1'; } catch { /* opaque iframe */ }
  if (recipe) {
    if(recipe.music) recipe.music.notes.sort((a,b)=>a.beat-b.beat);
    for (const item of recipe.graphics) {
      const img = new Image();
      imageLoads.push(new Promise(resolve=>{
        img.onload=()=>resolve(true);
        img.onerror=()=>{graphicsErrors.push(item.id);resolve(false);};
      }));
      img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(item.svg);
      images.set(item.id, img);
    }
    recipe.instruments.forEach(item => instruments.set(item.id, item));
    recipe.sounds.forEach(item => sounds.set(item.id, item));
  }

  let safeProbe;
  function updateButton() {
    if (!button) return;
    button.textContent = muted ? '♪×' : '♪';
    button.title = muted ? 'Включить звук' : 'Выключить звук';
    button.setAttribute('aria-label', muted ? 'Включить звук' : 'Выключить звук');
    button.setAttribute('aria-pressed', String(!muted));
    tools.hidden = hostControlled;
  }
  function output() {
    if (!context || context.state === 'closed') return;
    const now = context.currentTime;
    master.gain.cancelScheduledValues(now);
    master.gain.setValueAtTime(master.gain.value, now);
    master.gain.linearRampToValueAtTime(muted || hostMuted || document.hidden ? 0 : .65, now + .025);
  }
  function setMuted(value) {
    muted = !!value;
    try { localStorage.setItem('gameforge:sound-muted', muted ? '1' : '0'); } catch { /* optional persistence */ }
    output(); updateButton();
  }
  function setHostControl(value) {
    hostControlled = true; hostMuted = !!value;
    // The embedding player's preference is authoritative while embedded.
    muted = false;
    document.documentElement.style.setProperty('--gf-tool-reserve','0px');
    output(); updateButton();
  }
  function ensureAudio() {
    if (context) return;
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) throw new Error('Web Audio unavailable');
    context = new Audio();
    master = context.createGain();
    const limiter = context.createDynamicsCompressor();
    limiter.threshold.value = -10; limiter.knee.value = 6; limiter.ratio.value = 12;
    limiter.attack.value = .003; limiter.release.value = .15;
    analyser = context.createAnalyser(); analyser.fftSize = 256;
    master.gain.value = muted || hostMuted || document.hidden ? 0 : .65;
    master.connect(limiter); limiter.connect(analyser); analyser.connect(context.destination);
  }
  function unlock(event, fromControl=false) {
    if (!recipe || !event.isTrusted || event.type === 'keydown' && event.repeat) return;
    if(!fromControl && event.target instanceof Element && event.target.closest('#gf-player-tools'))return;
    if (!recipe.sounds.length && !recipe.music) return;
    try {
      ensureAudio();
      const first = !unlocked;
      const wasRunning = context.state === 'running';
      const resumed = context.resume();
      if (first) { unlocked = true; startMusic(!wasRunning); }
      resumed.then(() => {
        if (first && !wasRunning && playing) {
          musicStart = context.currentTime + .03 - pausedPosition;
          nextCycle = 0; lastScheduled = -1;
          scheduleSafely();
        }
      }).catch(error => { audioError = String(error.message); });
    } catch (error) { audioError = String(error.message); }
  }
  addEventListener('pointerdown', unlock, {capture:true});
  addEventListener('keydown', unlock, {capture:true});

  function voice(instrument, frequency, endFrequency, duration, gain, when, channel='effect') {
    if (!context || context.state === 'closed' || voices.size >= 16 || !instrument) return;
    const start = Math.max(context.currentTime, when), end = start + duration + instrument.release;
    const source = instrument.wave === 'noise' ? context.createBufferSource() : context.createOscillator();
    if (instrument.wave === 'noise') {
      const buffer = context.createBuffer(1, Math.ceil(context.sampleRate * (duration + instrument.release)), context.sampleRate);
      const data = buffer.getChannelData(0);
      // Fixed seed makes this recipe repeatable; no downloaded samples.
      let seed = 1234567;
      for (let i=0;i<data.length;i++) { seed = (Math.imul(seed,1664525)+1013904223)>>>0; data[i] = seed/2147483648-1; }
      source.buffer = buffer;
    } else {
      source.type = instrument.wave;
      source.frequency.setValueAtTime(frequency,start);
      source.frequency.exponentialRampToValueAtTime(endFrequency, start+duration);
    }
    const filter = context.createBiquadFilter(); filter.type='lowpass'; filter.frequency.value=instrument.brightness;
    const envelope = context.createGain();
    envelope.gain.setValueAtTime(0,start);
    envelope.gain.linearRampToValueAtTime(gain,start+Math.min(instrument.attack,duration/2));
    envelope.gain.setValueAtTime(gain,start+duration);
    envelope.gain.linearRampToValueAtTime(0,end);
    source.connect(filter); filter.connect(envelope); envelope.connect(master);
    const entry = {source, filter, envelope, channel}; voices.add(entry); voicesPlayed++;
    source.onended = () => { source.disconnect(); filter.disconnect(); envelope.disconnect(); voices.delete(entry); };
    source.start(start); source.stop(end+.005);
  }
  function stopVoices(channel) {
    for (const entry of voices) {
      if (channel && entry.channel !== channel) continue;
      try { entry.source.stop(); } catch { /* already stopped */ }
      entry.source.disconnect(); entry.filter.disconnect(); entry.envelope.disconnect();
      voices.delete(entry);
    }
  }
  function sound(id) {
    const item = sounds.get(id);
    if (!item || !unlocked || !context || document.hidden || muted || hostMuted) return;
    const now = context.currentTime;
    if (now-(lastEffect.get(id) ?? -Infinity) < .06) return;
    lastEffect.set(id,now);
    try { voice(instruments.get(item.instrument),item.frequency,item.end_frequency,item.duration,item.gain,now); }
    catch (error) { audioError = String(error.message); }
  }
  function schedule() {
    if (!playing || !context || document.hidden || context.state !== 'running') return;
    const music = recipe.music, beatSeconds=60/music.bpm, length=music.beats*beatSeconds;
    const now=context.currentTime, horizon=now+.15;
    // Skip missed cycles rather than bursting queued notes after browser suspension.
    nextCycle=Math.max(nextCycle,Math.floor((now-musicStart)/length));
    for (let cycle=nextCycle; cycle<=nextCycle+1;cycle++) {
      for (let i=0;i<music.notes.length;i++) {
        const note=music.notes[i], at=musicStart+cycle*length+note.beat*beatSeconds;
        const ordinal=cycle*music.notes.length+i;
        if (ordinal<=lastScheduled || at>horizon) continue;
        if (at>=now && !muted && !hostMuted) {
          const hz=440*Math.pow(2,(note.note-69)/12);
          voice(instruments.get(note.instrument),hz,hz,note.duration*beatSeconds,note.gain,at,'music');
        }
        lastScheduled=ordinal;
      }
    }
    nextCycle=Math.max(0,Math.floor((now-musicStart)/length));
  }
  function scheduleSafely() {
    try { schedule(); } catch(error) { audioError=String(error.message); stopMusic(); }
  }
  function startMusic(deferFirst=false) {
    if (!recipe?.music || !unlocked || !context || playing) return;
    playing=true; musicStart=context.currentTime+.03-pausedPosition; nextCycle=0; lastScheduled=-1;
    if (!document.hidden) {
      timer=setInterval(scheduleSafely,80);
      if (!deferFirst) scheduleSafely();
    }
  }
  function stopMusic() {
    playing=false; clearInterval(timer); timer=undefined; pausedPosition=0; stopVoices('music');
  }
  document.addEventListener('visibilitychange', () => {
    output();
    if (document.hidden) {
      if (playing && context && recipe?.music) pausedPosition=Math.max(0,context.currentTime-musicStart)%(recipe.music.beats*60/recipe.music.bpm);
      clearInterval(timer); timer=undefined; stopVoices();
    } else if (playing) { playing=false; startMusic(); }
  });
  addEventListener('pagehide', () => { clearInterval(timer); stopVoices(); });

  function layout() {
    const width=document.documentElement.clientWidth, height=innerHeight;
    if(!safeProbe && document.body){
      safeProbe=document.createElement('div');
      safeProbe.style.cssText='position:fixed;visibility:hidden;pointer-events:none;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)';
      document.body.append(safeProbe);
    }
    const style=safeProbe?getComputedStyle(safeProbe):null;
    const safe={top:parseFloat(style?.paddingTop)||0,right:parseFloat(style?.paddingRight)||0,bottom:parseFloat(style?.paddingBottom)||0,left:parseFloat(style?.paddingLeft)||0};
    return {width,height,orientation:width>height?'landscape':'portrait',toolbar:hostControlled?0:64,safe};
  }
  function draw(ctx,id,x,y,w,h) {
    if (!ctx || typeof ctx.drawImage !== 'function' || typeof id !== 'string'
        || ![x,y,w,h].every(Number.isFinite))
      throw new TypeError('GameForgeExperience.draw(ctx,id,x,y,w,h): pass the Canvas context, a declared string asset ID and finite coordinates.');
    if (!images.has(id)) throw new RangeError('Unknown generated graphic: '+id);
    const img=images.get(id);
    if (img?.complete && img.naturalWidth) { ctx.drawImage(img,x,y,w,h); drawCalls++; }
  }

  function bindInput(actions, callback) {
    const cleanup=[], active=new Map(), keys=new Map();
    const listen=(target,name,fn,options) => { target.addEventListener(name,fn,options); cleanup.push(()=>target.removeEventListener(name,fn,options)); };
    function change(action,source,down) {
      const previous=active.get(action) || new Set();
      const had=previous.size>0;
      if (down) previous.add(source); else previous.delete(source);
      active.set(action,previous);
      if (had !== (previous.size>0)) callback({action,phase:previous.size?'down':'up'});
    }
    function release() {
      const ids=[...active.keys()].filter(id=>active.get(id).size);
      active.clear(); ids.forEach(action=>callback({action,phase:'up'}));
    }
    for (const action of actions) {
      for (const key of action.keys || []) keys.set(key,action.id);
      const element=action.selector ? document.querySelector(action.selector) : null;
      if (!element) continue;
      let pointerClickUntil=0;
      listen(element,'pointerdown', event => {
        if (event.button!==0) return;
        pointerClickUntil=performance.now()+750;
        event.preventDefault(); element.focus({preventScroll:true}); element.setPointerCapture(event.pointerId);
        change(action.id,'p'+event.pointerId,true);
      });
      for (const name of ['pointerup','pointercancel','lostpointercapture'])
        listen(element,name,event=>change(action.id,'p'+event.pointerId,false));
      // Native keyboard/assistive click, not the synthetic click following a pointer.
      listen(element,'keydown',()=>{pointerClickUntil=0;});
      listen(element,'click',event=> {
        if(performance.now()<pointerClickUntil){pointerClickUntil=0;return;}
        if(event.detail===0) { change(action.id,'click',true); change(action.id,'click',false); }
      });
    }
    const typing=target=>target instanceof Element && !!target.closest('input,textarea,select,[contenteditable="true"],#gf-player-tools');
    listen(window,'keydown',event=> {
      if (typing(event.target) || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
      if(['Enter',' '].includes(event.key) && event.target instanceof Element && event.target.closest('button'))return;
      const action=keys.get(event.code) || keys.get(event.key);
      if (!action) return;
      event.preventDefault(); change(action,'k'+(event.code||event.key),true);
    });
    listen(window,'keyup',event=> {
      const action=keys.get(event.code) || keys.get(event.key);
      if (action) change(action,'k'+(event.code||event.key),false);
    });
    listen(window,'blur',release);
    listen(document,'visibilitychange',()=> { if(document.hidden) release(); });
    return Object.freeze({release,dispose(){release(); cleanup.forEach(fn=>fn());}});
  }
  function mount() {
    if (!recipe) return;
    document.documentElement.style.setProperty('--gf-tool-reserve',hostControlled?'0px':'64px');
    tools=document.createElement('div'); tools.id='gf-player-tools';
    tools.style.cssText='position:fixed;top:max(8px,env(safe-area-inset-top));right:max(8px,env(safe-area-inset-right));z-index:2147483646';
    const shadow=tools.attachShadow({mode:'open'});
    const style=document.createElement('style');
    style.textContent='button{box-sizing:border-box;width:48px;height:48px;padding:8px;border:1px solid #999;border-radius:12px;background:#151a24;color:white;font:20px system-ui;cursor:pointer;touch-action:manipulation}button:focus-visible{outline:3px solid #ffcf52;outline-offset:2px}';
    button=document.createElement('button'); button.type='button';
    button.addEventListener('click',event=>{setMuted(!muted);if(!muted)unlock(event,true);});
    shadow.append(style,button); document.body.append(tools); updateButton();
  }
  Object.defineProperty(window,'GameForgeExperience',{value:Object.freeze({version:1,ready:Promise.all(imageLoads),draw,sound,startMusic,stopMusic,setMuted,setHostControl,layout,bindInput,
    inspect(){
      let peak=0;
      if(analyser){const samples=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(samples);for(const n of samples)peak=Math.max(peak,Math.abs(n));}
      return {version:1,graphicsReady:[...images.values()].filter(i=>i.complete&&i.naturalWidth).length,graphicsErrors:[...graphicsErrors],drawCalls,
        voicesPlayed,activeVoices:voices.size,musicPlaying:playing,muted:muted||hostMuted,state:context?.state||'locked',peak,audioError};
    }}),writable:false,configurable:false});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
  dispatchEvent(new Event('gameforge:experience-ready'));
})();
