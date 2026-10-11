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
