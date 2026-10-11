/* Original short synthesized cues, complete voice ownership and the
 * common Forge audio API. The UI owns the supplied context and its promises.
 * This preserved card game has no ambient composition; its music bus is silent. */
class GameAudio {
  constructor(context,destination=context.destination){
    const audioContext=context,master=context.createGain(),audioMaster=context.createGain(),musicGain=context.createGain();
    master.connect(destination);audioMaster.connect(master);musicGain.connect(master);
    const settings={enabled:false,musicEnabled:true,volume:.55,sfxVolume:.7,mode:'menu'};
    const audioNodes=new Map();let noiseBuffer=null,disposed=false;
    this.sequence=0;this.seen=new Set();this.settings=settings;this.sfxGain=audioMaster;this.musicGain=musicGain;
    master.gain.value=0;audioMaster.gain.value=.24;musicGain.gain.value=.55;
  function trackSound(source, nodes) {
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      source.onended = null;
      nodes.forEach(node => { try { node.disconnect(); } catch (_) { /* Already disconnected. */ } });
      audioNodes.delete(source);
    };
    if(audioNodes.size>=32){
      const oldest=audioNodes.entries().next().value;
      try{oldest[0].stop();}catch(_){}oldest[1]();
    }
    audioNodes.set(source, release);
    source.onended = release;
  }

  function cancelSounds() {
    audioNodes.forEach((release, source) => {
      try { source.stop(); } catch (_) { /* A one-shot may already have ended. */ }
      release();
    });
  }

  function tone(frequency, start, duration, volume, type) {
    if (!audioContext || !audioMaster) return;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = type || 'sine';
    oscillator.frequency.setValueAtTime(frequency, start);
    gain.gain.setValueAtTime(0.001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.001, start + duration);
    oscillator.connect(gain);
    gain.connect(audioMaster);
    trackSound(oscillator, [oscillator, gain]);
    oscillator.start(start);
    oscillator.stop(start + duration + 0.02);
  }

  function flick(start, duration, volume) {
    if (!audioContext || !audioMaster) return;
    if (!noiseBuffer) {
      noiseBuffer = audioContext.createBuffer(1, Math.floor(audioContext.sampleRate * 0.12), audioContext.sampleRate);
      const samples = noiseBuffer.getChannelData(0);
      let noise = 314159;
      for (let i = 0; i < samples.length; i++) { noise = (Math.imul(noise, 1664525) + 1013904223) >>> 0; samples[i] = noise / 2147483648 - 1; }
    }
    const source = audioContext.createBufferSource();
    const filter = audioContext.createBiquadFilter();
    const gain = audioContext.createGain();
    source.buffer = noiseBuffer;
    filter.type = 'highpass';
    filter.frequency.value = 1500;
    gain.gain.setValueAtTime(volume, start);
    gain.gain.exponentialRampToValueAtTime(0.001, start + duration);
    source.connect(filter); filter.connect(gain); gain.connect(audioMaster);
    trackSound(source, [source, filter, gain]);
    source.start(start); source.stop(start + duration + 0.01);
  }

  function sound(kind) {
    if (!settings.enabled || settings.sfxVolume <= 0 || disposed || audioContext.state !== 'running') return;
    try {
      const now = audioContext.currentTime + 0.006;
      if (kind === 'deal') for (let i = 0; i < 6; i++) flick(now + i * 0.052, 0.06, 0.28);
      else if (kind === 'attack') { flick(now, 0.055, 0.32); tone(140, now + 0.014, 0.06, 0.18, 'triangle'); }
      else if (kind === 'defend') { flick(now, 0.05, 0.3); tone(225, now + 0.024, 0.08, 0.12, 'triangle'); }
      else if (kind === 'select') tone(450, now, 0.042, 0.07, 'sine');
      else if (kind === 'take') { flick(now, 0.10, 0.23); tone(130, now, 0.12, 0.10, 'triangle'); }
      else if (kind === 'continue') flick(now, 0.09, 0.27);
      else if (kind === 'win') [392, 493.88, 587.33, 783.99].forEach((note, index) => tone(note, now + index * 0.13, 0.28, 0.16, 'sine'));
      else if (kind === 'lose') [329.63, 293.66, 220].forEach((note, index) => tone(note, now + index * 0.14, 0.24, 0.13, 'sine'));
    } catch (_) { /* Audio failure never changes game state or prevents a legal move. */ }
  }


    this.cancel=cancelSounds;
    this.play=kind=>this.handleEvents([{id:'ui:'+String(++this.sequence),type:kind}]);
    this.handleEvents=events=>{
      if(disposed||!Array.isArray(events))return;
      for(const event of events){
        if(!event||typeof event.id!=='string'||typeof event.type!=='string'||this.seen.has(event.id))continue;
        this.seen.add(event.id);if(this.seen.size>256)this.seen.delete(this.seen.values().next().value);
        sound(event.type);
      }
    };
    this.setState=patch=>{
      if(!patch||typeof patch!=='object'||disposed)return;
      const previousEnabled=settings.enabled,previousSfx=settings.sfxVolume;
      for(const key of ['enabled','musicEnabled'])if(typeof patch[key]==='boolean')settings[key]=patch[key];
      for(const key of ['volume','sfxVolume'])if(typeof patch[key]==='number'&&Number.isFinite(patch[key]))settings[key]=Math.max(0,Math.min(1,patch[key]));
      if(typeof patch.mode==='string')settings.mode=patch.mode;
      const masterTarget=settings.enabled?1:0,sfxTarget=.24*settings.sfxVolume/.7,musicTarget=settings.musicEnabled?settings.volume:0;
      if(master.gain.value!==masterTarget)master.gain.value=masterTarget;
      if(audioMaster.gain.value!==sfxTarget)audioMaster.gain.value=sfxTarget;
      if(musicGain.gain.value!==musicTarget)musicGain.gain.value=musicTarget;
      if(previousEnabled&&!settings.enabled||previousSfx>0&&settings.sfxVolume===0)cancelSounds();
    };
    this.tick=()=>{}; // This original SFX-only game has no looping score to schedule.
    this.dispose=()=>{if(disposed)return;disposed=true;cancelSounds();
      for(const node of [audioMaster,musicGain,master])try{node.disconnect();}catch(_){}
      noiseBuffer=null;this.seen.clear();
    };
  }
}
