/* "Поход последней искры" — original score for Ashen Vault.
 * D minor / modal fantasy; 6/8 at dotted-quarter = 80; 64 bars = 96 seconds.
 * One transport, driven exclusively by tick(). No timers, fetches, or files.
 * API: new AshenMusic(ctx, destination); setState({enabled, volume, mode});
 *      tick(); dispose(). Victory resolves to D MAJOR (Picardy third).
 */
class AshenMusic {
  constructor(ctx, destination = ctx.destination) {
    this.ctx = ctx;
    this._disposed = false;
    this._enabled = false;
    this._volume = .55;
    this._mode = 'explore';
    this._step = .25;
    this._stepIndex = 0;
    this._nextTime = null;
    this._lastTime = null;
    this._wasRunning = false;
    this._terminalPlayed = false;
    this._finishUntil = null;
    this._voices = new Set();
    this._cache = new Map();
    this._ownedNodes = [];
    this._noiseState = 0x71a59c3d;

    const own = node => { this._ownedNodes.push(node); return node; };
    this._master = own(ctx.createGain());
    this._master.gain.value = 0;
    this._masterTarget = 0;
    this._compressor = own(ctx.createDynamicsCompressor());
    this._compressor.threshold.value = -16;
    this._compressor.knee.value = 18;
    this._compressor.ratio.value = 3.5;
    this._compressor.attack.value = .012;
    this._compressor.release.value = .22;
    this._compressor.connect(this._master);
    this._master.connect(destination);
    this._dry = own(ctx.createGain()); this._dry.gain.value = .88;
    this._dry.connect(this._compressor);
    this._send = own(ctx.createGain()); this._send.gain.value = .28;
    this._reverb = own(ctx.createConvolver());
    this._reverb.normalize = true;
    this._reverb.buffer = this._impulse();
    this._wet = own(ctx.createGain()); this._wet.gain.value = .28;
    this._send.connect(this._reverb); this._reverb.connect(this._wet); this._wet.connect(this._compressor);
    this._buses = {};
    for (const instrument of ['wind', 'strings', 'horn', 'lute', 'drum', 'tambourine']) {
      const bus = own(ctx.createGain());
      bus.gain.value = 0;
      bus.connect(this._dry); bus.connect(this._send);
      this._buses[instrument] = bus;
      this._cache.set(instrument, this._makeSample(instrument));
    }

    this._chords = {
      d: { bass: 38, notes: [50, 53, 57] },
      b: { bass: 34, notes: [46, 50, 53] },
      f: { bass: 41, notes: [53, 57, 60] },
      c: { bass: 36, notes: [48, 52, 55] },
      g: { bass: 43, notes: [55, 58, 62] },
      G: { bass: 43, notes: [55, 59, 62] },
      a: { bass: 45, notes: [57, 60, 64] },
      A: { bass: 45, notes: [57, 61, 64] }
    };
    // Each pair is [MIDI pitch, duration in eighth notes]; null is a rest.
    // Both sixteen-bar melodies are newly composed for this game.
    this._themeA = [
      [[62, 2], [65, 1], [69, 2], [65, 1]],
      [[70, 3], [69, 1], [65, 2]],
      [[69, 2], [72, 1], [69, 2], [67, 1]],
      [[64, 3], [67, 1], [72, 2]],
      [[74, 3], [69, 1], [65, 2]],
      [[67, 2], [70, 1], [69, 1], [67, 1], [65, 1]],
      [[64, 2], [69, 1], [70, 1], [69, 2]],
      [[73, 2], [70, 1], [69, 2], [64, 1]],
      [[62, 3], [65, 1], [69, 2]],
      [[72, 2], [67, 1], [64, 2], [67, 1]],
      [[70, 3], [65, 1], [62, 2]],
      [[69, 2], [67, 1], [64, 3]],
      [[67, 2], [70, 1], [74, 2], [72, 1]],
      [[69, 3], [65, 1], [64, 2]],
      [[64, 2], [65, 1], [69, 2], [67, 1]],
      [[73, 2], [69, 1], [64, 2], [null, 1]]
    ];
    this._themeB = [
      [[77, 3], [76, 1], [72, 2]],
      [[76, 2], [79, 1], [76, 2], [72, 1]],
      [[74, 2], [69, 1], [65, 1], [69, 2]],
      [[70, 3], [74, 1], [77, 2]],
      [[74, 2], [71, 1], [67, 2], [69, 1]],
      [[72, 3], [67, 1], [64, 2]],
      [[69, 2], [70, 1], [69, 2], [67, 1]],
      [[73, 3], [76, 1], [69, 2]],
      [[74, 2], [77, 1], [76, 2], [74, 1]],
      [[72, 3], [76, 1], [79, 2]],
      [[77, 2], [74, 1], [70, 2], [69, 1]],
      [[67, 3], [70, 1], [74, 2]],
      [[69, 2], [65, 1], [62, 2], [65, 1]],
      [[64, 2], [67, 1], [72, 2], [70, 1]],
      [[69, 3], [67, 1], [64, 2]],
      [[73, 2], [76, 1], [69, 2], [null, 1]]
    ];
    this._harmonyA = ['d', 'b', 'f', 'c', 'd', 'g', 'A', 'A', 'd', 'c', 'b', 'a', 'g', 'd', 'A', 'A'];
    this._harmonyB = ['f', 'c', 'd', 'b', 'G', 'c', 'A', 'A', 'd', 'c', 'b', 'g', 'd', 'c', 'A', 'A'];
    this._applyMix(ctx.currentTime || 0, true);
  }

