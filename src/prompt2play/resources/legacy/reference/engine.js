/* Ashen Vault — deterministic, DOM-free, turn-based game rules.
 * tiles: 0 wall, 1 floor, 2 stairs. Coordinates and moves are cardinal.
 * Features trigger on stepping onto them; interact also reaches adjacent features.
 * Stairs only trigger via interact while standing on them. Beat floor-five boss,
 * then use its stairs to win. act/choose clear events; event IDs never repeat.
 * A level-up consumes the action but grants respite from that enemy response.
 */
const ASHEN_CLASSES = [
  { id: 'warden', name: 'Страж', desc: 'Крепкая броня, тяжёлый удар. Надёжный путь в глубину.', color: '#e0aa5d', hp: 36, mana: 9, atk: 6, armor: 2, crit: .08, dodge: .03 },
  { id: 'rogue', name: 'Тень', desc: 'Критические удары и уклонение. Уязвим, но смертоносен.', color: '#79cdbb', hp: 29, mana: 11, atk: 5, armor: 1, crit: .25, dodge: .16 },
  { id: 'mage', name: 'Искровед', desc: 'Сильные заклинания и большой запас маны.', color: '#a99be7', hp: 26, mana: 18, atk: 4, armor: 0, crit: .10, dodge: .06 }
];
const ASHEN_SKILLS = [
  { id: 'bolt', name: 'Искра', desc: 'Магический удар по видимому врагу. Броня не защищает.', cost: 3, range: 9 },
  { id: 'nova', name: 'Кольцо пепла', desc: 'Удар по видимым врагам в радиусе 2,5 клеток.', cost: 5, range: 2.5 }
];
const ASHEN_PERKS = [
  { id: 'vitality', name: 'Несгибаемость', desc: '+9 к максимальному здоровью; восстановить 9 HP.' },
  { id: 'strength', name: 'Тяжёлая рука', desc: '+2 к силе всех обычных атак.' },
  { id: 'armor', name: 'Пепельная кожа', desc: '+1 к броне. Каждый удар врага слабее.' },
  { id: 'focus', name: 'Внутренний огонь', desc: '+5 к максимальной мане; восстановить всю ману.' },
  { id: 'sorcery', name: 'Жар углей', desc: '+3 к урону обоих заклинаний.' },
  { id: 'precision', name: 'Верный удар', desc: '+12% к шансу критического удара.' },
  { id: 'evasion', name: 'Лёгкий шаг', desc: '+8% к шансу уклониться от атаки.' },
  { id: 'vampire', name: 'Тлеющее сердце', desc: 'Каждый убитый враг восстанавливает 2 HP.' }
];

class AshenEngine {
  constructor({ seed = String(Date.now()), classId = 'warden' } = {}) {
    const hero = ASHEN_CLASSES.find(c => c.id === classId) || ASHEN_CLASSES[0];
    const seedText = String(seed).slice(0, 200);
    let h = 2166136261;
    for (let i = 0; i < seedText.length; i++) h = Math.imul(h ^ seedText.charCodeAt(i), 16777619);
    this._rng = h >>> 0;
    this._uid = 0;
    this.state = {
      version: 1, seed: seedText, floor: 1, maxFloors: 5, turn: 0, status: 'playing',
      w: 41, h: 29, tiles: [], rooms: [], seen: [], visible: [],
      player: { classId: hero.id, name: hero.name, x: 0, y: 0, hp: hero.hp, maxHp: hero.hp,
        mana: hero.mana, maxMana: hero.mana, atk: hero.atk, armor: hero.armor,
        crit: hero.crit, dodge: hero.dodge, level: 1, xp: 0, xpNext: 18,
        potions: 3, gold: 0, weaponName: hero.id === 'mage' ? 'Угольный посох' : hero.id === 'rogue' ? 'Парные ножи' : 'Старый клинок',
        armorName: hero.id === 'warden' ? 'Кольчуга дозорного' : 'Потрёпанный плащ',
        weaponPower: 0, armorPower: 0, spellPower: hero.id === 'mage' ? 4 : 0, lifesteal: 0, relics: [] },
      enemies: [], features: [], items: [], stairs: { x: 0, y: 0 }, choices: [], log: [], events: [],
      bossDefeated: false, stats: { kills: 0, gold: 0, damageDealt: 0, damageTaken: 0, spells: 0, potionsUsed: 0, floors: 1, chests: 0 }
    };
    this._generateFloor();
    this._log('Пять этажей под пеплом. Найди Владыку углей и выберись живым.', 'info');
    this._log('Двигайся в сторону врага, чтобы атаковать. E — лестница и взаимодействие.', 'info');
  }

