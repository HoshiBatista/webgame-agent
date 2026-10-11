/* Ashen Vault: self-contained procedural Canvas renderer. */
class AshenRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: false });
    this.width = 1;
    this.height = 1;
    this.dpr = 1;
    this.transform = null;
    this.reset();
  }

  reset() {
    this.positions = new Map();
    this.eventIds = new Set();
    this.eventOrder = [];
    this.pending = [];
    this.particles = [];
    this.labels = [];
    this.rings = [];
    this.flashes = [];
    this.shake = 0;
    this.clock = 0;
    this.lastTime = null;
    this.floorKey = null;
    this.state = null;
    this.transform = null;
    this.reduceMotion = false;
  }

  pushEvents(events) {
    if (!Array.isArray(events)) return;
    for (const event of events) {
      if (!event || typeof event !== 'object') continue;
      // Engine events have stable IDs. Object identity also handles ID-less callers.
      const key = event.id == null ? event : event.id;
      if (this.eventIds.has(key)) continue;
      this.eventIds.add(key);
      this.eventOrder.push(key);
      this.pending.push({ ...event });
      if (this.eventOrder.length > 2048) this.eventIds.delete(this.eventOrder.shift());
    }
  }

  hitTest(clientX, clientY) {
    if (!this.transform || !this.state) return null;
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const px = (clientX - rect.left) * this.width / rect.width;
    const py = (clientY - rect.top) * this.height / rect.height;
    if (px < 0 || py < 0 || px >= this.width || py >= this.height) return null;
    const { x, y, tile } = this.transform;
    const gx = Math.floor((px - x) / tile);
    const gy = Math.floor((py - y) / tile);
    return gx >= 0 && gy >= 0 && gx < this.state.w && gy < this.state.h ? { x: gx, y: gy } : null;
  }

  _resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.width = Math.max(1, Math.round(rect.width || this.canvas.clientWidth || 800));
    this.height = Math.max(1, Math.round(rect.height || this.canvas.clientHeight || 600));
    this.dpr = Math.min(2, Math.max(1, typeof devicePixelRatio === 'number' ? devicePixelRatio : 1));
    const w = Math.round(this.width * this.dpr);
    const h = Math.round(this.height * this.dpr);
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.ctx.imageSmoothingEnabled = true;
  }

  _hash(x, y, salt = 0) {
    let a = (x * 374761393 + y * 668265263 + salt * 1442695041) | 0;
    a = Math.imul(a ^ (a >>> 13), 1274126177);
    return ((a ^ (a >>> 16)) >>> 0) / 4294967295;
  }

  _seen(x, y) {
    return !this.state.seen || !!(this.state.seen[y] && this.state.seen[y][x]);
  }

  _visible(x, y) {
    return !this.state.visible || !!(this.state.visible[y] && this.state.visible[y][x]);
  }

  _floor(x, y) {
    const row = this.state.tiles[y];
    return !!(row && row[x] > 0);
  }

  _position(id, entity, instant = false) {
    const hero = id === 'player';
    let p = this.positions.get(id);
    if (!p) {
      p = { x: entity.x, y: entity.y, fx: entity.x, fy: entity.y, tx: entity.x, ty: entity.y, at: this.clock,
        facing: 'down', walkAt: -Infinity, walkPhase: 0, walkWeight: 0 };
      this.positions.set(id, p);
    }
    if (instant) {
      if (hero && (p.tx !== entity.x || p.ty !== entity.y)) p.facing = this._stepFacing(entity.x-p.tx,entity.y-p.ty);
      p.x = p.fx = p.tx = entity.x;
      p.y = p.fy = p.ty = entity.y;
      p.at = this.clock;
      p.walkAt = -Infinity;
      return p;
    }
    const age = Math.min(1, Math.max(0, (this.clock - p.at) / (hero ? 195 : 115)));
    const ease = hero ? age * age * (3 - 2 * age) : 1 - Math.pow(1 - age, 3);
    p.x = p.fx + (p.tx - p.fx) * ease;
    p.y = p.fy + (p.ty - p.fy) * ease;
    if (p.tx !== entity.x || p.ty !== entity.y) {
      const teleport = instant || Math.abs(p.tx - entity.x) + Math.abs(p.ty - entity.y) > 3;
      if (hero) {
        const pose = this._heroPose(p);
        p.facing = this._stepFacing(entity.x-p.tx,entity.y-p.ty);
        p.walkPhase = pose.phase;
        p.walkWeight = pose.amount;
        p.walkAt = teleport ? -Infinity : this.clock;
      }
      p.fx = teleport ? entity.x : p.x;
      p.fy = teleport ? entity.y : p.y;
      p.tx = entity.x;
      p.ty = entity.y;
      p.at = this.clock;
      if (teleport) { p.x = entity.x; p.y = entity.y; }
    }
    return p;
  }

  _stepFacing(dx, dy) {
    return Math.abs(dx) > Math.abs(dy) ? dx < 0 ? 'left' : 'right' : dy < 0 ? 'up' : 'down';
  }

  _heroPose(p) {
    // The gait advances only after a real tile change. A tile is half a stride;
    // subsequent tiles continue the same cycle, then the limbs settle to rest.
    const elapsed = this.clock - p.walkAt;
    const live = Number.isFinite(elapsed) && elapsed >= 0;
    const phase = (p.walkPhase || 0) + (live ? Math.min(elapsed,195) / 195 * Math.PI : 0);
    const ramp = Math.min(1, Math.max(0, elapsed / 38));
    const attack = ramp * ramp * (3 - 2 * ramp);
    const release = Math.min(1, Math.max(0, (elapsed - 195) / 135));
    const fade = 1 - release * release * (3 - 2 * release);
    const amount = !live || this.reduceMotion ? 0 : ((p.walkWeight || 0) + (1 - (p.walkWeight || 0)) * attack) * fade;
    return { amount, phase, facing: p.facing || 'down', stride: Math.cos(phase) * amount,
      leftLift: Math.max(0, Math.sin(phase)) * amount,
      rightLift: Math.max(0, -Math.sin(phase)) * amount,
      bounce: -Math.abs(Math.sin(phase)) * amount * 1.6 };
  }

  _emitEvents() {
    for (const event of this.pending) {
      const x = Number.isFinite(event.x) ? event.x : this.state.player.x;
      const y = Number.isFinite(event.y) ? event.y : this.state.player.y;
      if (!this._visible(x, y) && event.type !== 'floor' && event.type !== 'level') continue;
      const type = event.type;
      const color = event.color || (type === 'heal' ? '#7fe0bc' : type === 'cast' ? '#9adfdc' : type === 'loot' || type === 'level' ? '#f2cd80' : '#efa18c');
      const counts = { hit: 12, death: 24, cast: 15, heal: 10, loot: 9, level: 32, step: 2, floor: 18 };
      const n = this.reduceMotion ? 0 : counts[type] || 6;
      for (let i = 0; i < n; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = (0.35 + Math.random() * 1.8) * (type === 'step' ? 0.18 : 1);
        const life = type === 'step' ? 250 : 350 + Math.random() * 420;
        this.particles.push({ x: x + 0.5, y: y + 0.55, vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed - (type === 'heal' || type === 'level' ? 1 : 0.4),
          size: type === 'step' ? 0.035 : 0.025 + Math.random() * 0.035,
          born: this.clock, life, color: type === 'step' ? '#9b927c' : color });
      }
      if (type === 'hit') {
        this.flashes.push({ x, y, until: this.clock + 160 });
        if (!this.reduceMotion && x === this.state.player.x && y === this.state.player.y) this.shake = Math.min(8, this.shake + 4);
      }
      if (!this.reduceMotion && ['cast', 'heal', 'level', 'floor', 'death'].includes(type)) {
        this.rings.push({ x: x + 0.5, y: y + 0.55, born: this.clock, life: type === 'level' ? 850 : 450, color, type,
          tx: event.tx == null ? null : event.tx + 0.5, ty: event.ty == null ? null : event.ty + 0.5 });
      }
      const eventWords = { warning: 'ОПАСНОСТЬ', aim: 'ПРИЦЕЛ', nova: 'КОЛЬЦО ПЕПЛА',
        blast: 'ВЗРЫВ', arrow: '', bomber: '', bolt: 'ИСКРА', critical: 'КРИТИЧЕСКИЙ', crit: 'КРИТИЧЕСКИЙ', miss: 'ПРОМАХ',
        chest: 'СОКРОВИЩЕ', shrine: 'БЛАГОСЛОВЕНИЕ', fountain: 'ЖИВАЯ ВОДА',
        rat: '', skeleton: '', archer: '', sentinel: '', boss: '', player: '', brute: '', wisp: '' };
      let label = Object.prototype.hasOwnProperty.call(eventWords, event.text) ? eventWords[event.text] : event.text;
      if (type === 'hit' && event.amount != null && (event.amount !== 0 || !label)) label = '−' + Math.abs(event.amount);
      if (type === 'heal' && event.amount != null) label = '+' + Math.abs(event.amount);
      if (label && type !== 'step' && type !== 'floor') {
        this.labels.push({ x: x + 0.5, y: y + 0.12, text: String(label), color, born: this.clock, life: 1000 });
      }
    }
    this.pending.length = 0;
    if (this.particles.length > 420) this.particles.splice(0, this.particles.length - 420);
    if (this.labels.length > 30) this.labels.splice(0, this.labels.length - 30);
  }

  draw(state, timeMs, { mapMode = false, paused = false, hover = null, reduceMotion = false } = {}) {
    if (!state || !state.tiles || !state.player || !this.ctx) return;
    this._resize();
    const now = Number.isFinite(timeMs) ? timeMs : 0;
    const dt = this.lastTime == null ? 0 : Math.max(0, Math.min(80, now - this.lastTime));
    this.lastTime = now;
    if (!paused) this.clock += dt;
    this.state = state;
    this.reduceMotion = !!reduceMotion;
    if (this.reduceMotion) {
      this.shake = 0;
      this.particles.length = this.rings.length = 0;
    }
    const floorKey = `${state.floor}:${state.w}:${state.h}`;
    if (floorKey !== this.floorKey) {
      this.positions.clear();
      this.particles.length = this.labels.length = this.rings.length = this.flashes.length = 0;
      this.floorKey = floorKey;
      this.shake = 0;
    }
    if (!mapMode) {
      this.pushEvents(state.events);
      this._emitEvents();
    }
    const c = this.ctx;
    const w = this.width, h = this.height;
    c.globalAlpha = 1;
    c.globalCompositeOperation = 'source-over';
    c.fillStyle = '#070c0e';
    c.fillRect(0, 0, w, h);
    const tile = mapMode ? Math.max(1, Math.min((w - 10) / state.w, (h - 10) / state.h)) : w < 520 ? 38 : w > 1200 ? 44 : 42;
    const player = this._position('player', state.player, mapMode || this.reduceMotion);
    let ox = w / 2 - (player.x + 0.5) * tile;
    let oy = h / 2 - (player.y + 0.5) * tile;
    if (mapMode || state.w * tile <= w) ox = (w - state.w * tile) / 2;
    else ox = Math.max(w - state.w * tile, Math.min(0, ox));
    if (mapMode || state.h * tile <= h) oy = (h - state.h * tile) / 2;
    else oy = Math.max(h - state.h * tile, Math.min(0, oy));
    if (!mapMode && this.shake > 0.1) {
      ox += Math.sin(this.clock * 0.083) * this.shake;
      oy += Math.cos(this.clock * 0.067) * this.shake * 0.6;
      if (!paused) this.shake *= Math.exp(-dt / 90);
    }
    this.transform = { x: ox, y: oy, tile };
    this.tile = tile;
    const left = Math.max(0, Math.floor(-ox / tile) - 1);
    const top = Math.max(0, Math.floor(-oy / tile) - 1);
    const right = Math.min(state.w, Math.ceil((w - ox) / tile) + 1);
    const bottom = Math.min(state.h, Math.ceil((h - oy) / tile) + 1);
    c.save();
    c.translate(ox, oy);
    if (mapMode) {
      this._map(tile, left, top, right, bottom);
      c.restore();
      return;
    }
    for (let y = top; y < bottom; y++) {
      for (let x = left; x < right; x++) {
        if (this._seen(x, y)) this._tile(x, y, tile);
      }
    }
    // Light pools sit over the stone but underneath entities, silhouettes and fog.
    this._glow((player.x + 0.5) * tile, (player.y + 0.48) * tile, tile * 4.2, 'rgba(203,132,60,0.14)');
    for (let y = top; y < bottom; y++) {
      for (let x = left; x < right; x++) {
        if (!this._visible(x, y) || this._floor(x, y)) continue;
        if (this._floor(x, y + 1) && this._hash(x, y, 3) > 0.86) this._torch(x, y, tile);
      }
    }
    this._telegraphs(tile);
    const stairs = state.stairs;
    if (stairs && this._seen(stairs.x, stairs.y)) this._stairs(stairs.x, stairs.y, tile);
    else {
      for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
        if (state.tiles[y][x] === 2 && this._seen(x, y)) this._stairs(x, y, tile);
      }
    }
    if (state.entry && this._seen(state.entry.x, state.entry.y)) this._entry(state.entry.x, state.entry.y, tile);
    for (const f of state.features || []) if (this._seen(f.x, f.y)) this._feature(f, tile);
    for (const item of state.items || []) if (this._visible(item.x, item.y)) this._item(item, tile);
    const entities = [];
    for (const enemy of state.enemies || []) {
      if (enemy.hp <= 0 || !this._visible(enemy.x, enemy.y)) continue;
      const p = this._position('enemy:' + enemy.id, enemy, this.reduceMotion);
      entities.push({ e: enemy, p, hero: false });
    }
    entities.push({ e: state.player, p: player, hero: true });
    entities.sort((a, b) => a.p.y - b.p.y);
    for (const entity of entities) this._entity(entity.e, entity.p, tile, entity.hero);
    if (hover && this._seen(hover.x, hover.y) && this._floor(hover.x, hover.y)) {
      c.strokeStyle = 'rgba(234,199,133,0.65)';
      c.lineWidth = 1;
      const hx = hover.x * tile + 3, hy = hover.y * tile + 3, edge = tile - 6, len = 7;
      for (const [sx, sy, dx, dy] of [[hx,hy,1,1],[hx+edge,hy,-1,1],[hx,hy+edge,1,-1],[hx+edge,hy+edge,-1,-1]]) {
        c.beginPath(); c.moveTo(sx + dx * len, sy); c.lineTo(sx, sy); c.lineTo(sx, sy + dy * len); c.stroke();
      }
    }
    this._effects(tile, paused ? 0 : dt);
    // The final veil prevents every light/effect from revealing unexplored rooms.
    for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
      if (!this._seen(x, y)) { c.fillStyle = '#070c0e'; c.fillRect(x * tile, y * tile, tile + 0.5, tile + 0.5); }
      else if (!this._visible(x, y)) { c.fillStyle = 'rgba(5,10,13,0.76)'; c.fillRect(x * tile, y * tile, tile + 0.5, tile + 0.5); }
    }
    c.restore();
    const vignette = c.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.28, w / 2, h / 2, Math.max(w, h) * 0.66);
    vignette.addColorStop(0, 'rgba(1,5,7,0)');
    vignette.addColorStop(1, 'rgba(1,5,7,0.63)');
    c.fillStyle = vignette; c.fillRect(0, 0, w, h);
    if (state.player.hp > 0 && state.player.hp / state.player.maxHp < 0.28) {
      const danger = c.createRadialGradient(w / 2, h / 2, h * 0.32, w / 2, h / 2, Math.max(w, h) * 0.65);
      danger.addColorStop(0, 'rgba(110,18,12,0)'); danger.addColorStop(1, `rgba(110,18,12,${0.2 + (this.reduceMotion ? 0 : Math.sin(this.clock * 0.003) * 0.06)})`);
      c.fillStyle = danger; c.fillRect(0, 0, w, h);
    }
  }

  _map(t, left, top, right, bottom) {
    const c = this.ctx, s = this.state;
    for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
      if (!this._seen(x, y)) continue;
      const visible = this._visible(x, y);
      c.fillStyle = this._floor(x, y) ? visible ? '#827665' : '#3e403d' : visible ? '#303b3c' : '#1a2529';
      c.fillRect(x * t, y * t, Math.max(1, t - 0.6), Math.max(1, t - 0.6));
    }
    for (const f of s.features || []) {
      if (!this._seen(f.x, f.y) || f.used) continue;
      c.fillStyle = f.type === 'chest' ? '#b89459' : '#6fa89c';
      c.fillRect((f.x + 0.22) * t, (f.y + 0.22) * t, t * 0.56, t * 0.56);
    }
    if (s.stairs && this._seen(s.stairs.x, s.stairs.y)) {
      c.fillStyle = '#a6d6c6'; c.fillRect((s.stairs.x + 0.15) * t, (s.stairs.y + 0.15) * t, t * 0.7, t * 0.7);
    }
    if (s.entry && this._seen(s.entry.x, s.entry.y)) {
      this._poly([[(s.entry.x+.5)*t,(s.entry.y+.15)*t],[(s.entry.x+.85)*t,(s.entry.y+.8)*t],[(s.entry.x+.15)*t,(s.entry.y+.8)*t]], '#dec18a');
    }
    for (const e of s.enemies || []) if (e.hp > 0 && this._visible(e.x, e.y)) {
      c.fillStyle = e.type === 'boss' ? '#ffb07d' : '#d07765';
      c.fillRect((e.x + 0.24) * t, (e.y + 0.24) * t, t * 0.52, t * 0.52);
    }
    c.fillStyle = '#f4d8a1';
    c.beginPath(); c.arc((s.player.x + 0.5) * t, (s.player.y + 0.5) * t, Math.max(2, t * 0.4), 0, Math.PI * 2); c.fill();
  }

  _tile(x, y, t) {
    const c = this.ctx, px = x * t, py = y * t;
    const r = this._hash(x, y, this.state.floor || 0);
    if (this._floor(x, y)) {
      const shade = Math.floor(27 + r * 10);
      c.fillStyle = `rgb(${shade + 5},${shade + 8},${shade + 8})`; c.fillRect(px, py, t, t);
      c.fillStyle = 'rgba(0,0,0,0.23)'; c.fillRect(px, py, t, 1); c.fillRect(px, py, 1, t);
      c.fillStyle = 'rgba(196,183,143,0.035)'; c.fillRect(px + 2, py + 2, t - 4, 1); c.fillRect(px + 2, py + 2, 1, t - 4);
      if (r > 0.72) {
        c.strokeStyle = 'rgba(10,14,15,0.55)'; c.lineWidth = 1;
        c.beginPath(); c.moveTo(px + t * 0.65, py + 1); c.lineTo(px + t * 0.5, py + t * 0.27);
        c.lineTo(px + t * 0.58, py + t * 0.42); c.lineTo(px + t * 0.43, py + t * 0.61); c.stroke();
      }
      for (let i = 0; i < 3; i++) {
        const rx = this._hash(x + i * 7, y, 2), ry = this._hash(x, y + i * 9, 5);
        c.fillStyle = i === 0 ? 'rgba(179,165,117,0.09)' : 'rgba(5,10,12,0.22)';
        c.fillRect(px + 4 + rx * (t - 9), py + 4 + ry * (t - 9), 1 + r * 2, 1);
      }
      if (!this._floor(x, y - 1)) { c.fillStyle = 'rgba(0,0,0,0.25)'; c.fillRect(px, py, t, t * 0.22); }
      if (!this._floor(x - 1, y)) { c.fillStyle = 'rgba(0,0,0,0.16)'; c.fillRect(px, py, t * 0.12, t); }
    } else {
      const edge = this._floor(x, y + 1), k = Math.floor(r * 7);
      c.fillStyle = `rgb(${22 + k},${31 + k},${33 + k})`; c.fillRect(px, py, t, t);
      c.fillStyle = `rgb(${34 + k},${43 + k},${44 + k})`; c.fillRect(px + 1, py + 2, t - 2, t * 0.58);
      c.fillStyle = 'rgba(159,166,151,0.10)'; c.fillRect(px + 2, py + 2, t - 4, 2);
      c.fillStyle = 'rgba(4,10,12,0.47)'; c.fillRect(px, py + t * 0.59, t, 2);
      c.fillRect(px + (y % 2 ? t * 0.28 : t * 0.7), py + 2, 2, t * 0.56);
      if (edge) {
        c.fillStyle = '#151e20'; c.fillRect(px + 1, py + t * 0.66, t - 2, t * 0.34);
        c.fillStyle = '#51514a'; c.fillRect(px, py + t * 0.61, t, 2);
        c.fillStyle = 'rgba(173,144,94,0.17)'; c.fillRect(px + 2, py + t * 0.66, 2, t * 0.25);
        c.fillStyle = 'rgba(1,5,6,0.48)'; c.fillRect(px, py + t - 3, t, 3);
      }
      if (r > 0.87) {
        c.strokeStyle = 'rgba(111,133,114,0.18)'; c.lineWidth = 1;
        c.beginPath(); c.moveTo(px + t * 0.2, py + 5); c.lineTo(px + t * 0.27, py + 14); c.lineTo(px + t * 0.2, py + 22); c.stroke();
      }
    }
  }

  _glow(x, y, radius, color) {
    const c = this.ctx;
    const gradient = c.createRadialGradient(x, y, 0, x, y, Math.max(1, radius));
    gradient.addColorStop(0, color); gradient.addColorStop(1, 'rgba(0,0,0,0)');
    c.fillStyle = gradient; c.fillRect(x - radius, y - radius, radius * 2, radius * 2);
  }

  _poly(points, color, stroke = null, line = 1) {
    const c = this.ctx; c.beginPath();
    c.moveTo(points[0][0], points[0][1]);
    for (let i = 1; i < points.length; i++) c.lineTo(points[i][0], points[i][1]);
    c.closePath(); c.fillStyle = color; c.fill();
    if (stroke) { c.strokeStyle = stroke; c.lineWidth = line; c.stroke(); }
  }

  _ellipse(x, y, rx, ry, color) {
    const c = this.ctx; c.fillStyle = color; c.beginPath(); c.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); c.fill();
  }

  _torch(x, y, t) {
    const c = this.ctx, px = (x + 0.5) * t, py = (y + 0.66) * t;
    const flicker = this.reduceMotion ? 0 : Math.sin(this.clock * 0.012 + x * 4 + y) * 0.12 + Math.sin(this.clock * 0.021 + x) * 0.04;
    this._glow(px, py, t * (2.5 + flicker), 'rgba(243,151,53,0.16)');
    c.save(); c.translate(px, py); c.scale(t / 40, t / 40);
    c.fillStyle = '#0c1011'; c.fillRect(-5, -4, 10, 11);
    c.fillStyle = '#765c38'; c.fillRect(-2, -3, 4, 12);
    this._poly([[-5,-3],[-4,-10],[0,-18-flicker*10],[2,-12],[5,-7],[4,-2]], '#d28536');
    this._poly([[-2,-3],[-2,-8],[1,-13-flicker*8],[3,-6],[2,-2]], '#ffdc8b');
    c.fillStyle = '#b49455'; c.fillRect(-5, -1, 10, 2);
    if (!this.reduceMotion && Math.sin(this.clock * 0.004 + x) > 0) {
      c.globalAlpha = 0.7; c.fillStyle = '#f5bb65'; c.fillRect(Math.sin(this.clock * 0.004 + y) * 4, -18 - (this.clock * 0.012 + x * 8) % 14, 1, 2);
    }
    c.restore();
  }

  _stairs(x, y, t) {
    const c = this.ctx, px = x * t, py = y * t;
    this._glow(px + t * 0.5, py + t * 0.5, t * 1.5, 'rgba(74,165,152,0.13)');
    c.fillStyle = '#10191c'; c.fillRect(px + t * 0.12, py + t * 0.15, t * 0.76, t * 0.73);
    for (let i = 0; i < 5; i++) {
      c.fillStyle = ['#59625a','#47534d','#38453f','#283730','#192925'][i];
      c.fillRect(px + t * (0.16 + i * 0.04), py + t * (0.2 + i * 0.13), t * (0.68 - i * 0.08), t * 0.09);
      c.fillStyle = 'rgba(190,195,155,0.2)'; c.fillRect(px + t * (0.16 + i * 0.04), py + t * (0.2 + i * 0.13), t * (0.68 - i * 0.08), 1);
    }
    c.strokeStyle = '#7d9e87'; c.lineWidth = 1;
    c.strokeRect(px + t * 0.1, py + t * 0.12, t * 0.8, t * 0.78);
    this._poly([[px+t*.4,py+t*.32],[px+t*.6,py+t*.32],[px+t*.5,py+t*.46]], '#bdd3a7');
  }

  _entry(x, y, t) {
    // Safe-return marker is only a visual landmark; campaign.canReturn owns eligibility.
    const c = this.ctx, px = x * t, py = y * t;
    this._glow(px+t*.5, py+t*.5, t*1.1, 'rgba(208,166,88,.1)');
    c.strokeStyle = '#b5a074'; c.lineWidth = 1;
    c.setLineDash([3, 3]); c.strokeRect(px+t*.12, py+t*.12, t*.76, t*.76); c.setLineDash([]);
    this._poly([[px+t*.3,py+t*.45],[px+t*.5,py+t*.26],[px+t*.7,py+t*.45]], '#c2ab76', '#e4d1a1', .8);
    c.fillStyle = '#74684d'; c.fillRect(px+t*.36,py+t*.45,t*.28,t*.22);
    c.fillStyle = '#28342d'; c.fillRect(px+t*.46,py+t*.53,t*.08,t*.14);
  }

  _feature(f, t) {
    const c = this.ctx, x = (f.x + 0.5) * t, y = (f.y + 0.55) * t;
    if (!f.used && f.type !== 'chest') this._glow(x, y - t * 0.1, t * 1.6, 'rgba(56,183,170,0.12)');
    c.save(); c.translate(x, y); c.scale(t / 40, t / 40);
    this._ellipse(0, 11, 15, 5, 'rgba(0,0,0,0.38)');
    if (f.type === 'chest') {
      c.fillStyle = '#392920'; c.fillRect(-13, -3, 26, 15);
      c.fillStyle = '#75532b'; c.fillRect(-11, -2, 22, 12);
      c.fillStyle = '#a58246'; c.fillRect(-14, -6, 28, 7);
      if (f.used) {
        this._poly([[-14,-7],[-12,-16],[12,-16],[14,-7]], '#685337', '#a98c54');
        c.fillStyle = '#151a18'; c.fillRect(-10,-7,20,6);
      } else {
        this._poly([[-14,-6],[-10,-12],[10,-12],[14,-6]], '#9d763c', '#c19b54');
        c.fillStyle = '#c4a364'; c.fillRect(-10,-8,3,19); c.fillRect(7,-8,3,19);
        c.fillStyle = '#252722'; c.fillRect(-3,-2,6,7); c.fillStyle = '#e5c777'; c.fillRect(-1,-1,2,3);
        if (this._visible(f.x,f.y)) {
          c.globalAlpha = this.reduceMotion ? 0.5 : 0.5 + Math.sin(this.clock * 0.003 + f.x) * 0.25;
          c.fillStyle = '#ffdc91'; c.fillRect(-10,-12,20,1); c.globalAlpha = 1;
        }
      }
      c.fillStyle = '#342820'; c.fillRect(-10,11,5,3); c.fillRect(5,11,5,3);
    } else if (f.type === 'fountain') {
      this._ellipse(0, 6, 16, 9, '#374c48'); this._ellipse(0, 3, 16, 8, '#859b86');
      this._ellipse(0, 2, 12, 5, f.used ? '#253d39' : '#377d76');
      c.fillStyle = '#738779'; c.fillRect(-4,-8,8,9); this._ellipse(0,-8,7,3,'#97a792');
      if (!f.used) {
        c.strokeStyle = '#85d7c1'; c.lineWidth = 1;
        c.beginPath(); c.moveTo(-1,-9); c.quadraticCurveTo(-9,-19,-10,0); c.moveTo(1,-9); c.quadraticCurveTo(9,-19,10,0); c.stroke();
        this._ellipse(0,-9,3,2,'#b8e6cb');
        c.strokeStyle = 'rgba(177,225,204,0.5)'; c.beginPath(); c.ellipse(0,3,7+(this.reduceMotion?0:Math.sin(this.clock*.004)*2),2,0,0,Math.PI*2); c.stroke();
      }
    } else {
      this._poly([[-14,12],[-10,6],[10,6],[14,12]], '#57615b', '#899080');
      this._poly([[-8,6],[-6,-5],[6,-5],[8,6]], '#58695c');
      this._poly([[-9,-4],[-10,-8],[10,-8],[9,-4]], '#9a9d79');
      c.fillStyle = '#333f37'; c.fillRect(-2,-3,4,7);
      if (!f.used) {
        const bob = this.reduceMotion ? 0 : Math.sin(this.clock * 0.003 + f.x) * 1.8;
        this._poly([[0,-23+bob],[6,-16+bob],[0,-9+bob],[-6,-16+bob]], '#77d6c2', '#c1f0cf');
        this._poly([[0,-23+bob],[0,-9+bob],[-6,-16+bob]], '#419c91');
        c.strokeStyle = 'rgba(95,188,164,0.4)'; c.lineWidth = 1; c.beginPath(); c.ellipse(0,-15,13,5,-0.2,0,Math.PI*2); c.stroke();
      } else this._poly([[0,-17],[5,-12],[0,-8],[-5,-12]], '#485c51');
    }
    c.restore();
  }

  _item(item, t) {
    const c = this.ctx, x = (item.x + 0.5) * t, y = (item.y + 0.52) * t;
    const type = String(item.type || 'gold');
    c.save(); c.translate(x,y); c.scale(t/40,t/40);
    this._ellipse(0,7,7,3,'rgba(0,0,0,0.35)');
    c.translate(0,this.reduceMotion ? 0 : Math.sin(this.clock*.003 + item.x)*1.4);
    if (type === 'wood') {
      for (let i = 0; i < 3; i++) {
        const xx = i * 4 - 5, yy = i % 2 * -4;
        this._poly([[xx-5,yy+3],[xx-3,yy-9],[xx+2,yy-8],[xx+1,yy+5]], '#7b6240', '#a99564', .7);
        this._ellipse(xx-2,yy+4,3,2,'#c0a570');
      }
      c.strokeStyle='#c6b184';c.lineWidth=1;c.beginPath();c.moveTo(-7,-1);c.lineTo(7,1);c.moveTo(-6,2);c.lineTo(6,4);c.stroke();
    } else if (type === 'ore') {
      this._poly([[-9,3],[-6,-5],[0,-8],[8,-3],[9,4],[2,8],[-6,7]], '#647b81', '#a1b7b4', .8);
      this._poly([[-6,-5],[0,-8],[3,-1],[-2,3],[-9,3]], '#8aa2a3');
      this._poly([[3,-1],[8,-3],[9,4],[2,8]], '#3d555e');
      c.strokeStyle='#c5d4bc';c.lineWidth=1;c.beginPath();c.moveTo(-4,-2);c.lineTo(-1,0);c.lineTo(1,-3);c.stroke();
    } else if (type === 'herb') {
      c.strokeStyle='#9aaa68';c.lineWidth=1.1;c.beginPath();c.moveTo(-2,8);c.lineTo(1,-10);c.moveTo(-1,5);c.lineTo(-7,-6);c.moveTo(0,3);c.lineTo(7,-5);c.stroke();
      this._poly([[0,-4],[-2,-11],[2,-12],[3,-6]], '#abc081');
      this._poly([[-3,1],[-10,-5],[-9,-9],[-4,-5]], '#779c65');
      this._poly([[1,0],[5,-7],[9,-7],[7,-2]], '#91b37b');
      this._ellipse(1,-11,2,2,'#c9b6ca');
      c.strokeStyle='#cfbb87';c.beginPath();c.moveTo(-4,4);c.lineTo(3,5);c.stroke();
    } else if (/potion|heal|flask/.test(type)) {
      c.fillStyle='#b69d76'; c.fillRect(-2,-8,4,3);
      this._poly([[-3,-5],[3,-5],[3,-1],[6,3],[4,7],[-4,7],[-6,3],[-3,-1]], '#9b514b', '#d7a283');
      c.fillStyle='#efbe98'; c.fillRect(-3,0,1,4);
    } else if (/scroll|book/.test(type)) {
      this._poly([[-5,-7],[5,-6],[4,7],[-5,6]], '#b7a880','#e0c99d');
      c.fillStyle='#615c46'; c.fillRect(-2,-3,5,1); c.fillRect(-2,0,4,1); c.fillRect(-2,3,3,1);
    } else if (/weapon|sword/.test(type)) {
      c.rotate(.45);
      this._poly([[-2,-10],[1,-13],[3,-10],[2,4],[-2,4]], '#9cae9e','#d5d5ad');
      c.fillStyle='#c19e5d'; c.fillRect(-6,3,12,2); c.fillStyle='#755338'; c.fillRect(-1,5,3,6);
    } else if (/armor|shield/.test(type)) {
      this._poly([[-8,-7],[0,-10],[8,-7],[7,4],[0,10],[-7,4]], '#667668','#c0ae76');
      c.strokeStyle='#c5b17a'; c.lineWidth=1; c.beginPath(); c.moveTo(0,-7); c.lineTo(0,7); c.moveTo(-5,-2); c.lineTo(5,-2); c.stroke();
    } else if (/gem|mana|crystal|shard/.test(type)) {
      this._poly([[0,-8],[5,-2],[3,6],[-3,6],[-5,-2]], '#66b7ad','#a2e0cb');
      this._poly([[0,-8],[0,6],[-5,-2]], '#337f7c');
    } else {
      this._ellipse(-3,3,5,3,'#82613b'); this._ellipse(-3,1,5,3,'#d2ad62');
      this._ellipse(3,0,5,3,'#a78040'); this._ellipse(3,-2,5,3,'#e3bd6a');
      c.fillStyle='#fbe1a0'; c.fillRect(2,-3,2,1);
    }
    c.restore();
  }

  _telegraphs(t) {
    const c = this.ctx;
    for (const e of this.state.enemies || []) {
      if (e.hp <= 0 || !this._visible(e.x,e.y)) continue;
      const nova = e.intent === 'nova';
      const blast = e.intent === 'blast' || e.armed;
      if (nova || blast) {
        const radius = nova ? 2 : 1;
        const pulse = this.reduceMotion ? 0.18 : 0.11 + (Math.sin(this.clock * .007) + 1) * .055;
        for (let y = e.y - radius; y <= e.y + radius; y++) for (let x = e.x - radius; x <= e.x + radius; x++) {
          if (!this._floor(x,y) || !this._visible(x,y)) continue;
          if (nova && (x-e.x)*(x-e.x)+(y-e.y)*(y-e.y)>6.25) continue;
          c.fillStyle = `rgba(203,73,43,${pulse})`; c.fillRect(x*t+2,y*t+2,t-4,t-4);
          c.strokeStyle = 'rgba(241,124,79,0.42)'; c.lineWidth = 1; c.strokeRect(x*t+3,y*t+3,t-6,t-6);
          c.fillStyle = 'rgba(235,132,84,0.58)';
          c.fillRect(x*t+t*.48,y*t+t*.37,t*.04,t*.16); c.fillRect(x*t+t*.48,y*t+t*.59,t*.04,t*.04);
        }
      } else if (e.intent === 'aim' || (e.charge && e.tx != null && e.ty != null)) {
        const tx = e.tx == null ? this.state.player.x : e.tx;
        const ty = e.ty == null ? this.state.player.y : e.ty;
        c.save(); c.strokeStyle = 'rgba(222,107,78,0.65)'; c.lineWidth = 1; c.setLineDash([4,5]);
        c.beginPath(); c.moveTo((e.x+.5)*t,(e.y+.5)*t); c.lineTo((tx+.5)*t,(ty+.5)*t); c.stroke(); c.restore();
      }
    }
  }

  _entity(e, p, t, hero) {
    const c = this.ctx, x = (p.x + 0.5) * t, y = (p.y + 0.61) * t;
    const boss = e.type === 'boss';
    const phase = this._hash(e.x, e.y, String(e.id || '').length) * Math.PI * 2;
    const bob = this.reduceMotion || hero ? 0 : Math.sin(this.clock * .004 + phase) * (e.type === 'wisp' ? 3 : .7);
    if (hero) this._glow(x - t*.18,y-t*.04,t*.82,'rgba(222,166,73,0.18)');
    if (e.type === 'wisp') this._glow(x,y-t*.1,t,'rgba(45,190,169,0.21)');
    c.save(); c.translate(x,y); c.scale(t/40,t/40);
    this._ellipse(0,11,boss?18:11,boss?6:4,'rgba(0,0,0,0.48)');
    c.translate(0,bob);
    if (hero) this._hero(e, this._heroPose(p));
    else if (e.type === 'rat') this._rat();
    else if (e.type === 'skeleton' || e.type === 'archer') this._skeleton(e.type === 'archer');
    else if (e.type === 'sentinel' || e.type === 'brute') this._sentinel();
    else if (e.type === 'bomber') this._bomber(e.armed || e.intent === 'blast');
    else if (e.type === 'boss') this._boss(e.intent === 'nova');
    else this._wisp();
    if (this.flashes.some(f => f.x === e.x && f.y === e.y && f.until > this.clock)) {
      c.globalCompositeOperation='screen';
      this._ellipse(0,-4,boss?15:10,boss?23:16,'rgba(255,204,157,0.43)');
      c.globalCompositeOperation='source-over';
    }
    c.restore();
    if (!hero && (e.hp < e.maxHp || e.alert || boss)) {
      const bw = t * (boss ? .85 : .62), by = y - t * (boss ? .94 : .72);
      c.fillStyle = '#0b1011'; c.fillRect(x-bw/2-1,by-1,bw+2,5);
      c.fillStyle = '#503330'; c.fillRect(x-bw/2,by,bw,3);
      c.fillStyle = boss ? '#d39560' : '#bf7561'; c.fillRect(x-bw/2,by,bw*Math.max(0,Math.min(1,e.hp/(e.maxHp||e.hp||1))),3);
    }
    if (boss && e.intent === 'nova') {
      const turns = Math.max(1, Math.round(Number(e.charge) || 1));
      const by = y - t * 1.6, bw = 62;
      c.fillStyle = 'rgba(30,15,14,0.94)'; c.fillRect(x-bw/2,by,bw,16);
      c.strokeStyle = '#bd7951'; c.lineWidth = 1; c.strokeRect(x-bw/2+.5,by+.5,bw-1,15);
      c.font = '700 10px ui-monospace, monospace'; c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillStyle = '#ffd4a0'; c.fillText(turns + (turns === 1 ? ' ХОД' : ' ХОДА'),x,by+8);
    }
  }

  _hero(e, pose = { amount: 0, phase: 0, stride: 0, leftLift: 0, rightLift: 0, bounce: 0, facing: 'down' }) {
    const c = this.ctx;
    const mage = /mage|mystic|wizard|arcan|witch/.test(String(e.classId || ''));
    const rogue = /rogue|ranger|scout/.test(String(e.classId || ''));
    const cloak = mage ? '#365b57' : rogue ? '#4b5551' : '#855137';
    const trim = mage ? '#689789' : rogue ? '#8b9a86' : '#b58650';
    const side = pose.facing === 'left' || pose.facing === 'right';
    const back = pose.facing === 'up';
    const sway = Math.sin(pose.phase - .65) * pose.amount * 2.8;
    const trail = sway - (side ? pose.amount * 2.4 : 0);
    c.save();
    if (pose.facing === 'left') c.scale(-1,1);

    // Two articulated legs: hips, bent knees, lifted heels and individual boots.
    // Sorting the feet gives a readable passing pose when one leg overtakes the other.
    const legs = [
      { hip: -3.5, stride: pose.stride, lift: pose.leftLift, near: false },
      { hip: 3.5, stride: -pose.stride, lift: pose.rightLift, near: true }
    ];
    legs.sort((a,b) => (a.stride-b.stride) * (side ? 0 : back ? -1 : 1));
    for (const leg of legs) this._heroLeg(leg, side, back);

    c.save();
    c.translate(side ? pose.amount * .9 : pose.stride * .3,pose.bounce);
    c.rotate(side ? pose.amount * .065 : pose.stride * .025);
    if (back) {
      this._heroArm(-1,pose,mage,side,back);
      this._heroArm(1,pose,mage,side,back);
    }

    // The cape trails the torso; its split hem moves independently of the legs.
    const hemLeft = 7 + Math.max(0,-pose.stride) * 2;
    const hemRight = 7 + Math.max(0,pose.stride) * 2;
    this._poly([[-7,-16],[7,-16],[12+trail,hemRight],[7+trail,11],
      [1+trail*.65,7],[-3+trail*.7,11],[-12+trail,hemLeft]], '#242e2c', '#111a1a');
    this._poly([[-7,-15],[3,-16],[6+trail,7],[-3+trail,9],[-10+trail,hemLeft]], cloak);
    this._poly([[-6,-9],[-2,-12],[-3+trail*.7,6],[-7+trail,8]], mage?'#4c7d70':rogue?'#66776a':'#a36b40');
    c.strokeStyle=trim; c.lineWidth=.8;
    c.beginPath(); c.moveTo(-9+trail,hemLeft); c.lineTo(-3+trail,9); c.lineTo(1+trail*.65,7); c.stroke();

    if (back) {
      this._poly([[-7,-14],[7,-14],[10+trail,7],[3+trail,10],[-4+trail,8],[-10+trail,8]],cloak);
      this._poly([[-2,-14],[3,-13],[5+trail,7],[1+trail,9],[-1+trail,1]],mage?'#447c70':rogue?'#697c70':'#a16a44');
      c.strokeStyle=trim; c.lineWidth=1;
      c.beginPath(); c.moveTo(-6,-12); c.quadraticCurveTo(-2,0,-5+trail,7); c.moveTo(5,-11); c.lineTo(7+trail,6); c.stroke();
      // A clasp, shoulder seam and hood centre seam make the back view intentional.
      c.fillStyle='#584b35'; c.fillRect(-7,-11,14,2);
      this._poly([[-8,-17],[-6,-24],[0,-27],[7,-23],[8,-17],[4,-11],[-5,-12]],cloak,'#a48b5b');
      this._poly([[-2,-25],[3,-23],[5,-16],[1,-12],[-1,-17]],mage?'#477b70':rogue?'#66786c':'#a06844');
      c.strokeStyle=trim; c.lineWidth=.8; c.beginPath(); c.moveTo(0,-25); c.quadraticCurveTo(-2,-18,0,-13); c.stroke();
    } else {
      this._poly([[-6,-12],[5,-12],[7,2],[-5,3]], '#887555', '#342f29');
      this._poly([[-5,-11],[-1,-10],[-1,-1],[-5,-2]], '#aa956c');
      c.fillStyle='#b8a47a'; c.fillRect(-4,-11,8,2);
      c.fillStyle='#4a382c'; c.fillRect(-6,0,13,3); c.fillStyle='#e0bd70'; c.fillRect(-1,0,3,3);
      this._heroArm(-1,pose,mage,side,back);
      this._heroArm(1,pose,mage,side,back);
      c.save(); c.translate(side ? .7 : -pose.stride*.18, -pose.bounce*.2);
      this._ellipse(0,-18,8,9,'#151e1e');
      this._poly([[-8,-17],[-6,-24],[1,-27],[7,-22],[8,-15],[3,-11],[-4,-12]], cloak, '#ae8651');
      if (side) {
        this._poly([[0,-21],[6,-21],[8,-17],[6,-13],[1,-11],[-1,-16]], '#192427');
        c.fillStyle='#e1c792'; c.fillRect(4,-19,3,2);
        this._poly([[6,-17],[9,-16],[6,-15]],'#b79b6f');
      } else {
        this._poly([[-4,-20],[4,-20],[5,-13],[0,-10],[-4,-13]], '#192427');
        c.fillStyle='#d9ba82'; c.fillRect(-4,-19,2,2); c.fillRect(2,-19,2,2);
      }
      c.restore();
    }
    c.restore();
    c.restore();
  }

  _heroLeg(leg, side, back) {
    const c = this.ctx;
    const forward = back ? -leg.stride : leg.stride;
    const footX = leg.hip + (side ? leg.stride * 6.2 : leg.stride * .8);
    const footY = 13 + (side ? 0 : forward * 3.6) - leg.lift * 4.1;
    const kneeX = leg.hip + (footX-leg.hip)*.48 + (side ? leg.lift*1.6 : 0);
    const kneeY = 7 + (footY-13)*.42;
    this._poly([[leg.hip-2.2,1],[leg.hip+2.2,1],[kneeX+2.1,kneeY],
      [footX+2,footY],[footX-2,footY],[kneeX-2.1,kneeY]],
      leg.near?'#303b36':'#222c29','#151e1b',.7);
    this._poly([[kneeX-1.9,kneeY-1.4],[kneeX+1.9,kneeY-1.4],
      [kneeX+1.5,kneeY+1.6],[kneeX-1.5,kneeY+1.6]],leg.near?'#8f7750':'#665d43');
    const toe = side ? 3.8 : .8;
    this._poly([[footX-2.4,footY-2],[footX+2.3,footY-2],
      [footX+2.4+toe,footY+1],[footX+2.4+toe,footY+3.3],[footX-2.5,footY+3.3]],
      leg.near?'#8b6643':'#624f38','#252a23',.8);
    c.strokeStyle=leg.near?'#c49c60':'#9b8052'; c.lineWidth=1;
    c.beginPath(); c.moveTo(footX-1.7,footY); c.lineTo(footX+1.7,footY); c.stroke();
    c.strokeStyle='#171f1a'; c.beginPath(); c.moveTo(footX-2.3,footY+3.3); c.lineTo(footX+2.4+toe,footY+3.3); c.stroke();
  }

  _heroArm(sideSign, pose, mage, sideView, back) {
    const c = this.ctx;
    const shoulderX = sideSign < 0 ? -8 : 7;
    // Arm rotation opposes the same-side foot. The carried object has another
    // pivot, so the lantern trails the wrist instead of being glued to the body.
    const swing = pose.stride * -sideSign;
    const angle = swing * (sideView ? .38 : .28);
    c.save(); c.translate(shoulderX,-10); c.rotate(angle);
    const handX = sideSign * 3.5;
    this._poly([[sideSign < 0 ? 1 : -1,-1],[sideSign*4,0],
      [handX+2,7],[handX+2,10],[handX-2,10],[handX-2,5]],back?'#8e7653':'#b78e59','#574830',.7);
    c.fillStyle='#d0af78'; c.fillRect(handX-1.6,7,3.2,3);
    c.translate(handX,9);
    if(sideSign < 0) {
      const lag = Math.sin(pose.phase-.55)*pose.amount*.19;
      c.rotate(-angle*.62 + lag);
      c.strokeStyle='#d0aa62'; c.lineWidth=1; c.beginPath(); c.arc(0,2,3,Math.PI,0); c.stroke();
      c.fillStyle='#725b36'; c.fillRect(-4,3,8,10); c.fillStyle='#efbd63'; c.fillRect(-2,5,4,6);
      c.fillStyle='#ffe5a3'; c.fillRect(-1,6,2,3); c.fillStyle='#3e3323'; c.fillRect(-5,3,10,2); c.fillRect(-5,12,10,2);
      c.fillStyle='#bd9552'; c.fillRect(-4,4,1,8); c.fillRect(3,4,1,8);
    } else {
      c.rotate(-angle*.2);
      if(mage) {
        c.strokeStyle='#a7804f'; c.lineWidth=3; c.beginPath(); c.moveTo(0,15); c.lineTo(2,-22); c.stroke();
        c.strokeStyle='#c5a672'; c.lineWidth=.8; c.beginPath(); c.moveTo(1,12); c.lineTo(3,-21); c.stroke();
        this._poly([[2,-29],[6,-23],[2,-17],[-2,-23]], '#8ed4ba','#d3eac3');
      } else {
        this._poly([[-1,-19],[2,-23],[3,-6],[1,-2],[-1,-6]], '#91a4a0','#d1d7bc');
        c.fillStyle='#d6b273'; c.fillRect(-4,-4,10,2); c.fillStyle='#775435'; c.fillRect(0,-2,3,7); c.fillStyle='#c7a366'; c.fillRect(-1,4,5,2);
      }
    }
    c.restore();
  }

  _rat() {
    const c=this.ctx;
    c.strokeStyle='#936354'; c.lineWidth=2; c.beginPath(); c.moveTo(-10,5); c.bezierCurveTo(-22,8,-19,-6,-13,-5); c.stroke();
    this._ellipse(-1,2,12,8,'#594841'); this._ellipse(-3,0,9,6,'#776155');
    this._poly([[6,-4],[15,0],[12,6],[4,7]],'#8b7260');
    this._ellipse(5,-5,4,5,'#493c36'); this._ellipse(5,-5,2,3,'#9a6b64');
    c.fillStyle='#392c29'; c.fillRect(-9,7,5,3); c.fillRect(4,7,5,3);
    c.fillStyle='#f2a185'; c.fillRect(9,-1,2,2); c.fillStyle='#19191a'; c.fillRect(14,2,3,2);
    c.strokeStyle='#b5a18b'; c.lineWidth=.7; c.beginPath(); c.moveTo(12,4); c.lineTo(18,3); c.moveTo(12,5); c.lineTo(17,7); c.stroke();
  }

  _skeleton(archer) {
    const c=this.ctx;
    if (archer) this._poly([[-7,-18],[6,-18],[10,10],[-8,10]],'#534237');
    c.strokeStyle='#a99e80'; c.lineWidth=3;
    c.beginPath(); c.moveTo(-4,0); c.lineTo(-6,7); c.lineTo(-5,13); c.moveTo(4,0); c.lineTo(7,7); c.lineTo(6,13); c.stroke();
    c.strokeStyle='#d0c5a1'; c.lineWidth=2; c.beginPath(); c.moveTo(0,-13); c.lineTo(0,1); c.moveTo(-7,-10); c.lineTo(-10,-3); c.lineTo(-8,2); c.moveTo(7,-10); c.lineTo(10,-3); c.lineTo(12,-3); c.stroke();
    for(let i=0;i<3;i++) { c.strokeStyle=i===0?'#d9cba4':'#a99c7f'; c.beginPath(); c.moveTo(-5,-11+i*4); c.lineTo(0,-9+i*4); c.lineTo(5,-11+i*4); c.stroke(); }
    this._poly([[-5,-1],[5,-1],[6,3],[1,4],[-5,3]],'#887b64');
    this._poly([[-6,-24],[5,-24],[7,-18],[4,-12],[-4,-12],[-7,-18]],'#c5b693','#796d58');
    c.fillStyle='#202422'; c.fillRect(-5,-20,4,4); c.fillRect(2,-20,3,4); c.fillRect(-1,-16,2,2);
    c.fillStyle='#d98463'; c.fillRect(-3,-19,1,1); c.fillRect(3,-19,1,1);
    c.fillStyle='#e0d1a6'; c.fillRect(-3,-13,6,2); c.fillStyle='#615443'; c.fillRect(-1,-13,1,2); c.fillRect(2,-13,1,2);
    if(archer) {
      this._poly([[-7,-23],[0,-28],[7,-23]],'#66523b');
      c.strokeStyle='#ad8956'; c.lineWidth=2; c.beginPath(); c.moveTo(11,-19); c.quadraticCurveTo(23,-3,12,11); c.stroke();
      c.strokeStyle='#b7b19a'; c.lineWidth=.8; c.beginPath(); c.moveTo(11,-19); c.lineTo(12,11); c.stroke();
      c.strokeStyle='#c2b98e'; c.beginPath(); c.moveTo(3,-3); c.lineTo(21,-3); c.stroke();
      this._poly([[22,-3],[18,-6],[18,0]],'#b8beb1');
    } else {
      this._poly([[12,-18],[15,-21],[16,-3],[13,-1]],'#788b85','#b9bba1');
      c.fillStyle='#b7945b'; c.fillRect(10,-1,9,2); c.fillStyle='#624b35'; c.fillRect(13,1,3,5);
    }
  }

  _sentinel() {
    const c=this.ctx;
    this._poly([[-11,-16],[11,-16],[15,9],[-14,9]],'#493a32');
    c.fillStyle='#282c29'; c.fillRect(-10,5,8,10); c.fillRect(3,5,8,10);
    c.fillStyle='#977b4d'; c.fillRect(-11,11,9,4); c.fillRect(3,11,9,4);
    this._poly([[-11,-15],[11,-15],[13,0],[7,6],[-7,6],[-13,0]],'#77745b','#b09a65');
    this._poly([[-9,-13],[-1,-10],[-1,1],[-9,-2]],'#a18b5c');
    this._poly([[1,-10],[9,-13],[9,-2],[1,1]],'#53605a');
    this._poly([[-15,-16],[-8,-19],[-5,-12],[-14,-8],[-18,-10]],'#b19c69','#41433b');
    this._poly([[7,-18],[14,-17],[18,-9],[10,-9]],'#9e8b60','#41433b');
    this._poly([[-8,-26],[0,-30],[8,-26],[8,-17],[0,-12],[-8,-17]],'#8a8667','#bbb084');
    c.fillStyle='#242e2b'; c.fillRect(-6,-23,12,4); c.fillStyle='#e6a073'; c.fillRect(-5,-22,4,1); c.fillRect(2,-22,3,1);
    c.fillStyle='#b29b6d'; c.fillRect(-1,-26,2,11);
    this._poly([[-19,-8],[-11,-11],[-5,-7],[-7,8],[-13,13],[-19,7]],'#585f51','#bea273');
    c.strokeStyle='#9a8c5e'; c.lineWidth=2; c.beginPath(); c.moveTo(-13,-7); c.lineTo(-13,9); c.moveTo(-17,-1); c.lineTo(-9,-1); c.stroke();
    c.strokeStyle='#816743'; c.lineWidth=3; c.beginPath(); c.moveTo(15,12); c.lineTo(17,-21); c.stroke();
    this._poly([[12,-25],[21,-24],[24,-16],[11,-17]],'#7b8d83','#b5bd9c');
  }

  _bomber(armed) {
    const c=this.ctx;
    this._poly([[-7,-16],[7,-16],[11,11],[3,13],[0,10],[-7,13],[-12,9]],'#703f37','#302928');
    this._poly([[-7,-13],[-1,-15],[-3,9],[-9,10]],'#995843');
    this._ellipse(0,-18,8,9,'#8a5340');
    this._poly([[-5,-21],[5,-21],[4,-13],[-4,-13]],'#252923');
    c.fillStyle='#e9a26b'; c.fillRect(-4,-18,2,2); c.fillRect(2,-18,2,2);
    c.fillStyle='#b59366'; c.fillRect(-8,-6,5,5); c.fillRect(6,-5,5,5);
    this._ellipse(4,1,9,9,'#222c2b'); this._ellipse(2,-1,6,6,'#485047');
    c.strokeStyle='#bd9960'; c.lineWidth=2; c.beginPath(); c.moveTo(5,-7); c.quadraticCurveTo(3,-13,9,-12); c.stroke();
    c.fillStyle=armed?'#ffbd79':'#d19b61'; c.fillRect(8,-14,3,3);
    if(armed) {
      this._poly([[10,-17],[12,-13],[16,-14],[13,-11],[15,-8],[11,-10],[8,-7],[9,-11],[6,-13],[10,-13]],'#ffda91');
      c.strokeStyle='#df7752'; c.lineWidth=1; c.beginPath(); c.arc(4,1,11+(this.reduceMotion?0:Math.sin(this.clock*.01)),0,Math.PI*2); c.stroke();
    }
    c.fillStyle='#806041'; c.fillRect(-8,11,5,3); c.fillRect(4,11,5,3);
  }

  _boss(charging) {
    const c=this.ctx;
    this._poly([[-15,-24],[15,-24],[22,14],[11,17],[4,12],[0,16],[-8,13],[-19,16]],'#482f33','#a17254');
    this._poly([[-14,-23],[-5,-25],[-7,12],[-16,14]],'#805047');
    this._poly([[8,-24],[14,-22],[18,12],[11,14]],'#643d3b');
    c.fillStyle='#28332e'; c.fillRect(-10,7,7,10); c.fillRect(4,7,7,10);
    c.fillStyle='#b19a68'; c.fillRect(-12,13,9,4); c.fillRect(4,13,9,4);
    this._poly([[-11,-21],[11,-21],[13,-6],[8,7],[-8,7],[-13,-6]],'#53645b','#b0a87f');
    for(let i=0;i<3;i++) {
      this._poly([[-9,-18+i*6],[-2,-15+i*6],[-2,-12+i*6],[-9,-15+i*6]],'#bcad80');
      this._poly([[9,-18+i*6],[2,-15+i*6],[2,-12+i*6],[9,-15+i*6]],'#918f6b');
    }
    this._poly([[-20,-25],[-10,-28],[-7,-19],[-15,-12],[-22,-17]],'#a59770','#d0ba84');
    this._poly([[10,-28],[20,-25],[23,-17],[15,-12],[7,-19]],'#8e8c67','#c0af7c');
    this._poly([[-9,-37],[8,-37],[10,-29],[6,-21],[-6,-21],[-10,-29]],'#c7bf99','#716f54');
    this._poly([[-9,-35],[-14,-35],[-18,-44],[-16,-30],[-10,-27]],'#9b8860','#d0b77e');
    this._poly([[9,-35],[14,-35],[18,-44],[16,-30],[10,-27]],'#9b8860','#d0b77e');
    this._poly([[-8,-38],[-7,-45],[-3,-40],[0,-48],[3,-40],[8,-44],[8,-37]],'#b99a57','#eed295');
    c.fillStyle='#25312c'; c.fillRect(-7,-32,5,5); c.fillRect(3,-32,5,5);
    c.fillStyle=charging?'#ffe1a6':'#d8a278'; c.fillRect(-6,-30,4,2); c.fillRect(3,-30,4,2);
    this._poly([[0,-29],[-2,-25],[2,-25]],'#303b32');
    c.fillStyle='#dfd0a3'; c.fillRect(-4,-23,8,3); c.fillStyle='#5e5d45'; c.fillRect(-2,-23,1,3); c.fillRect(1,-23,1,3);
    c.strokeStyle='#9e7d50'; c.lineWidth=4; c.beginPath(); c.moveTo(20,18); c.lineTo(21,-29); c.stroke();
    this._poly([[20,-38],[27,-26],[23,-20],[19,-20],[15,-27]],charging?'#d89862':'#5f9b8a','#b9cc99');
    this._poly([[-24,-15],[-16,-19],[-10,-14],[-13,5],[-20,10],[-25,3]],'#546457','#b7a477');
    this._poly([[-20,-12],[-17,-7],[-20,0],[-23,-7]],'#c3af77');
  }

  _wisp() {
    const c=this.ctx;
    this._poly([[-10,7],[-6,-6],[-9,-13],[-3,-12],[1,-25],[6,-15],[10,-13],[8,-6],[11,3],[4,10],[0,6],[-4,11]],'#2c6b65');
    this._poly([[-5,3],[-4,-8],[1,-19],[5,-9],[6,1],[1,7]],'#79cdb2');
    this._ellipse(0,-7,5,6,'#c8e5c4');
    c.fillStyle='#1e4640'; c.fillRect(-3,-9,2,3); c.fillRect(2,-9,2,3);
  }

  _effects(t, dt) {
    const c = this.ctx;
    this.particles = this.particles.filter(p => this.clock - p.born < p.life);
    this.labels = this.labels.filter(p => this.clock - p.born < p.life);
    this.rings = this.rings.filter(p => this.clock - p.born < p.life);
    this.flashes = this.flashes.filter(p => p.until > this.clock);
    for (const p of this.particles) {
      const age = (this.clock - p.born) / p.life;
      p.x += p.vx * dt / 1000; p.y += p.vy * dt / 1000; p.vy += dt / 1300;
      c.globalAlpha = (1-age)*.85; c.fillStyle = p.color;
      const size = Math.max(1,p.size*t*(1-age*.4)); c.fillRect(p.x*t-size/2,p.y*t-size/2,size,size);
    }
    c.globalAlpha = 1;
    for(const ring of this.rings) {
      const age=(this.clock-ring.born)/ring.life;
      c.globalAlpha=(1-age)*.75; c.strokeStyle=ring.color; c.lineWidth=1.5;
      c.beginPath(); c.ellipse(ring.x*t,ring.y*t,t*(.2+age*(ring.type==='level'?1.9:.9)),t*(.1+age*.5),0,0,Math.PI*2); c.stroke();
      if(ring.tx!=null && ring.ty!=null) {
        const travel=Math.min(1,age*3);
        const x=(ring.x+(ring.tx-ring.x)*travel)*t, y=(ring.y+(ring.ty-ring.y)*travel)*t;
        this._glow(x,y,t*.32,'rgba(121,224,212,0.55)');
        this._ellipse(x,y,2.5,2.5,'#def8df');
      }
    }
    c.globalAlpha=1;
    c.textAlign='center'; c.textBaseline='middle';
    for(const label of this.labels) {
      const age=(this.clock-label.born)/label.life;
      c.globalAlpha=Math.min(1,(1-age)*3);
      const number=/^[+−\-]?\d+$/.test(label.text);
      c.font=`${number?'700':'600'} ${number?15:11}px ui-monospace, monospace`;
      const x=label.x*t, y=label.y*t-(this.reduceMotion ? 0 : age*t*.65);
      c.lineWidth=3; c.strokeStyle='rgba(4,9,10,0.92)'; c.strokeText(label.text,x,y);
      c.fillStyle=label.color; c.fillText(label.text,x,y);
    }
    c.globalAlpha=1;
  }
}