  _random() {
    let x = this._noiseState;
    x ^= x << 13; x ^= x >>> 17; x ^= x << 5;
    this._noiseState = x >>> 0;
    return (this._noiseState / 4294967296) * 2 - 1;
  }

  _impulse() {
    const sr = this.ctx.sampleRate, length = Math.ceil(sr * 1.65);
    const buffer = this.ctx.createBuffer(2, length, sr);
    for (let channel = 0; channel < 2; channel++) {
      const samples = buffer.getChannelData(channel);
      let smooth = 0;
      for (let i = 0; i < length; i++) {
        const t = i / sr;
        smooth = smooth * .42 + this._random() * .58;
        const onset = t < .023 ? 0 : Math.min(1, (t - .023) / .015);
        samples[i] = smooth * Math.exp(-t * 4.6) * onset;
      }
    }
    return buffer;
  }

  _makeSample(instrument) {
    const sr = this.ctx.sampleRate;
    const durations = { wind: 3.6, strings: 6, horn: 3.8, lute: 2.4, drum: .72, tambourine: .25 };
    const baseMidi = instrument === 'wind' ? 69 : 57;
    const frequency = 440 * Math.pow(2, (baseMidi - 69) / 12);
    const stereo = instrument === 'strings' || instrument === 'lute';
    const duration = durations[instrument], length = Math.ceil(sr * duration);
    const buffer = this.ctx.createBuffer(stereo ? 2 : 1, length, sr);
    const left = buffer.getChannelData(0), right = stereo ? buffer.getChannelData(1) : null;
    const tau = Math.PI * 2;
    let phase = 0, secondPhase = .3, smoothNoise = 0, metallicNoise = 0;
    for (let i = 0; i < length; i++) {
      const t = i / sr, noise = this._random();
      const endFade = Math.min(1, (duration - t) / .045);
      smoothNoise = .93 * smoothNoise + .07 * noise;
      let value = 0, other = 0;
      if (instrument === 'wind') {
        const vibrato = .0022 * Math.min(1, t / .28) * Math.sin(tau * 4.8 * t);
        phase += tau * frequency * (1 + vibrato) / sr;
        const breath = (1 - Math.exp(-t * 28)) * (.97 + .025 * Math.sin(tau * 2.1 * t));
        value = breath * (.69 * Math.sin(phase) + .16 * Math.sin(2 * phase) + .065 * Math.sin(3 * phase) + .028 * Math.sin(4 * phase)) + smoothNoise * .036;
      } else if (instrument === 'strings') {
        phase += tau * frequency * (1 + .0013 * Math.sin(tau * 4.2 * t)) / sr;
        secondPhase += tau * frequency * 1.0042 / sr;
        const a = .45 * Math.sin(phase) + .13 * Math.sin(2 * phase) + .055 * Math.sin(3 * phase) + .025 * Math.sin(4 * phase);
        const b = .23 * Math.sin(secondPhase) + .06 * Math.sin(2 * secondPhase);
        value = a + b + smoothNoise * .011;
        other = a * .78 + b * 1.2 + .07 * Math.sin(secondPhase + .4);
      } else if (instrument === 'horn') {
        phase += tau * frequency * (1 + .0009 * Math.sin(tau * 3.7 * t)) / sr;
        const breath = .98 + .02 * Math.sin(tau * 1.7 * t);
        value = breath * (.61 * Math.sin(phase) + .24 * Math.sin(2 * phase) + .12 * Math.sin(3 * phase) + .055 * Math.sin(4 * phase) + .025 * Math.sin(5 * phase));
      } else if (instrument === 'lute') {
        const attack = 1 - Math.exp(-t * 600);
        value = attack * (
          .61 * Math.sin(tau * frequency * t) * Math.exp(-t * 3.1) +
          .25 * Math.sin(tau * frequency * 2.002 * t + .2) * Math.exp(-t * 4.8) +
          .12 * Math.sin(tau * frequency * 3.004 * t + .35) * Math.exp(-t * 7.5) +
          .065 * Math.sin(tau * frequency * 4.008 * t) * Math.exp(-t * 10) +
          smoothNoise * .055 * Math.exp(-t * 24));
        other = value * .84;
      } else if (instrument === 'drum') {
        phase += tau * (46 + 48 * Math.exp(-t * 24)) / sr;
        const attack = Math.min(1, t / .006);
        value = attack * (.83 * Math.sin(phase) * Math.exp(-t * 7.4) + .17 * Math.sin(phase * 1.58) * Math.exp(-t * 15) + smoothNoise * .26 * Math.exp(-t * 35));
      } else {
        metallicNoise = metallicNoise * .72 + noise * .28;
        const high = noise - metallicNoise;
        value = Math.min(1, t / .004) * Math.exp(-t * 21) * (.45 * high + .15 * Math.sin(tau * 4870 * t) + .11 * Math.sin(tau * 7193 * t));
      }
      left[i] = value * endFade;
      if (right) right[i] = other * endFade;
    }
    return { buffer, baseMidi, duration };
  }