  _random() {
    this._rng = (this._rng + 0x6D2B79F5) >>> 0;
    let t = this._rng;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  _int(a, b) { return a + Math.floor(this._random() * (b - a + 1)); }
  _pick(list) { return list[this._int(0, list.length - 1)]; }
  _id(prefix) { return prefix + (++this._uid); }
  _inside(x, y) { return Number.isInteger(x) && Number.isInteger(y) && x >= 0 && y >= 0 && x < this.state.w && y < this.state.h; }
  _walkable(x, y) { return this._inside(x, y) && this.state.tiles[y][x] !== 0; }
  _distance(a, b) { return Math.abs(a.x - b.x) + Math.abs(a.y - b.y); }
  _log(text, kind = 'info') {
    this.state.log.push({ text, kind, turn: this.state.turn });
    if (this.state.log.length > 100) this.state.log.shift();
  }
  _event(type, x, y, more = {}) { this.state.events.push({ id: this._id('ev'), type, x, y, ...more }); }
  _grid(value) { return Array.from({ length: this.state.h }, () => Array(this.state.w).fill(value)); }

  _generateFloor() {
    const s = this.state, p = s.player;
    s.tiles = this._grid(0); s.seen = this._grid(false); s.visible = this._grid(false);
    s.rooms = []; s.enemies = []; s.features = []; s.items = []; s.choices = [];
    const carve = (x, y) => { if (x > 0 && y > 0 && x < s.w - 1 && y < s.h - 1) s.tiles[y][x] = 1; };
    for (let attempt = 0; attempt < 220 && s.rooms.length < 10; attempt++) {
      const w = this._int(5, 9), h = this._int(4, 7);
      const x = this._int(2, s.w - w - 2), y = this._int(2, s.h - h - 2);
      if (s.rooms.some(r => x <= r.x + r.w && x + w >= r.x && y <= r.y + r.h && y + h >= r.y)) continue;
      const room = { x, y, w, h, cx: x + Math.floor(w / 2), cy: y + Math.floor(h / 2) };
      for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) carve(xx, yy);
      if (s.rooms.length) {
        const prev = s.rooms[s.rooms.length - 1];
        let xx = prev.cx, yy = prev.cy;
        if (this._random() < .5) {
          while (xx !== room.cx) { carve(xx, yy); xx += Math.sign(room.cx - xx); }
          while (yy !== room.cy) { carve(xx, yy); yy += Math.sign(room.cy - yy); }
        } else {
          while (yy !== room.cy) { carve(xx, yy); yy += Math.sign(room.cy - yy); }
          while (xx !== room.cx) { carve(xx, yy); xx += Math.sign(room.cx - xx); }
        }
        carve(xx, yy);
      }
      s.rooms.push(room);
    }
    const first = s.rooms[0];
    p.x = first.cx; p.y = first.cy;
    const distances = this._distances(p.x, p.y);
    let finalRoom = first, farthest = -1;
    for (const room of s.rooms) {
      const d = distances[room.cy][room.cx];
      if (d > farthest) { farthest = d; finalRoom = room; }
    }
    s.stairs = { x: finalRoom.cx, y: finalRoom.cy };
    s.tiles[s.stairs.y][s.stairs.x] = 2;
    const cells = [];
    for (let y = 1; y < s.h - 1; y++) for (let x = 1; x < s.w - 1; x++) {
      if (s.tiles[y][x] === 1 && !(x === p.x && y === p.y)) cells.push({ x, y });
    }
    const used = new Set([p.x + ',' + p.y, s.stairs.x + ',' + s.stairs.y]);
    const spot = (minDistance = 0, room = null) => {
      let candidates = cells.filter(c => !used.has(c.x + ',' + c.y) && distances[c.y][c.x] >= minDistance && (!room || (c.x >= room.x && c.x < room.x + room.w && c.y >= room.y && c.y < room.y + room.h)));
      if (!candidates.length) candidates = cells.filter(c => !used.has(c.x + ',' + c.y));
      const c = this._pick(candidates);
      if (!c) return null;
      used.add(c.x + ',' + c.y); return { ...c };
    };
    if (s.floor === 5) {
      const pos = spot(0, finalRoom);
      if (pos) s.enemies.push(this._makeEnemy('boss', pos.x, pos.y));
    }
    const count = 6 + s.floor * 2;
    for (let i = 0; i < count; i++) {
      const pos = spot(8);
      if (!pos) break;
      const pool = s.floor === 1 ? ['rat', 'rat', 'skeleton', 'skeleton', 'archer'] : ['rat', 'skeleton', 'skeleton', 'archer', 'sentinel', 'bomber'];
      s.enemies.push(this._makeEnemy(this._pick(pool), pos.x, pos.y));
    }
    for (const type of ['chest', 'chest', 'chest', 'shrine', 'fountain']) {
      const pos = spot(4);
      if (pos) s.features.push({ id: this._id('f'), type, ...pos, used: false });
    }
    for (const type of ['potion', 'potion', 'mana', 'weapon', 'armor', 'gold', 'gold']) {
      const pos = spot(3);
      if (pos) s.items.push(this._makeItem(type, pos.x, pos.y));
    }
    this._updateFov();
    this._event('floor', p.x, p.y, { text: s.floor === 5 ? 'Престол углей' : 'Этаж ' + s.floor });
  }