/* Ashen Vault: procedural camp. Shared hero art; no engine or economy writes. */
class AshenCampRenderer extends AshenRenderer {
  constructor(canvas) {
    super(canvas);
    this.reset();
  }

  reset() {
    this.clock = 0;
    this.lastTime = null;
    this.reduceMotion = false;
    this.layout = null;
    this.layoutKey = null;
    this.transform = null;
    this.hitAreas = [];
    this.hero = null;
    this.waypoints = [];
    this.destination = null;
    this.walkPhase = 0;
    this.view = null;
  }

  resize() {
    this._resize();
    const portrait = this.width / this.height < 1.18;
    const key = portrait ? 'portrait' : 'landscape';
    const w = portrait ? 660 : 1040, h = portrait ? 850 : 680;
    const scale = Math.min(this.width / w, this.height / h);
    this.transform = { x: (this.width - w * scale) / 2, y: (this.height - h * scale) / 2, scale, w, h };
    if (this.layoutKey !== key) {
      this.layoutKey = key;
      this.layout = portrait ? {
        portal: { x: 344, y: 256 }, fire: { x: 328, y: 523 }, spawn: { x: 333, y: 586 },
        hearth: { x: 163, y: 418 }, forge: { x: 471, y: 418 },
        garden: { x: 156, y: 661 }, archive: { x: 479, y: 656 },
        warden: { x: 218, y: 444 }, smith: { x: 419, y: 446 },
        herbalist: { x: 218, y: 681 }, archivist: { x: 421, y: 683 }
      } : {
        portal: { x: 540, y: 239 }, fire: { x: 534, y: 411 }, spawn: { x: 556, y: 511 },
        hearth: { x: 268, y: 476 }, forge: { x: 294, y: 300 },
        garden: { x: 797, y: 484 }, archive: { x: 809, y: 300 },
        warden: { x: 354, y: 484 }, smith: { x: 364, y: 324 },
        herbalist: { x: 722, y: 510 }, archivist: { x: 735, y: 332 }
      };
      const where = this.destination && this.layout[this.destination];
      const atPortal = this.destination === 'portal';
      this.hero = { x: where ? where.x + (atPortal ? 0 : where.x < w / 2 ? 31 : -31) : this.layout.spawn.x,
        y: where ? where.y + (atPortal ? 43 : 29) : this.layout.spawn.y, facing: 'up', walking: false };
      this.waypoints = [];
    }
  }