  _param(param, value, time, smoothing = .15) {
    try {
      if (typeof param.cancelAndHoldAtTime === 'function') param.cancelAndHoldAtTime(time);
      else param.cancelScheduledValues(time);
      if (smoothing > 0) param.setTargetAtTime(value, time, smoothing);
      else param.setValueAtTime(value, time);
    } catch (_) { /* A closed context can race with page teardown. */ }
  }

  _applyMix(now, immediate = false) {
    const mixes = {
      explore: [1, .82, .58, .92, .82, .60],
      battle: [1.05, .90, .90, .96, 1.05, .85],
      boss: [1.08, 1.02, 1.08, .80, 1.18, .95],
      menu: [.50, .52, .12, .50, 0, 0],
      victory: [1, 1, .88, .75, .90, .60],
      defeat: [.65, .85, .38, .40, .40, 0]
    };
    const names = ['wind', 'strings', 'horn', 'lute', 'drum', 'tambourine'];
    const mix = mixes[this._mode];
    names.forEach((name, i) => this._param(this._buses[name].gain, mix[i], now, immediate ? 0 : .22));
  }

  _setMaster(value, now, smoothing) {
    // setState is called every visual frame. Leave an unchanged envelope alone.
    if (value === this._masterTarget) return;
    this._masterTarget = value;
    this._param(this._master.gain, value, now, smoothing);
  }

  setState({ enabled, volume, mode } = {}) {
    if (this._disposed) return;
    const now = Number.isFinite(this.ctx.currentTime) ? this.ctx.currentTime : 0;
    const wasEnabled = this._enabled, oldMode = this._mode;
    if (enabled !== undefined) this._enabled = Boolean(enabled);
    if (typeof volume === 'number' && Number.isFinite(volume)) this._volume = Math.max(0, Math.min(1, volume));
    if (['explore', 'battle', 'boss', 'menu', 'victory', 'defeat'].includes(mode)) this._mode = mode;
    if (this._mode !== oldMode) {
      const ending = this._mode === 'victory' || this._mode === 'defeat';
      const leavingEnding = oldMode === 'victory' || oldMode === 'defeat';
      this._applyMix(now);
      if (ending || leavingEnding) {
        this._stopVoices(now, .065);
        this._nextTime = null; this._terminalPlayed = false; this._finishUntil = null;
        if (leavingEnding) this._stepIndex = 0;
      }
    }
    if (!this._enabled) {
      this._setMaster(0, now, .016);
      if (wasEnabled) this._stopVoices(now, .05);
      this._nextTime = null; this._lastTime = null;
    } else {
      if (!wasEnabled) {
        this._nextTime = null; this._lastTime = null;
        this._stepIndex = Math.ceil(this._stepIndex / 6) * 6;
        // An interrupted ending can be replayed once, with old sources removed.
        this._terminalPlayed = false; this._finishUntil = null;
      }
      const ended = this._terminalPlayed && this._finishUntil !== null && now >= this._finishUntil;
      this._setMaster(ended ? 0 : this._volume * .86, now, .075);
    }
  }

