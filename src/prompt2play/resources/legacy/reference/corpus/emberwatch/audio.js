/* Original score: "The valley keeps its watch". D modal minor, eight-bar theme.
   Only unlock() creates Web Audio. No media, network, document listeners or imports. */
const AudioModes = new Set(['menu', 'build', 'wave', 'boss', 'won', 'lost', 'paused']);
const AudioMelody = [
  [0, 7, 10, 9, 7, 5, 3, 2], [0, 3, 7, null, 5, 3, 2, null],
  [2, 7, 9, 12, 9, 7, 5, 2], [3, 2, 0, null, -2, 0, null, null],
  [3, 7, 10, 14, 12, 10, 7, 5], [2, 5, 7, null, 10, 7, 5, 2],
  [2, 5, 9, 12, 14, 12, 9, 7], [5, 3, 2, -2, 0, null, null, null],
];
const AudioChords = [[50, 53, 57], [48, 52, 55], [43, 47, 50], [50, 53, 57],
  [46, 50, 53], [48, 52, 55], [43, 47, 50], [50, 53, 57]];
const AudioHz = midi => 440 * Math.pow(2, (midi - 69) / 12);
const AudioClamp = (value, fallback) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : fallback;

class GameAudio {
  constructor() {
    this.ctx = null;
    this.state = {enabled: false, musicEnabled: true, volume: .35, sfxVolume: .6, mode: 'menu'};
    this._disposed = false;
    this._unlocked = false;
    this._resumeBlocked = false;
    this._unlocking = null;
    this._syncQueued = null;
    this._syncRequested = false;
    this._timer = null;
    this._voices = new Set();
    this._samples = new Map();
    this._lastEventId = -1;
    this._cooldowns = Object.create(null);
    this._step = 0;
    this._next = 0;
    this._endingPlayed = false;
  }

  async unlock() {
    if (this._disposed) return false;
    if (this._unlocking) return this._unlocking;
    const Ctor = typeof AudioContext !== 'undefined' ? AudioContext
      : typeof webkitAudioContext !== 'undefined' ? webkitAudioContext : null;
    if (!Ctor) return false;
    if (!this.ctx) {
      try {
        this.ctx = new Ctor();
        this._master = this.ctx.createGain();
        this._music = this.ctx.createGain();
        this._sfx = this.ctx.createGain();
        this._master.gain.value = 0;
        this._music.gain.value = this.state.volume * .7;
        this._sfx.gain.value = this.state.sfxVolume;
        this._music.connect(this._master);
        this._sfx.connect(this._master);
        this._master.connect(this.ctx.destination);
        this._noise = this._makeNoise();
      } catch (_) {
        if (this.ctx) { try { await this.ctx.close(); } catch (_) {} }
        this.ctx = null;
        return false;
      }
    }
    const context = this.ctx;
    // Call resume while the trusted gesture is still on the stack.
    let resuming;
    this._resumeBlocked = false;
    try { resuming = context.resume(); } catch (_) { this._resumeBlocked = true; return false; }
    this._unlocking = Promise.resolve(resuming).then(async () => {
      if (this._disposed || context !== this.ctx) return false;
      this._unlocked = true;
      await this._sync();
      return !this._disposed;
    }).catch(() => { this._resumeBlocked = true; return false; }).finally(() => { this._unlocking = null; });
    return this._unlocking;
  }

  setState(partial = {}) {
    if (this._disposed || !partial || typeof partial !== 'object') return;
    const before = this.state;
    const next = {...before};
    for (const key of ['enabled', 'musicEnabled']) if (typeof partial[key] === 'boolean') next[key] = partial[key];
    for (const key of ['volume', 'sfxVolume']) if (key in partial) next[key] = AudioClamp(partial[key], before[key]);
    if (AudioModes.has(partial.mode)) next.mode = partial.mode;
    this.state = next;
    if (!this.ctx || !this._unlocked) return;
    const changed = Object.keys(next).some(key => before[key] !== next[key]);
    if (!changed && (this._resumeBlocked || (this._audible() ? this.ctx.state === 'running' : this.ctx.state === 'suspended'))) return;
    const changedMode = before.mode !== next.mode;
    if (changedMode || before.musicEnabled !== next.musicEnabled) {
      this._stopVoices('music');
      this._step = 0;
      this._next = 0;
      this._endingPlayed = false;
    }
    if (!this._audible()) {
      this._silence();
    } else {
      this._ramp(this._master.gain, 1, .035);
      this._ramp(this._music.gain, next.volume * .7, .035);
      this._ramp(this._sfx.gain, next.sfxVolume, .035);
      if (next.volume === 0) this._stopVoices('music');
      if (next.sfxVolume === 0) this._stopVoices('sfx');
      if (changedMode && (next.mode === 'won' || next.mode === 'lost')) this._stopVoices('sfx');
    }
    this._sync();
  }