  _makeEnemy(type, x, y) {
    const f = this.state.floor - 1;
    const defs = {
      rat: { name: 'Пепельная крыса', hp: 8, atk: 3, armor: 0, xp: 5, color: '#b3a281' },
      skeleton: { name: 'Костяной страж', hp: 13, atk: 4, armor: 0, xp: 8, color: '#d5c9b3' },
      archer: { name: 'Тлеющий лучник', hp: 11, atk: 4, armor: 0, xp: 9, color: '#cc9b72' },
      sentinel: { name: 'Железный дозор', hp: 23, atk: 5, armor: 2, xp: 13, color: '#98a6ac' },
      bomber: { name: 'Пороховой дух', hp: 10, atk: 8, armor: 0, xp: 10, color: '#f6a34c' },
      boss: { name: 'Владыка углей', hp: 100, atk: 8, armor: 2, xp: 50, color: '#f17862' }
    };
    const d = defs[type];
    const hp = d.hp + (type === 'boss' ? 0 : f * 3);
    return { id: this._id('e'), type, name: d.name, x, y, hp, maxHp: hp,
      atk: d.atk + (type === 'boss' ? 0 : Math.floor(f * .65)), armor: d.armor,
      xp: d.xp + f, color: d.color, alert: 0, armed: false, intent: null, charge: 0, actions: 0 };
  }
  _makeItem(type, x, y) {
    const f = this.state.floor;
    const item = { id: this._id('i'), type, x, y };
    if (type === 'gold') { item.amount = this._int(5, 10) + f * 3; item.name = 'Золото'; }
    if (type === 'potion') { item.amount = 1; item.name = 'Лечебное зелье'; }
    if (type === 'mana') { item.amount = 5; item.name = 'Осколок эфира'; }
    if (type === 'weapon') { item.power = f + this._int(0, 2); item.name = this._pick(['Угольный клинок', 'Серп дозорного', 'Шип пламени', 'Обсидиановый меч']) + ' +' + item.power; }
    if (type === 'armor') { item.power = Math.ceil(f / 2) + this._int(0, 1); item.name = this._pick(['Пепельный панцирь', 'Броня изгнанника', 'Кольчуга углей']) + ' +' + item.power; }
    return item;
  }