  _voice(instrument, midi, start, duration, velocity, release = .12) {
    if (this._disposed || !this._enabled || this.ctx.state !== 'running' || this._voices.size >= 48) return;
    const sample = this._cache.get(instrument);
    if (!sample) return;
    const pitched = instrument !== 'drum' && instrument !== 'tambourine';
    const rate = pitched ? Math.pow(2, (midi - sample.baseMidi) / 12) : (midi || 1);
    const available = sample.duration / rate;
    const total = Math.min(duration + release, available - .004);
    if (!(total > .02)) return;
    const attack = instrument === 'wind' ? .035 : instrument === 'strings' ? .19 : instrument === 'horn' ? .075 : .006;
    const sustainEnd = Math.max(attack + .005, total - release);
    const source = this.ctx.createBufferSource(), gain = this.ctx.createGain();
    source.buffer = sample.buffer; source.playbackRate.value = rate;
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(velocity, start + Math.min(attack, total * .3));
    gain.gain.setValueAtTime(velocity, start + Math.min(sustainEnd, total * .9));
    gain.gain.linearRampToValueAtTime(0, start + total);
    source.connect(gain); gain.connect(this._buses[instrument]);
    const voice = { source, gain, start, end: start + total, closed: false };
    const cleanup = () => {
      if (voice.closed) return;
      voice.closed = true;
      this._voices.delete(voice);
      source.onended = null;
      try { source.disconnect(); } catch (_) {}
      try { gain.disconnect(); } catch (_) {}
    };
    voice.cleanup = cleanup; source.onended = cleanup;
    this._voices.add(voice);
    try { source.start(start); source.stop(start + total + .003); }
    catch (_) { cleanup(); }
  }

  _stopVoices(now, fade) {
    for (const voice of [...this._voices]) {
      if (voice.start > now || fade === 0) {
        try { voice.source.stop(now); } catch (_) {}
        voice.cleanup();
      } else {
        this._param(voice.gain.gain, 0, now, Math.max(.005, fade / 3));
        try { voice.source.stop(now + fade); } catch (_) { voice.cleanup(); }
        voice.end = Math.min(voice.end, now + fade);
      }
    }
  }

  _barInfo(bar) {
    if (bar < 8) return { melody: this._themeA[bar], chord: this._harmonyA[bar], energy: .82 + bar * .015, section: 0, transpose: 0 };
    if (bar < 24) return { melody: this._themeA[bar - 8], chord: this._harmonyA[bar - 8], energy: 1, section: 1, transpose: 0 };
    if (bar < 40) return { melody: this._themeB[bar - 24], chord: this._harmonyB[bar - 24], energy: 1.08, section: 2, transpose: 0 };
    if (bar < 48) return { melody: this._themeA[bar - 40], chord: this._harmonyA[bar - 40], energy: .92, section: 3, transpose: -12 };
    if (bar < 56) return { melody: this._themeB[bar - 40], chord: this._harmonyB[bar - 40], energy: 1.12, section: 4, transpose: 0 };
    return { melody: this._themeA[bar - 48], chord: this._harmonyA[bar - 48], energy: 1.02, section: 5, transpose: 0 };
  }

  _scheduleStep(index, time) {
    const bar = Math.floor(index / 6) % 64, eighth = index % 6;
    const info = this._barInfo(bar), chord = this._chords[info.chord], energy = info.energy;
    const fighting = this._mode === 'battle' || this._mode === 'boss';
    let cursor = 0;
    for (const [note, beats] of info.melody) {
      if (cursor === eighth && note !== null) {
        const lead = info.section === 3 ? 'horn' : 'wind';
        this._voice(lead, note + info.transpose, time + .008, beats * this._step * .91, .185 * energy, .12);
        // Restrained octave doubling at the summit, never another transport.
        if (this._mode === 'boss' && beats >= 2) this._voice('horn', note - 12, time + .024, beats * this._step * .82, .052, .16);
      }
      cursor += beats;
    }
    if (eighth === 0) {
      this._voice('strings', chord.bass, time, 1.32, .083 * energy, .55);
      this._voice('strings', chord.notes[2], time + .02, 1.24, .046 * energy, .48);
      if ((bar % 4 === 3 || info.section === 4 || fighting) && this._mode !== 'menu') {
        this._voice('horn', chord.notes[0], time + .032, .98, (fighting ? .102 : .077) * energy, .29);
      }
    }
    if (eighth === 3 && fighting) this._voice('strings', chord.notes[1], time, .56, .035, .32);
    const arp = [0, 2, 1, 2, 0, 1];
    const luteNote = chord.notes[arp[eighth]] + (eighth === 3 || (bar % 4 === 2 && eighth === 5) ? 12 : 0);
    this._voice('lute', luteNote, time + (eighth % 3 === 0 ? .005 : .016), .26, (eighth % 3 === 0 ? .112 : .082) * energy, .17);
    if (this._mode !== 'menu') {
      if (eighth === 0 || eighth === 3) this._voice('drum', eighth === 0 ? 1 : 1.16, time, .45, (eighth === 0 ? .195 : .14) * energy, .11);
      if (eighth === 1 || eighth === 2 || eighth === 4 || eighth === 5) this._voice('tambourine', 1 + (bar % 3) * .035, time + .018, .16, (eighth === 2 || eighth === 5 ? .056 : .038) * energy, .025);
      if (eighth === 5 && ((fighting && bar % 2 === 1) || bar % 8 === 7)) {
        this._voice('drum', 1.48, time + .125, .26, .088 * energy, .06);
      }
    }
  }