  _audible() {
    return !this._disposed && this._unlocked && this.state.enabled
      && this.state.mode !== 'paused'
      && ((this.state.musicEnabled && this.state.volume > 0) || this.state.sfxVolume > 0);
  }

  _sync() {
    if (!this.ctx || this._disposed) return Promise.resolve();
    if (this._resumeBlocked) { this._silence(); return Promise.resolve(); }
    this._syncRequested = true;
    if (this._syncQueued) return this._syncQueued;
    const context = this.ctx;
    this._syncQueued = (async () => {
      // Re-read desired state after each async operation: pause/unpause may race.
      for (let attempt = 0; attempt < 4 && !this._disposed; attempt++) {
        this._syncRequested = false;
        const audible = this._audible();
        try {
          if (audible && context.state === 'suspended') await context.resume();
          else if (!audible && context.state === 'running') await context.suspend();
        } catch (_) { this._resumeBlocked = true; this._silence(); return; }
        if (audible !== this._audible()) { this._syncRequested = true; continue; }
        if (audible && context.state === 'running') {
          this._ramp(this._master.gain, 1, .035);
          this._ramp(this._music.gain, this.state.volume * .7, .035);
          this._ramp(this._sfx.gain, this.state.sfxVolume, .035);
          this._ensureTimer();
        } else this._silence();
        return;
      }
    })().finally(() => {
      this._syncQueued = null;
      // A request may arrive after the worker has finished synchronously but
      // before this Promise cleanup runs. Drain that request as well; merely
      // sharing the completed Promise would leave the last state unapplied.
      if (this._syncRequested && !this._disposed && !this._resumeBlocked) return this._sync();
    });
    return this._syncQueued;
  }

  _ramp(param, value, seconds) {
    const now = this.ctx.currentTime;
    param.cancelScheduledValues(now);
    param.setValueAtTime(param.value, now);
    param.linearRampToValueAtTime(value, now + seconds);
  }

  _silence() {
    if (!this.ctx) return;
    if (this._timer !== null) { clearInterval(this._timer); this._timer = null; }
    this._master.gain.cancelScheduledValues(this.ctx.currentTime);
    this._master.gain.setValueAtTime(0, this.ctx.currentTime);
    this._stopVoices();
    this._next = 0;
  }

  _ensureTimer() {
    if (this._timer !== null || !this._audible()) return;
    this._tick();
    this._timer = setInterval(() => this._tick(), 80);
  }

  _tick() {
    if (!this.ctx || !this._audible() || this.ctx.state !== 'running') return;
    const now = this.ctx.currentTime;
    for (const voice of this._voices) if (voice.end < now - .03) this._release(voice);
    if (!this.state.musicEnabled || this.state.volume === 0) return;
    if (this.state.mode === 'won' || this.state.mode === 'lost') {
      if (!this._endingPlayed) {
        this._endingPlayed = true;
        this._ending(this.state.mode === 'won', now + .035, 'music');
      }
      return;
    }
    // A throttled tab must never replay missed beats as a burst.
    if (!this._next || this._next < now - .35) this._next = now + .035;
    const tempo = this.state.mode === 'boss' ? 124 : this.state.mode === 'wave' ? 108 : 88;
    const beat = 30 / tempo;
    let scheduled = 0;
    while (this._next < now + .2 && scheduled++ < 4) {
      this._musicStep(this._step++ % 64, this._next, beat);
      this._next += beat;
    }
  }

  _musicStep(step, at, beat) {
    const bar = Math.floor(step / 8), tick = step % 8;
    const mode = this.state.mode;
    const calm = mode === 'menu' || mode === 'build';
    const intense = mode === 'boss';
    const chord = AudioChords[bar];
    if (tick === 0) {
      for (const midi of chord) this._tone(AudioHz(midi), at, beat * 7.6, calm ? .014 : .019, 'music', 'triangle', null, .32);
      this._tone(AudioHz(chord[0] - 12), at, beat * 3.3, .09, 'music', 'sine');
    }
    if (tick === 4 || (intense && tick % 2 === 0)) this._pluck(chord[0] - 12, at, .065, 'music');
    const note = AudioMelody[bar][tick];
    if (note !== null && (!calm || tick % 2 === 0 || tick === 7)) {
      this._pluck(62 + note, at, calm ? .15 : .19, 'music');
    }
    if (!calm && (tick === 0 || tick === 4 || (intense && tick === 6))) this._drum(at, intense ? .16 : .1, 'music', tick !== 0);
    if (!calm && tick % 2 === 1) this._noiseHit(at, .025, .07, 1800, 'music');
  }