  hitTest(clientX, clientY) {
    if (!this.transform || !this.view || !Number.isFinite(clientX) || !Number.isFinite(clientY)) return null;
    const rect = this.canvas.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) return null;
    const px = (clientX - rect.left) * this.width / rect.width;
    const py = (clientY - rect.top) * this.height / rect.height;
    if (px < 0 || py < 0 || px >= this.width || py >= this.height) return null;
    const { x, y, scale } = this.transform;
    const wx = (px - x) / scale, wy = (py - y) / scale;
    const matches = this.hitAreas.filter(a => wx >= a.x && wx <= a.x + a.w && wy >= a.y && wy <= a.y + a.h);
    matches.sort((a, b) => Math.hypot(wx - a.cx, wy - a.cy) - Math.hypot(wx - b.cx, wy - b.cy));
    return matches.length ? { type: matches[0].type, id: matches[0].id } : null;
  }

  visit(id) {
    if (!['warden', 'smith', 'herbalist', 'archivist', 'portal'].includes(id)) return false;
    this.destination = id;
    if (!this.layout || !this.hero) return true;
    const p = this.layout[id], fire = this.layout.fire;
    const target = id === 'portal' ? { x: p.x, y: p.y + 43 } : {
      x: p.x + (p.x < this.transform.w / 2 ? 31 : -31), y: p.y + 29
    };
    this.waypoints = [];
    if (Math.hypot(this.hero.x - target.x, this.hero.y - target.y) > 150) {
      // The open circle around the campfire is a visual path, not a gameplay pathfinder.
      this.waypoints.push({ x: fire.x + (target.x < fire.x ? -34 : 34), y: fire.y + 49 });
    }
    this.waypoints.push(target);
    if (this.reduceMotion) this._advance(0);
    return true;
  }

  _advance(dt) {
    if (!this.hero) return;
    if (this.reduceMotion && this.waypoints.length) {
      Object.assign(this.hero, this.waypoints[this.waypoints.length - 1]);
      this.waypoints = [];
    }
    let remaining = dt * .135;
    this.hero.walking = false;
    while (this.waypoints.length && remaining > 0) {
      const p = this.waypoints[0], dx = p.x - this.hero.x, dy = p.y - this.hero.y;
      const distance = Math.hypot(dx, dy);
      if (distance < .001) { this.waypoints.shift(); continue; }
      const moved = Math.min(distance, remaining);
      this.hero.x += dx / distance * moved;
      this.hero.y += dy / distance * moved;
      this.hero.facing = Math.abs(dx) > Math.abs(dy) ? dx < 0 ? 'left' : 'right' : dy < 0 ? 'up' : 'down';
      this.hero.walking = true;
      this.walkPhase += moved * .12;
      remaining -= moved;
      if (distance <= moved) this.waypoints.shift();
    }
    if (!this.waypoints.length) this.hero.walking = false;
  }

  draw(view, timeMs, { reduceMotion = false, selectedNpc = null, hoverTarget = null } = {}) {
    if (!view || !this.ctx) return;
    this.resize();
    this.view = view;
    this.reduceMotion = !!reduceMotion;
    const time = Number.isFinite(timeMs) ? timeMs : 0;
    const dt = this.lastTime == null ? 0 : Math.max(0, Math.min(80, time - this.lastTime));
    this.lastTime = time;
    if (!this.reduceMotion) this.clock += dt;
    this._advance(dt);
    this.sceneTime = this.reduceMotion ? 0 : this.clock;
    this.hitAreas = [];
    const c = this.ctx, tr = this.transform;
    c.globalAlpha = 1;
    c.globalCompositeOperation = 'source-over';
    c.fillStyle = '#0a171b'; c.fillRect(0, 0, this.width, this.height);
    c.save(); c.translate(tr.x, tr.y); c.scale(tr.scale, tr.scale);
    this._landscape(tr.w, tr.h);
    this._paths();
    this._ruins(this.layout.portal.x, this.layout.portal.y);
    const buildings = Array.isArray(view.buildings) ? view.buildings : Object.entries(view.buildings || {}).map(([id, level]) => ({ id, level: typeof level === 'object' ? level.level : level }));
    const byId = Object.fromEntries(buildings.map(b => [b.id, b]));
    const actors = ['hearth', 'forge', 'garden', 'archive'].map(id => ({ y: this.layout[id].y, draw: () => {
      const b = byId[id] || { level: 0 }, level = Math.min(3, Math.max(0, Number(b.level) || 0));
      this._building(id, this.layout[id].x, this.layout[id].y, level, !!b.canUpgrade);
    }}));
    actors.push({ y: this.layout.fire.y + 9, draw: () => this._campfire(this.layout.fire.x, this.layout.fire.y) });
    const defaults = { warden: ['Страж', '#d6b27c'], smith: ['Кузнец', '#d4926d'], herbalist: ['Травница', '#8ebca5'], archivist: ['Архивариус', '#aaa7ca'] };
    const npcs = Array.isArray(view.npcs) ? view.npcs : [];
    for (const id of Object.keys(defaults)) {
      const npc = npcs.find(n => n.id === id) || { id, name: defaults[id][0], color: defaults[id][1] };
      const p = this.layout[id], quests = (Array.isArray(view.quests) ? view.quests : []).filter(q => q.npc === id);
      const status = quests.some(q => q.status === 'ready') ? 'ready' : quests.some(q => q.status === 'available') ? 'available' : quests.some(q => q.status === 'active') ? 'active' : 'none';
      const selected = selectedNpc === id || (hoverTarget && (hoverTarget.id || hoverTarget) === id);
      actors.push({ y: p.y + 8, draw: () => this._npc(npc, p.x, p.y, status, selected) });
    }
    actors.push({ y: this.hero.y + 10, draw: () => this._traveller(view.classId || 'warden') });
    actors.sort((a, b) => a.y - b.y);
    for (const actor of actors) actor.draw();
    this._foreground(tr.w, tr.h);
    for (const id of Object.keys(defaults)) {
      const npc = npcs.find(n => n.id === id) || { id, name: defaults[id][0], color: defaults[id][1] };
      const p = this.layout[id];
      const label = this._nameplate(npc.name, p.x, p.y + 35, npc.color || defaults[id][1]);
      // The quest diamond reaches above the head; a label can grow when the
      // scene is small. Both visible affordances belong to the same target.
      const min = 44 / tr.scale, width = Math.max(94, min, label.w);
      const top = p.y - 80, bottom = Math.max(p.y + 40, label.y + label.h);
      this.hitAreas.push({ type: 'npc', id, x: p.x - width / 2, y: top, w: width, h: Math.max(bottom - top, min), cx: p.x, cy: p.y - 10 });
    }
    const portal = this.layout.portal;
    this._nameplate('В подземелье', portal.x, portal.y + 57, '#b4c8be', true);
    const portalWidth = Math.max(142, 44 / tr.scale), portalHeight = Math.max(204, 44 / tr.scale);
    this.hitAreas.push({ type: 'portal', id: 'portal', x: portal.x - portalWidth / 2, y: portal.y - 30 - portalHeight / 2, w: portalWidth, h: portalHeight, cx: portal.x, cy: portal.y - 30 });
    c.restore();
  }

  _landscape(w, h) {
    const c = this.ctx, sky = c.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, '#152932'); sky.addColorStop(.28, '#22383b'); sky.addColorStop(.48, '#263632'); sky.addColorStop(1, '#172723');
    c.fillStyle = sky; c.fillRect(-200, -200, w + 400, h + 400);
    this._poly([[-90,210],[w*.09,114],[w*.18,146],[w*.28,85],[w*.4,168],[w*.54,83],[w*.62,133],[w*.74,109],[w*.92,172],[w+70,106],[w+100,h+100],[-100,h+100]], '#172b31');
    const clearing = c.createRadialGradient(w / 2, h * .64, 20, w / 2, h * .64, w * .63);
    clearing.addColorStop(0, '#394138'); clearing.addColorStop(.64, '#2b3830'); clearing.addColorStop(1, 'rgba(28,44,36,0)');
    c.fillStyle = clearing; c.fillRect(-20, -20, w + 40, h + 40);
    this._glow(w * .73, 90, 128, 'rgba(151,194,181,.12)');
    this._ellipse(w * .73, 87, 22, 22, '#81988f');
    this._ellipse(w * .73 - 7, 83, 19, 21, '#20333b');
    for (let i = 0; i < 45; i++) {
      const x = this._hash(i, 1, 34) * w, y = 14 + this._hash(i, 2, 12) * 149;
      c.fillStyle = `rgba(185,203,187,${.11 + this._hash(i, 3, 4) * .24})`;
      c.fillRect(x, y, i % 7 === 0 ? 2 : 1, 1);
    }
    for (let layer = 0; layer < 3; layer++) {
      for (let i = 0; i < 23; i++) {
        const x = (i - 1) * w / 20 + this._hash(i, layer, 13) * 36;
        const y = 187 + layer * 32 + this._hash(i, layer, 99) * 22;
        this._pine(x, y, 68 + this._hash(i, layer, 77) * 93, layer === 0 ? '#1c3439' : layer === 1 ? '#182e30' : '#162b29');
      }
    }
    for (let i = 0; i < 205; i++) {
      const x = this._hash(i, 4, 29) * w, y = 268 + this._hash(i, 8, 61) * (h - 230);
      const r = this._hash(i, 12, 77);
      if (r > .7) {
        c.strokeStyle = r > .9 ? '#566048' : '#394d3b'; c.lineWidth = .8;
        c.beginPath(); c.moveTo(x - 2, y); c.lineTo(x - 5, y - 6); c.moveTo(x, y); c.lineTo(x, y - 9); c.moveTo(x + 2, y); c.lineTo(x + 5, y - 4); c.stroke();
      } else this._ellipse(x, y, 1 + r * 3, .5 + r, r > .45 ? '#566050' : '#23352d');
    }
    // Low drifting mist stays behind characters and interactive labels.
    for (let i = 0; i < 5; i++) {
      const dx = this.reduceMotion ? 0 : Math.sin(this.sceneTime * .00008 + i) * 23;
      const fog = c.createRadialGradient(w * i / 4 + dx, 239 + i * 12, 2, w * i / 4 + dx, 239 + i * 12, w * .28);
      fog.addColorStop(0, 'rgba(148,177,155,.045)'); fog.addColorStop(1, 'rgba(148,177,155,0)');
      c.fillStyle = fog; c.fillRect(-20, -20, w + 40, h + 40);
    }
  }

  _pine(x, y, size, color) {
    const c = this.ctx;
    c.fillStyle = '#172b28'; c.fillRect(x - size * .03, y - size * .63, size * .06, size * .67);
    for (let i = 0; i < 4; i++) {
      const half = size * (.1 + i * .05), top = y - size + i * size * .17, bottom = top + size * .39;
      this._poly([[x,top],[x+half*.86,bottom-7],[x+half*.52,bottom-6],[x+half,bottom+2],[x+2,bottom-2],[x-half,bottom+2],[x-half*.65,bottom-6],[x-half*.9,bottom-4]], color);
    }
  }

  _paths() {
    const c = this.ctx, f = this.layout.fire;
    c.lineCap = 'round'; c.lineJoin = 'round';
    for (const id of ['portal', 'warden', 'smith', 'herbalist', 'archivist']) {
      const p = this.layout[id];
      c.strokeStyle = '#394035'; c.lineWidth = id === 'portal' ? 49 : 34;
      c.beginPath(); c.moveTo(f.x, f.y + 22); c.quadraticCurveTo(f.x * .5 + p.x * .5, f.y * .65 + p.y * .35 + 25, p.x, p.y + 22); c.stroke();
      c.strokeStyle = 'rgba(145,133,91,.09)'; c.lineWidth = id === 'portal' ? 25 : 14; c.stroke();
    }
    this._ellipse(f.x, f.y + 11, 125, 80, '#3b4033');
    this._ellipse(f.x, f.y + 12, 111, 70, '#3e4133');
    for (let i = 0; i < 33; i++) {
      const a = i / 33 * Math.PI * 2, r = 104 + this._hash(i, 6, 1) * 7;
      this._rock(f.x + Math.cos(a) * r, f.y + 12 + Math.sin(a) * r * .62, 4 + this._hash(i, 1, 1) * 4);
    }
    c.lineCap = 'butt';
  }

  _rock(x, y, size) {
    this._ellipse(x + 1, y + 2, size * 1.25, size * .5, 'rgba(8,15,13,.32)');
    this._poly([[x-size,y],[x-size*.55,y-size*.62],[x+size*.35,y-size*.72],[x+size,y-size*.15],[x+size*.7,y+size*.28],[x-size*.6,y+size*.36]], '#525b4c', '#252f29', .6);
    this._poly([[x-size*.55,y-size*.62],[x+size*.35,y-size*.72],[x+size*.6,y-size*.16],[x-size*.3,y-size*.05]], '#646b58');
  }

  _ruins(x, y) {
    const c = this.ctx;
    c.save(); c.translate(x, y);
    this._ellipse(0, 15, 123, 28, 'rgba(5,14,16,.43)');
    this._poly([[-139,-6],[-121,-42],[-113,-90],[-85,-86],[-67,-152],[-43,-141],[-15,-177],[20,-161],[43,-158],[73,-121],[92,-91],[121,-55],[139,-4]], '#34413d');
    this._poly([[-139,-6],[-113,-48],[-93,-64],[-72,-135],[-41,-136],[-57,-64],[-79,-13]], '#47514a');
    this._poly([[57,-119],[72,-116],[105,-46],[127,-23],[131,-4],[80,-7]], '#202e2d');
    c.fillStyle = '#142223'; c.fillRect(-46, -79, 92, 89);
    c.beginPath(); c.arc(0, -75, 46, Math.PI, 0); c.fill();
    for (let side of [-1, 1]) for (let i = 0; i < 4; i++) {
      const sx = side < 0 ? -67 : 46, sy = -79 + i * 22;
      c.fillStyle = i % 2 ? '#616657' : '#555f54'; c.fillRect(sx, sy, 21, 20);
      c.fillStyle = '#79806b'; c.fillRect(sx + 1, sy, 18, 2);
      c.strokeStyle = '#2c3b35'; c.lineWidth = 1; c.strokeRect(sx, sy, 21, 20);
    }
    for (let i = 0; i < 9; i++) {
      const a = Math.PI + i * Math.PI / 9, b = Math.PI + (i + .91) * Math.PI / 9;
      this._poly([[Math.cos(a)*47,-76+Math.sin(a)*47],[Math.cos(a)*69,-76+Math.sin(a)*69],[Math.cos(b)*69,-76+Math.sin(b)*69],[Math.cos(b)*47,-76+Math.sin(b)*47]], i%2?'#66705f':'#586455', '#34443c');
    }
    this._glow(0, -29, 77, 'rgba(81,168,151,.17)');
    for (let i = 0; i < 5; i++) {
      c.fillStyle = ['#47554b','#3b4b43','#30413c','#273936','#1c2f2e'][i];
      c.fillRect(-43 + i * 5, 4 - i * 11, 86 - i * 10, 6);
      c.fillStyle = 'rgba(147,172,141,.15)'; c.fillRect(-43 + i * 5, 4 - i * 11, 86 - i * 10, 1);
    }
    for (let i = 0; i < 12; i++) this._rock((i < 6 ? -1 : 1) * (73 + this._hash(i, 31, 8) * 53), this._hash(i, 51, 8) * 12, 5 + this._hash(i, 11, 8) * 8);
    c.strokeStyle = '#567561'; c.lineWidth = 2;
    c.beginPath(); c.moveTo(-105, -9); c.bezierCurveTo(-99,-72,-41,-28,-47,-126); c.moveTo(70,-10); c.bezierCurveTo(108,-47,62,-61,71,-104); c.stroke();
    for (let i = 0; i < 10; i++) {
      const side = i < 5 ? -1 : 1, px = side * (57 + this._hash(i, 5, 5) * 32), py = -17 - this._hash(i, 6, 5) * 77;
      this._ellipse(px, py, 5, 2, '#63795d');
    }
    this._lantern(-79, -29, .85); this._lantern(78, -26, .85);
    c.restore();
  }

  _building(id, x, y, level, canUpgrade) {
    const c = this.ctx;
    c.save(); c.translate(x, y);
    this._ellipse(3, 12, id === 'garden' ? 96 : 83, 30, 'rgba(7,17,16,.31)');
    if (id === 'garden') this._garden(level);
    else if (level === 0) this._worksite(id);
    else this._house(id, level);
    const colors = { hearth: '#bd9b68', forge: '#c68c66', garden: '#8aad83', archive: '#a7a4bf' };
    for (let i = 0; i < 3; i++) {
      const dx = (i - 1) * 11, dy = id === 'garden' ? 33 : 24;
      this._poly([[dx,dy-3],[dx+3,dy],[dx,dy+3],[dx-3,dy]], i < level ? colors[id] : '#273833', i < level ? '#d9c89a' : '#677060', .65);
    }
    if (canUpgrade) {
      c.strokeStyle = 'rgba(218,187,121,.62)'; c.lineWidth = 1;
      c.beginPath(); c.moveTo(-29, 24); c.lineTo(-24, 19); c.lineTo(-19, 24); c.moveTo(19,24); c.lineTo(24,19); c.lineTo(29,24); c.stroke();
    }
    c.restore();
  }

  _worksite(id) {
    const c = this.ctx;
    const colors = { hearth: ['#746c48','#aaa071'], forge: ['#73513e','#ad7b51'], archive: ['#4a6264','#82989b'] };
    const [roof, edge] = colors[id];
    for (const x of [-62, 61]) {
      c.fillStyle = '#67513a'; c.fillRect(x - 2, -64, 4, 70);
      c.fillStyle = '#a08a62'; c.fillRect(x - 2, -64, 1, 70);
    }
    this._poly([[-66,-57],[0,-88],[66,-53],[56,-36],[-2,-59],[-60,-40]], roof, edge);
    c.strokeStyle = 'rgba(224,203,149,.21)'; c.lineWidth = 1;
    c.beginPath(); c.moveTo(0,-87); c.lineTo(-2,-60); c.lineTo(55,-38); c.moveTo(-30,-68); c.lineTo(-32,-49); c.stroke();
    this._poly([[-48,1],[-45,-14],[39,-14],[47,1]], '#6b5438', '#968260');
    c.fillStyle = '#433e2e'; c.fillRect(-41, 0, 6, 13); c.fillRect(35, 0, 6, 13);
    if (id === 'forge') { this._anvil(-3, -15); this._coals(52, 6, .55); }
    else if (id === 'archive') { this._books(-22, -15); this._books(16, -16); this._crystal(34, -28, .65); }
    else { this._banner(-42, -69, '#9e7044', 0); this._lantern(31,-27,.58); this._bedroll(-19,6); }
    this._crate(-71, 8, .72); this._logs(46, 15, .8);
  }

  _house(id, level) {
    const c = this.ctx, stone = level >= 2;
    const wide = level === 3 ? 76 : 65, high = level === 3 ? 83 : 68;
    const palette = { hearth: ['#6e6245','#a08a55'], forge: ['#714c37','#ac744a'], archive: ['#486269','#7f9997'] };
    const [roof, trim] = palette[id];
    this._poly([[-wide,4],[-wide,-high],[wide*.65,-high],[wide,4]], stone ? '#53584a' : '#685b41', '#28342c');
    this._poly([[wide*.65,-high],[wide+12,-high+18],[wide+12,4],[wide,10],[wide,4]], '#343e34');
    if (stone) {
      for (let row = 0; row < 5; row++) for (let col = 0; col < 6; col++) {
        const bx = -wide + 4 + col * 22 + (row % 2 ? 9 : 0), by = 2 - row * 14;
        if (bx > wide - 17) continue;
        c.strokeStyle = 'rgba(21,36,29,.42)'; c.lineWidth = 1; c.strokeRect(bx, by - 12, 20, 12);
        c.fillStyle = 'rgba(177,172,130,.16)'; c.fillRect(bx+1,by-12,18,1);
      }
    } else for (let i = 0; i < 5; i++) { c.fillStyle = '#3d4130'; c.fillRect(-wide+2, -high+8+i*12, wide*1.63, 2); }
    for (const sx of [-wide+2, wide*.65-6]) { c.fillStyle = '#564832'; c.fillRect(sx, -high, 7, high+7); c.fillStyle='#8e7b50'; c.fillRect(sx, -high, 2, high+6); }
    this._poly([[-wide-14,-high+2],[-9,-high-48],[wide+21,-high+6],[wide+9,-high+19],[-10,-high-30],[-wide-10,-high+16]], roof, trim);
    for (let i = 0; i < 5; i++) {
      const yy = -high-35+i*9;
      c.strokeStyle = 'rgba(25,36,29,.31)'; c.lineWidth = 2;
      c.beginPath(); c.moveTo(-13+i*-12, yy); c.lineTo(-7+i*16, yy+3); c.stroke();
    }
    c.fillStyle = '#252e25'; c.fillRect(-15, -44, 31, 49);
    this._poly([[-19,-43],[0,-55],[20,-43]], '#3d493b', '#a59764');
    c.fillStyle = '#746444'; c.fillRect(-11,-41,23,45);
    for (let i = 0; i < 3; i++) { c.fillStyle = '#514d33'; c.fillRect(-8+i*7,-37,1,39); }
    c.fillStyle = '#bda873'; c.fillRect(6,-15,3,4);
    this._window(-42, -32, id === 'archive' ? '#a8cab3' : '#e1a957');
    if (level >= 2) this._window(39, -30, id === 'archive' ? '#a8cab3' : '#e1a957');
    if (id === 'forge') {
      this._poly([[wide-11,-high-17],[wide-11,-high-64],[wide+10,-high-59],[wide+10,-high+2]], '#596053', '#354337');
      c.fillStyle='#889080'; c.fillRect(wide-14,-high-67,28,7);
      if (!this.reduceMotion) for (let i=0;i<4;i++) { const p=(this.sceneTime*.00022+i*.23)%1; this._ellipse(wide+1+Math.sin(p*5)*9,-high-67-p*50,5+p*10,6+p*8,`rgba(142,152,126,${(1-p)*.11})`); }
      this._anvil(-66, 4); this._coals(47, 10, .5); this._logs(84, 13, .95);
    } else if (id === 'archive') {
      this._books(-70, 9); this._crystal(62, -19, level === 3 ? 1.15 : .85);
      if (level === 3) {
        c.strokeStyle='#8aaea4'; c.lineWidth=1.2; c.beginPath(); c.arc(-7,-high-39,15,0,Math.PI*2); c.stroke();
        this._poly([[-7,-high-57],[-3,-high-39],[-7,-high-21],[-11,-high-39]], '#b1c3ac');
      }
    } else {
      this._banner(-wide+13,-high+11,level===3?'#b28d49':'#966540',level);
      this._crate(wide+6,15,.65); this._bedroll(-67,13);
    }
    this._lantern(22,-44,.55);
    if (level === 3) { this._lantern(-wide-5,-19,.65); this._crate(-wide-6,16,.6); }
  }

  _garden(level) {
    const c=this.ctx;
    this._poly([[-82,7],[-61,-58],[69,-58],[90,8]], '#504d35','#797950');
    for (let row=0;row<3;row++) {
      const yy=-43+row*18;
      this._poly([[-65+row*-5,yy],[-61+row*-5,yy-4],[63+row*6,yy-4],[67+row*6,yy]], '#716548');
      for (let col=0;col<5;col++) {
        const x=-47+col*25, growth=level ? (9+level*3) : 5, y=yy+7;
        c.strokeStyle=level?'#75915b':'#51654b'; c.lineWidth=1.4; c.beginPath(); c.moveTo(x,y+3); c.lineTo(x,y-growth); c.stroke();
        this._poly([[x,y-3],[x-8,y-growth+2],[x-10,y-growth-1],[x-1,y-growth+5]], level?'#6b8f59':'#496045');
        this._poly([[x,y-3],[x+9,y-growth-1],[x+11,y-growth-4],[x+1,y-growth+3]], level?'#89a261':'#5d714b');
        if (level>=2 && col%2===row%2) this._ellipse(x,y-growth,3,3,row%2?'#c5ac6d':'#a88db2');
      }
    }
    for (const x of [-85, 83]) {
      c.fillStyle='#65573a'; c.fillRect(x,-67,4,79);
      c.fillStyle='#ac9b69'; c.fillRect(x,-67,1,79);
    }
    c.strokeStyle='#8b8056'; c.lineWidth=2; c.beginPath(); c.moveTo(-83,-55); c.lineTo(-22,-65); c.lineTo(28,-66); c.lineTo(86,-55); c.stroke();
    if (level===0) { this._bedroll(-45,-52); this._basket(76,16); }
    if (level>=1) {
      this._poly([[-93,-63],[-34,-99],[64,-95],[97,-65],[43,-58],[-44,-58]], '#48695a','#879a69');
      c.strokeStyle='#627e5b'; c.lineWidth=1; c.beginPath(); c.moveTo(-34,-98); c.lineTo(-44,-59); c.moveTo(24,-97); c.lineTo(17,-59); c.moveTo(64,-94); c.lineTo(43,-58); c.stroke();
      this._basket(-70,13); this._basket(75,15);
    }
    if (level>=2) {
      for (const x of [-38,-9,19,47]) {
        c.strokeStyle='#a89b69'; c.lineWidth=1; c.beginPath(); c.moveTo(x,-60); c.lineTo(x,-42); c.stroke();
        this._poly([[x,-38],[x-6,-51],[x+3,-47],[x+5,-53],[x+8,-41],[x+1,-37]], '#87a36b');
      }
      this._lantern(-85,-37,.55);
    }
    if (level===3) {
      this._ellipse(0,13,37,12,'#56644c'); this._ellipse(0,10,33,10,'#a4ac7b'); this._ellipse(0,9,28,7,'#376f67');
      this._crystal(0,-3,.6);
      for (let i=0;i<8;i++) this._ellipse(-62+i*18,23+Math.sin(i)*4,2,2,i%2?'#ad97c5':'#c9bb8d');
    }
  }

  _window(x,y,color) {
    const c=this.ctx;
    this._glow(x,y,28,'rgba(232,174,79,.1)');
    c.fillStyle='#242e25'; c.fillRect(x-11,y-15,22,26);
    c.fillStyle=color; c.fillRect(x-8,y-12,16,20);
    c.fillStyle='#504c32'; c.fillRect(x-1,y-12,2,20); c.fillRect(x-8,y-3,16,2);
    c.fillStyle='#a7996e'; c.fillRect(x-12,y+10,24,3);
  }

  _banner(x,y,color,level) {
    const c=this.ctx, sway=this.reduceMotion?0:Math.sin(this.sceneTime*.0015+x)*2;
    c.strokeStyle='#b4a779'; c.lineWidth=2; c.beginPath(); c.moveTo(x-10,y); c.lineTo(x+13,y); c.stroke();
    this._poly([[x-8,y+1],[x+10,y+1],[x+10+sway,y+39],[x+sway,y+34],[x-8+sway,y+42]],color,'#5b4d33');
    this._poly([[x+1,y+11],[x+5,y+18],[x+1,y+25],[x-3,y+18]],'#d4bc78');
    if(level===3){c.fillStyle='#dac188';c.fillRect(x-6,y+4,14,1);c.fillRect(x-6,y+29,13,1);}
  }

  _crate(x,y,s) {
    const c=this.ctx;c.save();c.translate(x,y);c.scale(s,s);
    this._poly([[-17,0],[-17,-24],[13,-24],[20,-18],[20,1],[14,6]],'#554a32','#90815b');
    this._poly([[-17,-24],[13,-24],[20,-18],[-11,-17]],'#8a7850');
    c.strokeStyle='#b09a63';c.lineWidth=2;c.beginPath();c.moveTo(-14,-21);c.lineTo(13,2);c.moveTo(12,-21);c.lineTo(-14,2);c.moveTo(15,-17);c.lineTo(15,2);c.stroke();c.restore();
  }

  _logs(x,y,s) {
    const c=this.ctx;c.save();c.translate(x,y);c.scale(s,s);
    for(let i=0;i<5;i++){const xx=(i%3)*9-12,yy=-Math.floor(i/3)*7;c.fillStyle='#594732';c.fillRect(xx-12,yy-5,24,7);this._ellipse(xx+12,yy-1,4,4,'#a18b5b');this._ellipse(xx+12,yy-1,2,2,'#675334');}c.restore();
  }

  _bedroll(x,y) {this._ellipse(x,y,21,6,'#414638');this._poly([[x-20,y-2],[x-16,y-12],[x+15,y-11],[x+20,y-1]],'#738065','#a2aa83');this._ellipse(x-16,y-6,5,7,'#879275');}

  _books(x,y) {
    const c=this.ctx;for(let i=0;i<3;i++){c.fillStyle=['#6e7660','#9d895c','#715d50'][i];c.fillRect(x-12+(i%2)*3,y-i*5-4,25,5);c.fillStyle='#b2af85';c.fillRect(x-10+(i%2)*3,y-i*5-3,21,2);}
  }

  _basket(x,y) {this._ellipse(x,y,12,5,'#695234');this._poly([[x-11,y-1],[x-8,y+10],[x+8,y+10],[x+11,y-1]],'#89734a','#b09b64');for(let i=0;i<4;i++)this._ellipse(x-7+i*4,y-3-i%2*3,4,4,i%2?'#899a53':'#a4aa66');}

  _anvil(x,y) {const c=this.ctx;c.save();c.translate(x,y);this._poly([[-18,11],[-14,1],[12,1],[15,11]],'#6c6550','#9e9573');this._poly([[-12,1],[-9,-12],[9,-12],[10,1]],'#3d4a45');this._poly([[-25,-16],[-21,-20],[13,-20],[26,-16],[12,-10],[-17,-10]],'#88918a','#afb4a0');c.fillStyle='#515f59';c.fillRect(-14,-15,26,5);c.restore();}

  _crystal(x,y,s) {const c=this.ctx;c.save();c.translate(x,y);c.scale(s,s);this._glow(0,-12,26,'rgba(117,188,172,.18)');this._poly([[0,-34],[9,-20],[6,-4],[0,1],[-7,-5],[-10,-20]],'#80bbae','#c3d5bc');this._poly([[0,-34],[0,1],[-7,-5],[-10,-20]],'#426e71');c.restore();}

  _lantern(x,y,s=1) {const c=this.ctx;c.save();c.translate(x,y);c.scale(s,s);this._glow(0,0,45,'rgba(234,154,65,.17)');c.fillStyle='#49462e';c.fillRect(-5,-8,10,17);c.fillStyle='#e6b970';c.fillRect(-3,-6,6,12);c.fillStyle='#fff0b0';c.fillRect(-1,-4,2,7);c.strokeStyle='#b0a173';c.lineWidth=1;c.strokeRect(-5,-8,10,17);c.beginPath();c.arc(0,-10,4,Math.PI,0);c.stroke();c.restore();}

  _coals(x,y,s=1) {
    const c=this.ctx;c.save();c.translate(x,y);c.scale(s,s);
    this._glow(0,-5,57,'rgba(240,136,52,.18)');this._ellipse(0,5,23,10,'#212923');
    for(let i=0;i<8;i++)this._rock(Math.cos(i*Math.PI/4)*22,Math.sin(i*Math.PI/4)*11,5);
    for(let i=0;i<5;i++) {const sway=this.reduceMotion?0:Math.sin(this.sceneTime*.006+i*2)*4,xx=(i-2)*6;this._poly([[xx-5,3],[xx-6,-5],[xx+sway,-19-i%3*7],[xx+4,-6],[xx+5,3]],i%2?'#e7a34e':'#c47435');this._poly([[xx-2,3],[xx+sway*.4,-10-i%2*5],[xx+3,3]],'#f0d086');}
    c.restore();
  }

  _campfire(x,y) {
    const c=this.ctx;
    this._glow(x,y,171,'rgba(204,124,49,.14)');this._glow(x,y-7,93,'rgba(238,152,57,.12)');
    this._logs(x,y+3,.98);this._coals(x,y,1.25);
    if (!this.reduceMotion) for(let i=0;i<11;i++) {
      const p=(this.sceneTime*.00018+i*.09)%1, drift=Math.sin(i*5+p*4)*9;
      c.fillStyle=`rgba(240,176,88,${(1-p)*.7})`;c.fillRect(x+drift+(i%3-1)*9,y-13-p*79,1.2,2);
    }
    const cX=x-58,cY=y+30;
    c.strokeStyle='#766144';c.lineWidth=4;c.beginPath();c.moveTo(cX-20,cY+5);c.lineTo(cX-16,cY-9);c.lineTo(cX+18,cY-9);c.lineTo(cX+22,cY+5);c.stroke();
    c.fillStyle='#95835a';c.fillRect(cX-24,cY-13,49,6);
    this._crate(x+70,y+26,.65);
  }

  _npc(npc,x,y,status,selected) {
    const c=this.ctx,id=npc.id,color=npc.color||'#c7b48a';
    if (selected) {this._glow(x,y,46,'rgba(234,202,133,.11)');c.strokeStyle='#d8ba79';c.lineWidth=1.5;c.beginPath();c.ellipse(x,y+11,23,10,0,0,Math.PI*2);c.stroke();}
    this._ellipse(x,y+12,17,6,'rgba(5,15,14,.48)');
    c.save();c.translate(x,y);c.scale(1.16,1.16);
    const bob=this.reduceMotion?0:Math.sin(this.sceneTime*.0018+x)*.6;c.translate(0,bob);
    c.fillStyle='#302f25';c.fillRect(-7,3,5,12);c.fillRect(3,3,5,12);c.fillStyle='#645741';c.fillRect(-9,12,8,4);c.fillRect(2,12,9,4);
    const colors={warden:['#7f6644','#c5a565'],smith:['#6a4232','#bd8f66'],herbalist:['#4c6953','#a3b980'],archivist:['#565e72','#9eb4b3']};
    const [cloth,trim]=colors[id];
    this._poly([[-9,-16],[7,-16],[13,9],[5,13],[-1,10],[-8,12],[-13,8]],cloth,'#24302b');
    this._poly([[-8,-11],[-2,-15],[-3,6],[-9,8]],trim);
    c.fillStyle='#403827';c.fillRect(-9,0,19,3);c.fillStyle='#bea776';c.fillRect(-1,0,3,3);
    this._ellipse(0,-22,8,9,'#b49b77');
    if(id==='warden') {this._poly([[-9,-20],[-7,-29],[0,-34],[8,-29],[10,-20],[5,-22],[-5,-22]],'#879181','#bcc0a2');c.fillStyle='#444f48';c.fillRect(-1,-31,3,12);this._poly([[-8,-14],[-2,-16],[8,-13],[4,-5],[-5,-6]],'#bbb28d');c.strokeStyle='#b4a176';c.lineWidth=2;c.beginPath();c.moveTo(14,-27);c.lineTo(14,15);c.stroke();this._poly([[14,-37],[18,-29],[14,-24],[10,-29]],'#adb8a5');}
    else if(id==='smith') {this._poly([[-8,-24],[-5,-29],[5,-29],[9,-24],[8,-21],[-7,-21]],'#433c2e');this._poly([[-5,-20],[0,-16],[5,-21],[5,-13],[0,-9],[-5,-14]],'#594637');this._poly([[-4,-12],[5,-12],[9,9],[-5,9]],'#9a704c');c.fillStyle='#b29c7a';c.fillRect(-17,-12,7,12);c.fillRect(10,-12,7,12);c.save();c.translate(16,-4);c.rotate(this.reduceMotion?-.28:-.28+Math.sin(this.sceneTime*.002)*.07);c.fillStyle='#94794a';c.fillRect(-1,-13,3,19);c.fillStyle='#9da59a';c.fillRect(-7,-17,15,8);c.restore();}
    else if(id==='herbalist') {this._poly([[-10,-20],[-8,-30],[0,-36],[8,-30],[11,-19],[6,-23],[0,-26],[-6,-22]],'#77865b','#a8b580');c.strokeStyle='#86966a';c.lineWidth=2;c.beginPath();c.moveTo(-3,-9);c.lineTo(-5,9);c.stroke();c.fillStyle='#ac9879';c.fillRect(10,-10,5,9);this._basket(15,1);this._poly([[-13,-9],[-22,-19],[-17,-12],[-22,-9],[-13,-6]],'#94b276');}
    else {this._poly([[-10,-18],[-8,-29],[0,-34],[9,-28],[10,-18],[4,-22],[-4,-22]],'#586574','#929cb4');this._poly([[-5,-18],[0,-15],[6,-18],[4,-8],[0,-4],[-4,-9]],'#b6b6a3');this._poly([[-1,-6],[14,-11],[17,2],[3,8],[-9,4],[-11,-8]],'#bcb68e','#ddd1a3');c.strokeStyle='#747c70';c.lineWidth=1;c.beginPath();c.moveTo(1,-5);c.lineTo(3,7);c.moveTo(5,-3);c.lineTo(12,-6);c.moveTo(6,0);c.lineTo(13,-3);c.stroke();}
    c.fillStyle='#242e29';c.fillRect(-4,-23,2,2);c.fillRect(3,-23,2,2);
    c.restore();
    if (status!=='none') {
      const markerY=y-65, markerColor=status==='ready'?'#a3ccb0':status==='available'?'#e4c17c':'#91a8af';
      const rise=this.reduceMotion?0:Math.sin(this.sceneTime*.003+x)*1.2;
      this._glow(x,markerY,23,status==='ready'?'rgba(140,205,170,.11)':'rgba(231,193,121,.08)');
      this._poly([[x,markerY-12+rise],[x+11,markerY+rise],[x,markerY+12+rise],[x-11,markerY+rise]],'#1c2d28',markerColor,1.2);
      if(status==='ready') {
        c.strokeStyle=markerColor;c.lineWidth=1.7;c.beginPath();c.moveTo(x-4,markerY+rise);c.lineTo(x-1,markerY+rise+3);c.lineTo(x+5,markerY+rise-4);c.stroke();
      } else {
        c.font='700 16px Georgia, serif';c.textAlign='center';c.textBaseline='middle';c.fillStyle=markerColor;c.fillText(status==='available'?'!':'·',x,markerY+rise+.5);
      }
    }
  }

  _traveller(classId) {
    const c=this.ctx,p=this.hero,walking=p.walking&&!this.reduceMotion,phase=this.walkPhase;
    this._glow(p.x,p.y-6,43,'rgba(225,169,80,.09)');this._ellipse(p.x,p.y+15,15,5,'rgba(2,12,12,.42)');
    c.save();c.translate(p.x,p.y);c.scale(1.22,1.22);
    const amount=walking?1:0;
    this._hero({classId},{amount,phase,facing:p.facing,stride:Math.cos(phase)*amount,leftLift:Math.max(0,Math.sin(phase))*amount,rightLift:Math.max(0,-Math.sin(phase))*amount,bounce:-Math.abs(Math.sin(phase))*amount*1.6});
    c.restore();
  }

  _foreground(w,h) {
    const c=this.ctx;
    for(let i=0;i<5;i++) {const side=i%2?1:-1,x=side<0?-14+(i*13)%31:w+8-(i*17)%27,y=h-47-(i%3)*97;this._pine(x,y,150+(i%3)*32,'#142823');}
    for(let i=0;i<15;i++) {const x=this._hash(i,3,61)*w,y=h-21+this._hash(i,7,4)*29;this._rock(x,y,6+this._hash(i,2,6)*7);}
    const vignette=c.createRadialGradient(w/2,h*.56,h*.19,w/2,h*.54,w*.71);vignette.addColorStop(0,'rgba(3,12,14,0)');vignette.addColorStop(1,'rgba(3,12,14,.49)');c.fillStyle=vignette;c.fillRect(-1,-1,w+2,h+2);
  }

  _nameplate(name,x,y,color,portal=false) {
    const c=this.ctx,scale=this.transform.scale,font=Math.max(portal?15:14,10.5/scale);
    c.font=`500 ${font}px Georgia, serif`;c.textAlign='center';c.textBaseline='middle';
    let text=String(name||'');const max=this.layoutKey==='portrait'?142:154;
    while(c.measureText(text).width>max&&text.length>2)text=text.slice(0,-2)+'…';
    const width=c.measureText(text).width+22;
    const grd=c.createLinearGradient(x-width/2,0,x+width/2,0);grd.addColorStop(0,'rgba(9,22,20,0)');grd.addColorStop(.2,'rgba(9,22,20,.84)');grd.addColorStop(.8,'rgba(9,22,20,.84)');grd.addColorStop(1,'rgba(9,22,20,0)');
    c.fillStyle=grd;c.fillRect(x-width/2,y-font*.7,width,font*1.5);
    c.fillStyle=color;c.fillText(text,x,y+.5);
    if(portal){c.strokeStyle='rgba(148,178,156,.36)';c.lineWidth=.7;c.beginPath();c.moveTo(x-width*.33,y+font*.72);c.lineTo(x+width*.33,y+font*.72);c.stroke();}
    return {x:x-width/2,y:y-font*.7,w:width,h:font*1.5};
  }

}

class GameRenderer extends AshenRenderer {}