  _ending(now) {
    const t = now + .09;
    this._terminalPlayed = true;
    if (this._mode === 'victory') {
      // The minor journey opens into a warm D-major final sonority.
      this._voice('strings', 38, t, 3.8, .10, .7);
      this._voice('strings', 57, t, 3.6, .065, .7);
      this._voice('strings', 66, t + .72, 3, .055, .6);
      this._voice('horn', 50, t, .6, .13, .22);
      this._voice('horn', 57, t + .75, 2.2, .115, .6);
      for (const [offset, note, duration] of [[0, 74, .40], [.5, 78, .40], [1, 81, .40], [1.5, 74, 1.8]]) {
        this._voice('wind', note, t + offset, duration, .19, .25);
        this._voice('lute', note - 12, t + offset + .025, .32, .12, .12);
      }
      this._voice('drum', 1, t, .5, .20, .12);
      this._voice('drum', .9, t + 1.5, .6, .18, .12);
      this._finishUntil = t + 5.2;
    } else {
      this._voice('strings', 38, t, 3.2, .085, .8);
      this._voice('strings', 53, t + .04, 2.9, .045, .8);
      for (const [offset, note, duration] of [[0, 69, .55], [.7, 65, .55], [1.4, 64, .45], [2.05, 62, 1.1]]) {
        this._voice('wind', note, t + offset, duration, .13, .3);
      }
      this._voice('drum', .78, t + .03, .55, .15, .2);
      this._finishUntil = t + 4.9;
    }
  }

  tick() {
    if (this._disposed) return;
    const now = this.ctx.currentTime;
    if (!Number.isFinite(now)) return;
    // Also reap against the audio clock in case an onended notification is late.
    for (const voice of [...this._voices]) if (voice.end + .10 < now) voice.cleanup();
    if (this.ctx.state !== 'running') {
      if (this._wasRunning) this._stopVoices(now, 0);
      this._wasRunning = false; this._nextTime = null; this._lastTime = null;
      return;
    }
    this._wasRunning = true;
    if (!this._enabled) return;
    const longGap = this._lastTime !== null && now - this._lastTime > .65;
    this._lastTime = now;
    if (longGap) {
      this._stopVoices(now, .035);
      this._nextTime = null;
      this._stepIndex = Math.ceil(this._stepIndex / 6) * 6;
      // Terminal music does not replay after a tab has been absent for minutes.
      if (this._terminalPlayed) {
        this._finishUntil = now;
        this._setMaster(0, now, .04);
        return;
      }
    }
    if (this._mode === 'victory' || this._mode === 'defeat') {
      if (!this._terminalPlayed) this._ending(now);
      if (this._finishUntil !== null && now >= this._finishUntil) this._setMaster(0, now, .12);
      return;
    }
    if (this._nextTime === null) this._nextTime = now + .055;
    else if (this._nextTime < now) {
      // A missed frame must not play several historical notes at once. Keep the
      // musical grid, skip elapsed eighths, and schedule only future notes.
      const missed = Math.ceil((now - this._nextTime) / this._step);
      this._stepIndex = (this._stepIndex + missed) % 384;
      this._nextTime += missed * this._step;
    }
    let scheduled = 0;
    while (this._nextTime < now + .145 && scheduled < 3) {
      this._scheduleStep(this._stepIndex, this._nextTime);
      this._stepIndex = (this._stepIndex + 1) % 384;
      this._nextTime += this._step;
      scheduled++;
    }
  }

  dispose() {
    if (this._disposed) return;
    this._enabled = false;
    this._param(this._master.gain, 0, this.ctx.currentTime || 0, 0);
    this._stopVoices(this.ctx.currentTime || 0, 0);
    for (const node of this._ownedNodes) { try { node.disconnect(); } catch (_) {} }
    this._ownedNodes.length = 0; this._cache.clear();
    this._nextTime = null; this._disposed = true;
  }
}


class GameAudio extends AshenMusic {}