  _register(nodes, sources, end, lane) {
    const limit = lane === 'music' ? 28 : 16;
    const sameLane = [...this._voices].filter(v => v.lane === lane);
    if (sameLane.length >= limit) this._release(sameLane[0]);
    if (this._voices.size >= 40) this._release(this._voices.values().next().value);
    const voice = {nodes, sources, end, lane};
    this._voices.add(voice);
    // onended and clock cleanup both use the same idempotent release path.
    for (const source of sources) source.onended = () => this._release(voice);
    return voice;
  }

  _release(voice) {
    if (!voice || !this._voices.delete(voice)) return;
    for (const source of voice.sources) {
      source.onended = null;
      try { source.stop(); } catch (_) {}
    }
    for (const node of voice.nodes) { try { node.disconnect(); } catch (_) {} }
  }

  _stopVoices(lane) {
    for (const voice of [...this._voices]) if (!lane || voice.lane === lane) this._release(voice);
  }

  _envelope(at, duration, gain, lane, attack = .008) {
    const envelope = this.ctx.createGain();
    envelope.gain.setValueAtTime(0, at);
    envelope.gain.linearRampToValueAtTime(gain, at + Math.min(attack, duration * .3));
    envelope.gain.exponentialRampToValueAtTime(Math.max(.0001, gain * .6), at + duration * .55);
    envelope.gain.exponentialRampToValueAtTime(.0001, at + duration);
    envelope.gain.setValueAtTime(0, at + duration + .015);
    envelope.connect(lane === 'music' ? this._music : this._sfx);
    return envelope;
  }

  _tone(frequency, at, duration, gain, lane, shape = 'sine', endFrequency = null, attack = .008) {
    const osc = this.ctx.createOscillator();
    osc.type = shape;
    osc.frequency.setValueAtTime(frequency, at);
    if (endFrequency) osc.frequency.exponentialRampToValueAtTime(endFrequency, at + duration);
    const envelope = this._envelope(at, duration, gain, lane, attack);
    osc.connect(envelope);
    this._register([osc, envelope], [osc], at + duration + .03, lane);
    osc.start(at); osc.stop(at + duration + .03);
  }

  _makeNoise() {
    const length = Math.ceil(this.ctx.sampleRate * .8);
    const buffer = this.ctx.createBuffer(1, length, this.ctx.sampleRate);
    const data = buffer.getChannelData(0);
    let seed = 71337;
    for (let i = 0; i < length; i++) { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; data[i] = seed / 2147483648 - 1; }
    return buffer;
  }

  _pluck(midi, at, gain, lane) {
    let buffer = this._samples.get(midi);
    if (!buffer) {
      const rate = this.ctx.sampleRate, period = Math.max(2, Math.round(rate / AudioHz(midi)));
      buffer = this.ctx.createBuffer(1, Math.ceil(rate * 1.5), rate);
      const data = buffer.getChannelData(0), ring = new Float32Array(period);
      let seed = (midi * 7919 + 101) >>> 0;
      for (let i = 0; i < period; i++) { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; ring[i] = seed / 2147483648 - 1; }
      for (let i = 0; i < data.length; i++) {
        const index = i % period;
        ring[index] = .498 * (ring[index] + ring[(index + 1) % period]);
        data[i] = ring[index] * Math.min(1, i / (rate * .002)) * Math.min(1, (data.length - i) / (rate * .08));
      }
      if (this._samples.size >= 32) this._samples.delete(this._samples.keys().next().value);
      this._samples.set(midi, buffer);
    }
    const source = this.ctx.createBufferSource(); source.buffer = buffer;
    const envelope = this._envelope(at, 1.5, gain, lane, .002);
    source.connect(envelope);
    this._register([source, envelope], [source], at + 1.53, lane);
    source.start(at); source.stop(at + 1.53);
  }

