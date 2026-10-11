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
          c.globalAlpha = 0.5 + Math.sin(this.clock * 0.003 + f.x) * 0.25;
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
        c.strokeStyle = 'rgba(177,225,204,0.5)'; c.beginPath(); c.ellipse(0,3,7+Math.sin(this.clock*.004)*2,2,0,0,Math.PI*2); c.stroke();
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
    if (/potion|heal|flask/.test(type)) {
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
      c.strokeStyle='#df7752'; c.lineWidth=1; c.beginPath(); c.arc(4,1,11+Math.sin(this.clock*.01),0,Math.PI*2); c.stroke();
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
      const x=label.x*t, y=label.y*t-age*t*(this.reduceMotion ? .08 : .65);
      c.lineWidth=3; c.strokeStyle='rgba(4,9,10,0.92)'; c.strokeText(label.text,x,y);
      c.fillStyle=label.color; c.fillText(label.text,x,y);
    }
    c.globalAlpha=1;
  }
}