  _line(x0, y0, x1, y1) {
    // Bresenham's tie-break chooses different cells when traversed backward.
    // Use one canonical direction so FOV, targeting, and enemy sight agree.
    if (x0 > x1 || (x0 === x1 && y0 > y1)) {
      [x0, x1] = [x1, x0]; [y0, y1] = [y1, y0];
    }
    let dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, err = dx - dy;
    while (!(x0 === x1 && y0 === y1)) {
      const e = 2 * err, oldX = x0, oldY = y0;
      if (e > -dy) { err -= dy; x0 += sx; }
      if (e < dx) { err += dx; y0 += sy; }
      if (x0 !== oldX && y0 !== oldY && !this._walkable(x0, oldY) && !this._walkable(oldX, y0)) return false;
      if (x0 === x1 && y0 === y1) return true;
      if (!this._walkable(x0, y0)) return false;
    }
    return true;
  }
  _updateFov() {
    const s = this.state, p = s.player;
    s.visible = this._grid(false);
    for (let y = Math.max(0, p.y - 9); y <= Math.min(s.h - 1, p.y + 9); y++) {
      for (let x = Math.max(0, p.x - 9); x <= Math.min(s.w - 1, p.x + 9); x++) {
        if ((x - p.x) ** 2 + (y - p.y) ** 2 <= 81 && this._line(p.x, p.y, x, y)) s.visible[y][x] = s.seen[y][x] = true;
      }
    }
    s.visible[p.y][p.x] = s.seen[p.y][p.x] = true;
  }
  _distances(x, y) {
    const d = this._grid(-1), queue = [{ x, y }]; d[y][x] = 0;
    for (let i = 0; i < queue.length; i++) {
      const c = queue[i];
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = c.x + dx, ny = c.y + dy;
        if (this._walkable(nx, ny) && d[ny][nx] < 0) { d[ny][nx] = d[c.y][c.x] + 1; queue.push({ x: nx, y: ny }); }
      }
    }
    return d;
  }

  act(action) {
    const s = this.state, p = s.player;
    s.events = [];
    if (!action || typeof action !== 'object' || s.status !== 'playing') return false;
    let consumed = false, changedFloor = false;
    if (action.type === 'move') {
      const { dx, dy } = action;
      if (!Number.isInteger(dx) || !Number.isInteger(dy) || Math.abs(dx) + Math.abs(dy) !== 1) return false;
      const x = p.x + dx, y = p.y + dy;
      if (!this._walkable(x, y)) return false;
      const enemy = s.enemies.find(e => e.x === x && e.y === y);
      if (enemy) this._melee(enemy);
      else {
        const fromX = p.x, fromY = p.y; p.x = x; p.y = y;
        this._event('step', x, y, { tx: fromX, ty: fromY });
        this._pickup();
        const feature = s.features.find(f => f.x === x && f.y === y && !f.used);
        if (feature) this._useFeature(feature);
        if (s.tiles[y][x] === 2) this._log(s.floor < 5 ? 'Лестница вниз. Нажми E, когда будешь готов.' : s.bossDefeated ? 'Путь наружу открыт. Нажми E.' : 'Выход запечатан. Владыка углей ещё жив.', 'info');
      }
      consumed = true;
    } else if (action.type === 'wait') {
      p.mana = Math.min(p.maxMana, p.mana + 1);
      if (!s.enemies.some(e => this._distance(e, p) <= 6) && s.turn % 2 === 0) p.hp = Math.min(p.maxHp, p.hp + 1);
      consumed = true;
    } else if (action.type === 'potion') {
      if (p.potions < 1 || p.hp >= p.maxHp) { this._log(p.potions < 1 ? 'Нет лечебных зелий.' : 'Здоровье уже восстановлено.', 'info'); return false; }
      p.potions--; s.stats.potionsUsed++;
      this._heal(Math.ceil(p.maxHp * .55) + 4);
      this._log('Лечебное зелье согревает кровь.', 'good'); consumed = true;
    } else if (action.type === 'cast') {
      const skill = ASHEN_SKILLS.find(a => a.id === action.skill);
      if (!skill) return false;
      if (p.mana < skill.cost) { this._log('Не хватает маны. Ожидание восстанавливает силы.', 'info'); return false; }
      if (skill.id === 'bolt') {
        const { x, y } = action;
        if (!this._inside(x, y) || !s.visible[y][x] || (x - p.x) ** 2 + (y - p.y) ** 2 > skill.range ** 2 || !this._line(p.x, p.y, x, y)) return false;
        const enemy = s.enemies.find(e => e.x === x && e.y === y);
        if (!enemy) { this._log('Искре нужна видимая цель.', 'info'); return false; }
        p.mana -= skill.cost;
        this._event('cast', p.x, p.y, { tx: x, ty: y, text: 'bolt', color: '#b8a5ff' });
        this._hurtEnemy(enemy, 9 + p.spellPower + Math.floor(p.level / 2), true);
      } else {
        const targets = s.enemies.filter(e => (e.x - p.x) ** 2 + (e.y - p.y) ** 2 <= 6.25 && this._line(p.x, p.y, e.x, e.y));
        if (!targets.length) { this._log('Рядом нет врагов для кольца пепла.', 'info'); return false; }
        p.mana -= skill.cost;
        this._event('cast', p.x, p.y, { text: 'nova', color: '#d7b4ff' });
        for (const enemy of targets) this._hurtEnemy(enemy, 8 + p.spellPower + Math.floor(p.level / 2), true);
      }
      s.stats.spells++; consumed = true;
    } else if (action.type === 'interact') {
      if (p.x === s.stairs.x && p.y === s.stairs.y) {
        if (s.floor === 5) {
          if (!s.bossDefeated) { this._log('Печать держится силой Владыки углей.', 'danger'); return false; }
          s.status = 'won';
          this._log('Пепельный свод остался позади. Ты вынес свет на поверхность.', 'good');
          this._event('floor', p.x, p.y, { text: 'Свобода', color: '#efd297' }); consumed = true;
        } else {
          s.floor++; s.stats.floors = s.floor;
          p.hp = Math.min(p.maxHp, p.hp + Math.ceil(p.maxHp * .3)); p.mana = p.maxMana;
          this._generateFloor();
          this._log('Этаж ' + s.floor + '. На лестнице ты перевёл дыхание и восстановил ману.', 'good');
          consumed = true; changedFloor = true;
        }
      } else {
        const candidates = s.features.filter(f => !f.used && this._distance(f, p) <= 1).sort((a, b) => this._distance(a, p) - this._distance(b, p));
        const feature = candidates.find(f => f.type !== 'fountain' || p.hp < p.maxHp || p.mana < p.maxMana);
        if (!feature || !this._useFeature(feature)) return false;
        consumed = true;
      }
    }
    if (!consumed) return false;
    s.turn++;
    if (s.turn % 5 === 0) p.mana = Math.min(p.maxMana, p.mana + 1);
    this._updateFov();
    if (s.status === 'playing' && !changedFloor && !this._levelUp()) this._enemyTurn();
    this._updateFov();
    return true;
  }

  _melee(enemy) {
    const p = this.state.player, critical = this._random() < p.crit;
    let damage = p.atk + this._int(-1, 1);
    if (critical) damage = Math.ceil(damage * 1.7);
    this._hurtEnemy(enemy, damage, false, critical);
  }
  _hurtEnemy(enemy, amount, magic = false, critical = false) {
    if (!this.state.enemies.includes(enemy)) return;
    const s = this.state, damage = Math.max(1, amount - (magic ? 0 : enemy.armor));
    enemy.hp -= damage; enemy.alert = 9; s.stats.damageDealt += damage;
    this._event('hit', enemy.x, enemy.y, { amount: damage, text: critical ? 'КРИТ' : '', color: critical ? '#ffdc85' : magic ? '#bba2ff' : '#fff0d0' });
    this._log((critical ? 'Критический удар! ' : '') + enemy.name + ': −' + damage + ' HP.', magic ? 'magic' : 'combat');
    if (enemy.hp <= 0) this._killEnemy(enemy);
  }
  _killEnemy(enemy) {
    const s = this.state, p = s.player;
    s.enemies = s.enemies.filter(e => e.id !== enemy.id);
    s.stats.kills++; p.xp += enemy.xp;
    this._event('death', enemy.x, enemy.y, { text: enemy.type, color: enemy.color });
    this._log(enemy.name + ' повержен. +' + enemy.xp + ' опыта.', 'good');
    if (p.lifesteal) this._heal(p.lifesteal);
    if (enemy.type === 'boss') {
      s.bossDefeated = true; p.relics.push('Сердце углей');
      p.gold += 100; s.stats.gold += 100;
      this._log('Владыка пал. Печать разрушена — найди лестницу и нажми E!', 'good');
      this._heal(Math.ceil(p.maxHp * .3));
    } else {
      if (this._random() < .7) s.items.push(this._makeItem('gold', enemy.x, enemy.y));
      if (this._random() < .14) s.items.push(this._makeItem('potion', enemy.x, enemy.y));
    }
  }
  _hurtPlayer(amount, source, magic = false) {
    const s = this.state, p = s.player;
    if (s.status !== 'playing') return;
    if (!magic && this._random() < p.dodge) {
      this._event('hit', p.x, p.y, { amount: 0, text: 'МИМО', color: '#8ed8c0' });
      this._log('Ты уклонился: ' + source + '.', 'good'); return;
    }
    const damage = Math.max(1, amount - (magic ? Math.floor(p.armor / 2) : p.armor));
    p.hp = Math.max(0, p.hp - damage); s.stats.damageTaken += damage;
    this._event('hit', p.x, p.y, { amount: damage, color: '#ff746e' });
    this._log(source + ': −' + damage + ' HP.', 'danger');
    if (p.hp === 0) {
      s.status = 'dead'; s.choices = [];
      this._event('death', p.x, p.y, { text: 'player', color: '#ff746e' });
      this._log('Твой огонь погас. В следующий раз пепел ляжет иначе.', 'danger');
    }
  }
  _heal(amount) {
    const p = this.state.player, healed = Math.min(amount, p.maxHp - p.hp);
    if (healed > 0) { p.hp += healed; this._event('heal', p.x, p.y, { amount: healed, color: '#8ed8a7' }); }
  }
  _pickup() {
    const s = this.state, p = s.player, items = s.items.filter(i => i.x === p.x && i.y === p.y);
    s.items = s.items.filter(i => i.x !== p.x || i.y !== p.y);
    for (const item of items) this._giveItem(item);
  }
  _giveItem(item) {
    const s = this.state, p = s.player;
    if (item.type === 'gold') { p.gold += item.amount; s.stats.gold += item.amount; this._log('Найдено золото: +' + item.amount + '.', 'good'); }
    if (item.type === 'potion') { p.potions += item.amount || 1; this._log('Найдено лечебное зелье.', 'good'); }
    if (item.type === 'mana') { p.mana = Math.min(p.maxMana, p.mana + item.amount); this._log('Эфир восстановил ' + item.amount + ' маны.', 'magic'); }
    if (item.type === 'weapon' || item.type === 'armor') {
      const weapon = item.type === 'weapon', key = weapon ? 'weaponPower' : 'armorPower', stat = weapon ? 'atk' : 'armor';
      if (item.power > p[key]) {
        p[stat] += item.power - p[key]; p[key] = item.power; p[weapon ? 'weaponName' : 'armorName'] = item.name;
        this._log('Надето: ' + item.name + '.', 'good');
      } else { p.gold += 12; s.stats.gold += 12; this._log(item.name + ' обращён в 12 золотых.', 'good'); }
    }
    this._event('loot', p.x, p.y, { text: item.name || item.type, color: '#ecc97c' });
  }
  _useFeature(feature) {
    const s = this.state, p = s.player;
    if (feature.used) return false;
    if (feature.type === 'fountain') {
      if (p.hp === p.maxHp && p.mana === p.maxMana) return false;
      this._heal(Math.ceil(p.maxHp * .7)); p.mana = p.maxMana;
      this._log('Последняя вода фонтана вернула тебе силы.', 'good');
    } else if (feature.type === 'chest') {
      s.stats.chests++;
      this._giveItem(this._makeItem('gold', p.x, p.y));
      this._giveItem(this._makeItem(this._pick(['weapon', 'armor', 'potion', 'potion']), p.x, p.y));
      this._log('Древний сундук открыт.', 'good');
    } else if (feature.type === 'shrine') {
      p.maxHp += 3; this._heal(7); p.mana = Math.min(p.maxMana, p.mana + 4);
      this._log('Святилище укрепило твой дух: +3 к максимальному здоровью.', 'good');
    } else return false;
    feature.used = true;
    this._event('loot', feature.x, feature.y, { text: feature.type, color: '#e6c78c' });
    return true;
  }

  _levelUp() {
    const s = this.state, p = s.player;
    if (p.xp < p.xpNext || s.status !== 'playing') return false;
    p.xp -= p.xpNext; p.level++; p.xpNext = 18 + (p.level - 1) * 11;
    p.maxHp += 3; p.atk += 1; this._heal(Math.ceil(p.maxHp * .25)); p.mana = Math.min(p.maxMana, p.mana + 4);
    const pool = ASHEN_PERKS.filter(k => !(k.id === 'precision' && p.crit >= .65) && !(k.id === 'evasion' && p.dodge >= .45));
    s.choices = [];
    while (s.choices.length < 3 && pool.length) s.choices.push({ ...pool.splice(this._int(0, pool.length - 1), 1)[0] });
    s.status = 'choice';
    this._event('level', p.x, p.y, { amount: p.level, text: 'УРОВЕНЬ ' + p.level, color: '#ffe2a0' });
    this._log('Уровень ' + p.level + '! Выбери дар. Враги замерли на миг.', 'good');
    return true;
  }
  choose(id) {
    const s = this.state, p = s.player; s.events = [];
    if (s.status !== 'choice') return false;
    const perk = s.choices.find(k => k.id === id);
    if (!perk) return false;
    if (id === 'vitality') { p.maxHp += 9; this._heal(9); }
    if (id === 'strength') p.atk += 2;
    if (id === 'armor') p.armor++;
    if (id === 'focus') { p.maxMana += 5; p.mana = p.maxMana; }
    if (id === 'sorcery') p.spellPower += 3;
    if (id === 'precision') p.crit = Math.min(.75, p.crit + .12);
    if (id === 'evasion') p.dodge = Math.min(.5, p.dodge + .08);
    if (id === 'vampire') p.lifesteal += 2;
    p.relics.push(perk.name);
    s.choices = []; s.status = 'playing';
    this._log('Получен дар: ' + perk.name + '.', 'good');
    this._event('level', p.x, p.y, { text: perk.name, color: '#ffe2a0' });
    this._levelUp();
    return true;
  }

  _enemyTurn() {
    const s = this.state, p = s.player, distances = this._distances(p.x, p.y);
    for (const enemy of [...s.enemies]) {
      if (s.status !== 'playing') break;
      if (!s.enemies.includes(enemy)) continue;
      const dx = p.x - enemy.x, dy = p.y - enemy.y, distance = Math.abs(dx) + Math.abs(dy);
      const sight = distance <= 10 && this._line(enemy.x, enemy.y, p.x, p.y);
      if (sight) enemy.alert = 8;
      else enemy.alert = Math.max(0, enemy.alert - 1);
      if (!enemy.alert && !enemy.armed && !enemy.intent) continue;
      enemy.actions++;
      if (enemy.type === 'bomber') {
        if (enemy.armed) {
          this._event('cast', enemy.x, enemy.y, { text: 'blast', color: '#ffaf62' });
          if (Math.abs(dx) <= 1 && Math.abs(dy) <= 1 && this._line(enemy.x, enemy.y, p.x, p.y)) this._hurtPlayer(enemy.atk, 'Взрыв порохового духа', true);
          s.enemies = s.enemies.filter(e => e.id !== enemy.id);
          this._event('death', enemy.x, enemy.y, { text: 'bomber', color: '#ffaf62' });
          continue;
        }
        if (distance <= 2 && sight) {
          enemy.armed = true; enemy.intent = 'blast';
          this._log('Пороховой дух вспыхнул! Отойди от него хотя бы на две клетки.', 'danger');
          this._event('cast', enemy.x, enemy.y, { text: 'warning', color: '#ffaf62' }); continue;
        }
      }
      if (enemy.type === 'boss') {
        if (enemy.intent === 'nova') {
          if (enemy.charge > 1) { enemy.charge--; continue; }
          this._event('cast', enemy.x, enemy.y, { text: 'nova', color: '#ff775c' });
          if (dx * dx + dy * dy <= 6.25 && sight) this._hurtPlayer(enemy.atk + 3, 'Кольцо Владыки углей', true);
          enemy.intent = null; enemy.charge = 0; continue;
        }
        if (enemy.actions % 4 === 0 && distance <= 5 && sight) {
          enemy.intent = 'nova'; enemy.charge = 2;
          this._log('Владыка собирает огонь! У тебя два хода, чтобы отойти за пределы двух клеток.', 'danger');
          this._event('cast', enemy.x, enemy.y, { text: 'warning', color: '#ff775c' }); continue;
        }
      }
      if (distance === 1) { this._hurtPlayer(enemy.atk + this._int(-1, 1), enemy.name); continue; }
      if (enemy.type === 'archer' && distance <= 6 && sight) {
        if (enemy.actions % 2 === 0) {
          enemy.intent = null;
          this._event('cast', enemy.x, enemy.y, { tx: p.x, ty: p.y, text: 'arrow', color: '#d9b98d' });
          this._hurtPlayer(enemy.atk, enemy.name);
        } else {
          enemy.intent = 'aim';
          if (s.visible[enemy.y][enemy.x]) this._event('cast', enemy.x, enemy.y, { tx: p.x, ty: p.y, text: 'aim', color: '#d9b98d' });
        }
        continue;
      }
      if (enemy.type === 'sentinel' && enemy.actions % 3 === 0) continue;
      enemy.intent = null;
      const candidates = [[1, 0], [-1, 0], [0, 1], [0, -1]].map(([mx, my]) => ({ x: enemy.x + mx, y: enemy.y + my }));
      const legal = candidates.filter(c => this._walkable(c.x, c.y) && !(c.x === p.x && c.y === p.y) && !s.enemies.some(e => e !== enemy && e.x === c.x && e.y === c.y) && distances[c.y][c.x] >= 0);
      legal.sort((a, b) => distances[a.y][a.x] - distances[b.y][b.x]);
      if (legal.length && distances[legal[0].y][legal[0].x] < distances[enemy.y][enemy.x]) { enemy.x = legal[0].x; enemy.y = legal[0].y; }
    }
  }

  serialize() {
    return JSON.stringify({ format: 'ashen-vault', version: 1, rng: this._rng, uid: this._uid, state: this.state });
  }
  static fromSave(text) {
    const bad = () => { throw new Error('Сохранение повреждено или относится к другой версии.'); };
    if (typeof text !== 'string' || text.length > 3000000) return bad();
    let save;
    try { save = JSON.parse(text); } catch (_) { return bad(); }
    const s = save && save.state;
    if (!s || save.format !== 'ashen-vault' || save.version !== 1 || s.version !== 1 || s.w !== 41 || s.h !== 29 || !Number.isInteger(save.rng) || save.rng < 0 || save.rng > 4294967295 || !Number.isInteger(save.uid) || save.uid < 0) return bad();
    if (!Number.isInteger(s.floor) || s.floor < 1 || s.floor > 5 || s.maxFloors !== 5 || !Number.isInteger(s.turn) || s.turn < 0 || !['playing', 'choice', 'dead', 'won'].includes(s.status) || typeof s.seed !== 'string') return bad();
    if (!Array.isArray(s.tiles) || s.tiles.length !== 29 || s.tiles.some(row => !Array.isArray(row) || row.length !== 41 || row.some(t => ![0, 1, 2].includes(t)))) return bad();
    if (!Array.isArray(s.seen) || s.seen.length !== 29 || s.seen.some(row => !Array.isArray(row) || row.length !== 41 || row.some(v => typeof v !== 'boolean'))) return bad();
    const location = o => o && Number.isInteger(o.x) && Number.isInteger(o.y) && o.x >= 0 && o.x < 41 && o.y >= 0 && o.y < 29 && s.tiles[o.y][o.x] !== 0;
    const p = s.player;
    if (!location(p) || !ASHEN_CLASSES.some(c => c.id === p.classId) || !location(s.stairs) || s.tiles[s.stairs.y][s.stairs.x] !== 2) return bad();
    for (const key of ['hp', 'maxHp', 'mana', 'maxMana', 'atk', 'armor', 'crit', 'dodge', 'level', 'xp', 'xpNext', 'potions', 'gold', 'weaponPower', 'armorPower', 'spellPower', 'lifesteal']) {
      if (!Number.isFinite(p[key]) || p[key] < 0 || p[key] > 1000000) return bad();
    }
    if (p.hp > p.maxHp || p.mana > p.maxMana || p.maxHp < 1 || p.level < 1 || p.xpNext < 1 || p.crit > 1 || p.dodge > 1 || !Array.isArray(p.relics) || p.relics.some(r => typeof r !== 'string')) return bad();
    if ((s.status === 'dead') !== (p.hp === 0)) return bad();
    if (!Array.isArray(s.enemies) || s.enemies.length > 100 || s.enemies.some(e => !location(e) || !['rat', 'skeleton', 'archer', 'sentinel', 'bomber', 'boss'].includes(e.type) || !Number.isFinite(e.hp) || e.hp <= 0 || !Number.isFinite(e.maxHp) || e.hp > e.maxHp || !Number.isFinite(e.atk) || e.atk < 0 || !Number.isFinite(e.armor) || e.armor < 0 || !Number.isFinite(e.xp) || e.xp < 0 || !Number.isInteger(e.actions) || e.actions < 0 || !Number.isFinite(e.alert) || e.alert < 0 || !Number.isInteger(e.charge) || e.charge < 0 || typeof e.armed !== 'boolean' || ![null, 'aim', 'blast', 'nova'].includes(e.intent))) return bad();
    const occupied = new Set();
    for (const e of s.enemies) { const key = e.x + ',' + e.y; if (occupied.has(key) || (e.x === p.x && e.y === p.y)) return bad(); occupied.add(key); }
    if (!Array.isArray(s.features) || s.features.length > 100 || s.features.some(f => !location(f) || !['chest', 'shrine', 'fountain'].includes(f.type) || typeof f.used !== 'boolean')) return bad();
    if (!Array.isArray(s.items) || s.items.length > 1000 || s.items.some(i => !location(i) || !['potion', 'gold', 'mana', 'weapon', 'armor'].includes(i.type) || !Number.isFinite(i.type === 'weapon' || i.type === 'armor' ? i.power : i.amount) || (i.type === 'weapon' || i.type === 'armor' ? i.power : i.amount) < 0)) return bad();
    if (!Array.isArray(s.rooms) || !Array.isArray(s.choices) || s.choices.some(c => !ASHEN_PERKS.some(k => k.id === c.id)) || (s.status === 'choice' && s.choices.length !== 3) || (s.status !== 'choice' && s.choices.length)) return bad();
    if (!Array.isArray(s.log) || s.log.length > 100 || s.log.some(l => typeof l.text !== 'string' || typeof l.kind !== 'string') || !s.stats || typeof s.bossDefeated !== 'boolean') return bad();
    if (s.status === 'won' && (s.floor !== 5 || !s.bossDefeated)) return bad();
    const ids = new Set();
    for (const object of [...s.enemies, ...s.features, ...s.items]) {
      if (typeof object.id !== 'string' || !/^[efi]\d+$/.test(object.id) || Number(object.id.slice(1)) > save.uid || ids.has(object.id)) return bad();
      ids.add(object.id);
    }
    for (const key of ['kills', 'gold', 'damageDealt', 'damageTaken', 'spells', 'potionsUsed', 'floors', 'chests']) if (!Number.isFinite(s.stats[key]) || s.stats[key] < 0) return bad();
    const engine = Object.create(AshenEngine.prototype);
    engine.state = s; engine._rng = save.rng >>> 0; engine._uid = save.uid;
    s.events = [];
    engine._updateFov();
    return engine;
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { AshenEngine, ASHEN_CLASSES, ASHEN_SKILLS };