  _noiseHit(at, gain, duration, frequency, lane) {
    const source = this.ctx.createBufferSource(); source.buffer = this._noise;
    const filter = this.ctx.createBiquadFilter(); filter.type = 'lowpass'; filter.frequency.value = frequency;
    const envelope = this._envelope(at, duration, gain, lane, .003);
    source.connect(filter); filter.connect(envelope);
    this._register([source, filter, envelope], [source], at + duration + .03, lane);
    source.start(at); source.stop(at + duration + .03);
  }

  _drum(at, gain, lane, light = false) {
    this._tone(light ? 160 : 98, at, light ? .15 : .28, gain, lane, 'sine', light ? 75 : 38);
    this._noiseHit(at, gain * .24, .06, 650, lane);
  }

  _ending(won, at, lane) {
    const notes = won ? [62, 65, 69, 74, 73, 74] : [57, 53, 50, 45];
    for (let i = 0; i < notes.length; i++) this._pluck(notes[i], at + i * .24, won ? .24 : .16, lane);
    for (const note of won ? [50, 54, 57] : [38, 41, 45]) this._tone(AudioHz(note), at, 2.1, .04, lane, 'triangle', null, .15);
  }

  handleEvents(events) {
    if (this._disposed || !Array.isArray(events)) return;
    // Engine events are monotonically ordered: a high-water mark gives constant
    // memory deduplication, including events discarded while locked or muted.
    for (let i = Math.max(0, events.length - 512); i < events.length; i++) {
      const event = events[i];
      if (!event || !Number.isSafeInteger(event.id) || event.id <= this._lastEventId) continue;
      this._lastEventId = event.id;
      if (!this._audible() || !this.ctx || this.ctx.state !== 'running' || this.state.sfxVolume === 0) continue;
      this._event(event);
    }
  }

  _event(event) {
    const type = event.type, at = this.ctx.currentTime + .006;
    const allowed = ['start', 'build', 'upgrade', 'sell', 'shot', 'hit', 'kill', 'leak', 'wave-start', 'wave-complete', 'meteor', 'win', 'lose'];
    if (!allowed.includes(type)) return;
    const key = type === 'shot' ? 'shot-' + (['archer', 'cannon', 'frost', 'arcane'].includes(event.towerType) ? event.towerType : 'archer') : type;
    const interval = type === 'shot' ? .085 : type === 'hit' || type === 'kill' ? .11 : .18;
    if (at < (this._cooldowns[key] || -1)) return;
    this._cooldowns[key] = at + interval;
    const lane = 'sfx';
    if (type === 'shot') {
      if (event.towerType === 'cannon') { this._drum(at, .32, lane); this._noiseHit(at, .12, .18, 700, lane); }
      else if (event.towerType === 'frost') { this._tone(980, at, .18, .035, lane, 'sine', 510); this._noiseHit(at, .035, .14, 3500, lane); }
      else if (event.towerType === 'arcane') { this._tone(420, at, .13, .065, lane, 'triangle', 840); this._pluck(81, at, .08, lane); }
      else { this._noiseHit(at, .09, .07, 2900, lane); this._tone(650, at, .055, .04, lane, 'triangle', 280); }
    } else if (type === 'hit') this._noiseHit(at, .028, .045, 1100, lane);
    else if (type === 'kill') this._tone(event.enemyType === 'boss' ? 105 : 180, at, .14, .045, lane, 'sine', 65);
    else if (type === 'leak') { this._tone(110, at, .4, .15, lane, 'triangle', 72); this._drum(at, .13, lane); }
    else if (type === 'meteor') { this._noiseHit(at, .24, .7, 1200, lane); this._tone(220, at, .62, .22, lane, 'sine', 32); this._drum(at + .06, .2, lane); }
    else if (type === 'win' || type === 'lose') { if (!this.state.musicEnabled || this.state.volume === 0) this._ending(type === 'win', at, lane); }
    else {
      const phrase = type === 'upgrade' ? [62, 69, 74] : type === 'wave-start' ? [50, 57, 62]
        : type === 'wave-complete' ? [69, 74, 77] : type === 'sell' ? [81, 76] : type === 'build' ? [57, 62] : [62, 69];
      phrase.forEach((midi, index) => this._pluck(midi, at + index * .09, .2, lane));
    }
  }

  dispose() {
    if (this._disposed) return;
    this._disposed = true;
    this._silence();
    const context = this.ctx;
    for (const node of [this._music, this._sfx, this._master]) if (node) { try { node.disconnect(); } catch (_) {} }
    this._samples.clear();
    this._noise = null;
    this.ctx = null;
    this._unlocked = false;
    if (context) { try { Promise.resolve(context.close()).catch(() => {}); } catch (_) {} }
  }
}
