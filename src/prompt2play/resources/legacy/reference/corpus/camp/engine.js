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
  constructor({ seed = String(Date.now()), classId = 'warden', bonuses = {} } = {}) {
    const hero = ASHEN_CLASSES.find(c => c.id === classId) || ASHEN_CLASSES[0];
    const seedText = String(seed).slice(0, 200);
    let h = 2166136261;
    for (let i = 0; i < seedText.length; i++) h = Math.imul(h ^ seedText.charCodeAt(i), 16777619);
    this._rng = h >>> 0;
    this._uid = 0;
    this.state = {
      version: 1, campExtension: 1, seed: seedText, floor: 1, maxFloors: 5, turn: 0, status: 'playing',
      w: 41, h: 29, tiles: [], rooms: [], seen: [], visible: [],
      player: { classId: hero.id, name: hero.name, x: 0, y: 0, hp: hero.hp, maxHp: hero.hp,
        mana: hero.mana, maxMana: hero.mana, atk: hero.atk, armor: hero.armor,
        crit: hero.crit, dodge: hero.dodge, level: 1, xp: 0, xpNext: 18,
        potions: 3, gold: 0, materials: { wood: 0, ore: 0, herb: 0, crystal: 0 }, weaponName: hero.id === 'mage' ? 'Угольный посох' : hero.id === 'rogue' ? 'Парные ножи' : 'Старый клинок',
        armorName: hero.id === 'warden' ? 'Кольчуга дозорного' : 'Потрёпанный плащ',
        weaponPower: 0, armorPower: 0, spellPower: hero.id === 'mage' ? 4 : 0, lifesteal: 0, relics: [] },
      enemies: [], features: [], items: [], stairs: { x: 0, y: 0 }, choices: [], log: [], events: [],
      bossDefeated: false, stats: { kills: 0, gold: 0, damageDealt: 0, damageTaken: 0, spells: 0, potionsUsed: 0, floors: 1, chests: 0, shrines: 0,
        killsByType: { rat: 0, skeleton: 0, archer: 0, sentinel: 0, bomber: 0, boss: 0 }, legacyKills: 0 }
    };
    // The campaign supplies these once, when a fresh run is created. fromSave
    // restores exact stats and deliberately never calls this constructor.
    const p = this.state.player;
    for (const key of ['hp', 'mana', 'atk', 'armor', 'potions', 'spellPower']) {
      const value = bonuses && bonuses[key] !== undefined ? bonuses[key] : 0;
      if (!Number.isSafeInteger(value) || value < 0 || value > 1000) throw new Error('Некорректный бонус лагеря.');
      p[key] += value;
      if (key === 'hp') p.maxHp += value;
      if (key === 'mana') p.maxMana += value;
    }
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
    s.entry = { x: p.x, y: p.y };
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
    // A small guaranteed supply near the arrival room makes the first camp
    // upgrades attainable; further stacks reward exploration. Crystals remain
    // rare on floor one and guaranteed from floor two onward.
    for (const type of ['wood', 'ore', 'herb']) {
      const near = spot(2, first), far = spot(5);
      if (near) s.items.push({ ...this._makeItem(type, near.x, near.y), amount: 2 });
      if (far) s.items.push({ ...this._makeItem(type, far.x, far.y), amount: type === 'wood' ? 3 : 2 });
    }
    if (s.floor >= 2 || this._random() < .18) {
      const pos = spot(8);
      if (pos) s.items.push({ ...this._makeItem('crystal', pos.x, pos.y), amount: s.floor >= 4 ? 2 : 1 });
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
    const materials = { wood: 'Сухое дерево', ore: 'Железная руда', herb: 'Лунная трава', crystal: 'Пепельный кристалл' };
    if (Object.hasOwn(materials, type)) { item.amount = type === 'crystal' ? 1 : 2; item.name = materials[type]; }
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
    if (!s.enemies.includes(enemy)) return;
    s.enemies = s.enemies.filter(e => e.id !== enemy.id);
    s.stats.kills++; p.xp += enemy.xp;
    s.stats.killsByType[enemy.type]++;
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
      if (this._random() < .16) s.items.push(this._makeItem(enemy.type === 'sentinel' ? 'ore' : this._pick(['wood', 'herb']), enemy.x, enemy.y));
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
    if (Object.hasOwn(p.materials, item.type)) {
      p.materials[item.type] += item.amount;
      this._log(item.name + ': +' + item.amount + ' в рюкзак. Доставь в лагерь.', 'good');
    }
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
      this._giveItem(this._makeItem(this._pick(s.floor >= 2 ? ['wood', 'ore', 'herb', 'crystal'] : ['wood', 'ore', 'herb']), p.x, p.y));
      this._log('Древний сундук открыт.', 'good');
    } else if (feature.type === 'shrine') {
      s.stats.shrines++;
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
    const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    const integer = (value, max = 1000000000) => Number.isSafeInteger(value) && value >= 0 && value <= max;
    const label = (value, max = 250) => typeof value === 'string' && value.length <= max;
    const s = save && save.state;
    if (!record(s) || save.format !== 'ashen-vault' || save.version !== 1 || s.version !== 1 || s.w !== 41 || s.h !== 29 || !integer(save.rng, 4294967295) || !integer(save.uid)) return bad();
    if (s.campExtension !== undefined && s.campExtension !== 1) return bad();
    const extended = s.campExtension === 1;
    if (!integer(s.floor, 5) || s.floor < 1 || s.maxFloors !== 5 || !integer(s.turn) || !['playing', 'choice', 'dead', 'won'].includes(s.status) || !label(s.seed, 200)) return bad();
    if (!Array.isArray(s.tiles) || s.tiles.length !== 29 || s.tiles.some(row => !Array.isArray(row) || row.length !== 41 || row.some(t => ![0, 1, 2].includes(t)))) return bad();
    if (!Array.isArray(s.seen) || s.seen.length !== 29 || s.seen.some(row => !Array.isArray(row) || row.length !== 41 || row.some(v => typeof v !== 'boolean'))) return bad();
    const location = o => record(o) && Number.isInteger(o.x) && Number.isInteger(o.y) && o.x >= 0 && o.x < 41 && o.y >= 0 && o.y < 29 && s.tiles[o.y][o.x] !== 0;
    const p = s.player;
    if (!location(p) || !ASHEN_CLASSES.some(c => c.id === p.classId) || !location(s.stairs) || s.tiles[s.stairs.y][s.stairs.x] !== 2) return bad();
    for (const key of ['hp', 'maxHp', 'mana', 'maxMana', 'atk', 'armor', 'level', 'xp', 'xpNext', 'potions', 'gold', 'weaponPower', 'armorPower', 'spellPower', 'lifesteal']) {
      if (!integer(p[key], 1000000)) return bad();
    }
    if (!Number.isFinite(p.crit) || p.crit < 0 || p.crit > 1 || !Number.isFinite(p.dodge) || p.dodge < 0 || p.dodge > 1) return bad();
    if (p.hp > p.maxHp || p.mana > p.maxMana || p.maxHp < 1 || p.level < 1 || p.xpNext < 1 || !Array.isArray(p.relics) || p.relics.length > 5000 || p.relics.some(r => !label(r)) || !['name', 'weaponName', 'armorName'].every(key => label(p[key]))) return bad();
    if ((s.status === 'dead') !== (p.hp === 0)) return bad();
    const enemyTypes = ['rat', 'skeleton', 'archer', 'sentinel', 'bomber', 'boss'];
    if (!Array.isArray(s.enemies) || s.enemies.length > 100 || s.enemies.some(e => !location(e) || !enemyTypes.includes(e.type) || !integer(e.hp, 1000000) || e.hp === 0 || !integer(e.maxHp, 1000000) || e.hp > e.maxHp || !integer(e.atk, 1000000) || !integer(e.armor, 1000000) || !integer(e.xp, 1000000) || !integer(e.actions) || !integer(e.alert) || !integer(e.charge) || typeof e.armed !== 'boolean' || ![null, 'aim', 'blast', 'nova'].includes(e.intent) || !label(e.name) || !label(e.color, 40))) return bad();
    const occupied = new Set();
    for (const e of s.enemies) { const key = e.x + ',' + e.y; if (occupied.has(key) || (e.x === p.x && e.y === p.y)) return bad(); occupied.add(key); }
    if (!Array.isArray(s.features) || s.features.length > 100 || s.features.some(f => !location(f) || !['chest', 'shrine', 'fountain'].includes(f.type) || typeof f.used !== 'boolean')) return bad();
    const itemTypes = ['potion', 'gold', 'mana', 'weapon', 'armor', 'wood', 'ore', 'herb', 'crystal'];
    if (!Array.isArray(s.items) || s.items.length > 1000 || s.items.some(i => !location(i) || !itemTypes.includes(i.type) || !integer(i.type === 'weapon' || i.type === 'armor' ? i.power : i.amount, 1000000) || !label(i.name))) return bad();
    if (!Array.isArray(s.rooms) || !s.rooms.length || s.rooms.length > 20 || s.rooms.some(r => !record(r) || !['x', 'y', 'w', 'h', 'cx', 'cy'].every(k => integer(r[k], 41)) || r.w < 1 || r.h < 1 || r.x < 1 || r.y < 1 || r.x + r.w > 40 || r.y + r.h > 28 || r.cx < r.x || r.cx >= r.x + r.w || r.cy < r.y || r.cy >= r.y + r.h)) return bad();
    if (!Array.isArray(s.choices) || s.choices.some(c => !record(c) || !ASHEN_PERKS.some(k => k.id === c.id)) || new Set(s.choices.map(c => c.id)).size !== s.choices.length || (s.status === 'choice' && s.choices.length !== 3) || (s.status !== 'choice' && s.choices.length)) return bad();
    if (!Array.isArray(s.log) || s.log.length > 100 || s.log.some(l => !record(l) || !label(l.text, 2000) || !label(l.kind, 40) || !integer(l.turn)) || !record(s.stats) || typeof s.bossDefeated !== 'boolean') return bad();
    if (s.status === 'won' && (s.floor !== 5 || !s.bossDefeated)) return bad();
    const livingBosses = s.enemies.filter(enemy => enemy.type === 'boss').length;
    if (s.floor < 5 ? livingBosses !== 0 || s.bossDefeated : livingBosses !== (s.bossDefeated ? 0 : 1)) return bad();
    if (s.status === 'won' && (p.x !== s.stairs.x || p.y !== s.stairs.y)) return bad();
    const ids = new Set();
    for (const object of [...s.enemies, ...s.features, ...s.items]) {
      if (typeof object.id !== 'string' || !/^[efi]\d+$/.test(object.id) || !integer(Number(object.id.slice(1))) || Number(object.id.slice(1)) > save.uid || ids.has(object.id)) return bad();
      ids.add(object.id);
    }
    for (const key of ['kills', 'gold', 'damageDealt', 'damageTaken', 'spells', 'potionsUsed', 'floors', 'chests']) if (!integer(s.stats[key])) return bad();
    // Legacy saves did not have a camp, a floor entrance, materials or typed
    // kill counters. Missing new fields are migrated only for genuine v1 data;
    // a partial v2 extension is corruption rather than a silent reset.
    if (!extended && s.entry === undefined) s.entry = { x: s.rooms[0].cx, y: s.rooms[0].cy };
    if (!location(s.entry)) return bad();
    if (!extended && p.materials === undefined) p.materials = { wood: 0, ore: 0, herb: 0, crystal: 0 };
    if (!record(p.materials) || Object.keys(p.materials).length !== 4 || !['wood', 'ore', 'herb', 'crystal'].every(key => Object.hasOwn(p.materials, key) && integer(p.materials[key], 1000000))) return bad();
    if (!extended && s.stats.killsByType === undefined) {
      s.stats.killsByType = Object.fromEntries(enemyTypes.map(key => [key, 0]));
      s.stats.legacyKills = s.stats.kills;
    }
    if (!extended && s.stats.shrines === undefined) s.stats.shrines = 0;
    if (!record(s.stats.killsByType) || Object.keys(s.stats.killsByType).length !== enemyTypes.length || !enemyTypes.every(key => Object.hasOwn(s.stats.killsByType, key) && integer(s.stats.killsByType[key])) || !integer(s.stats.legacyKills) || !integer(s.stats.shrines)) return bad();
    if (s.stats.legacyKills + Object.values(s.stats.killsByType).reduce((sum, value) => sum + value, 0) !== s.stats.kills) return bad();
    s.campExtension = 1;
    s.choices = s.choices.map(choice => ({ ...ASHEN_PERKS.find(perk => perk.id === choice.id) }));
    const engine = Object.create(AshenEngine.prototype);
    engine.state = s; engine._rng = save.rng >>> 0; engine._uid = save.uid;
    // Every generated walkable cell belongs to one connected dungeon. Shape
    // checks alone would accept a trapped hero or an unreachable sealed exit.
    const reachable = engine._distances(p.x, p.y);
    if (s.tiles.some((row, y) => row.some((tile, x) => tile !== 0 && reachable[y][x] < 0))) return bad();
    if (s.tiles.reduce((count, row) => count + row.filter(tile => tile === 2).length, 0) !== 1) return bad();
    s.events = [];
    engine._updateFov();
    return engine;
  }
}


/* Ashen Vault — camp, quests and permanent progression.
 * DOM-free. The campaign is the sole owner of banking and settlement.
 * Engine events are presentation only; monotonic counters drive objectives.
 */
const AshenCampaignEngine = AshenEngine;
const AshenCampaignClasses = ASHEN_CLASSES;
const ashenFreeze = value => { if (value && typeof value === 'object') { Object.values(value).forEach(ashenFreeze); Object.freeze(value); } return value; };
const ASHEN_RESOURCES = ashenFreeze({
  gold: { name: 'Золото', symbol: '●', color: '#ecc97c' },
  wood: { name: 'Дерево', symbol: '▰', color: '#bf956d' },
  ore: { name: 'Руда', symbol: '◆', color: '#a0b5c9' },
  herb: { name: 'Лунная трава', symbol: '❧', color: '#8ac8a3' },
  crystal: { name: 'Кристаллы', symbol: '✦', color: '#b5a2ec' }
});
const ASHEN_NPCS = ashenFreeze([
  { id: 'warden', name: 'Мира', role: 'Начальница дозора', building: 'hearth', color: '#e0aa5d', greeting: 'Пока горит наш очаг, есть куда возвращаться. Помоги дозору — и лагерь сделает тебя сильнее.' },
  { id: 'smith', name: 'Борин', role: 'Кузнец', building: 'forge', color: '#a0b5c9', greeting: 'Внизу полно старого железа. Принеси руду, а я превращу её в силу для каждой твоей вылазки.' },
  { id: 'herbalist', name: 'Элира', role: 'Травница', building: 'garden', color: '#8ac8a3', greeting: 'Лунная трава растёт даже под камнем. Доставь её живым — посадим целый сад.' },
  { id: 'archivist', name: 'Северин', role: 'Хранитель свода', building: 'archive', color: '#b5a2ec', greeting: 'Сундуки хранят не только золото. Узнай тайны глубин, и архив разбудит твой внутренний огонь.' }
]);
const ASHEN_QUESTS = ashenFreeze([
  { id: 'watch_1', npc: 'warden', name: 'Огонь у ворот', description: 'Победи двух обитателей подземелья. Дозор даст первый допуск к восстановлению очага.', objective: { type: 'kills', target: 2 }, reward: { gold: 20, wood: 2 }, building: 'hearth', level: 1, requires: null },
  { id: 'watch_2', npc: 'warden', name: 'Разведка под сводом', description: 'После принятия задания достигни второго этажа. Мира укрепит лагерь по твоим сведениям.', objective: { type: 'floor', target: 2 }, reward: { gold: 35, wood: 2 }, building: 'hearth', level: 2, requires: 'watch_1' },
  { id: 'watch_3', npc: 'warden', name: 'Тропа к престолу', description: 'После принятия задания достигни четвёртого этажа. Даже при гибели карта пути останется у дозора.', objective: { type: 'floor', target: 4 }, reward: { gold: 70, wood: 4, crystal: 1 }, building: 'hearth', level: 3, requires: 'watch_2' },
  { id: 'forge_1', npc: 'smith', name: 'Руда для горна', description: 'Вынеси в лагерь 3 единицы руды, найденные после принятия задания. Руда останется в банке для строительства.', objective: { type: 'deliver', resource: 'ore', target: 3 }, reward: { gold: 25, wood: 1 }, building: 'forge', level: 1, requires: null },
  { id: 'forge_2', npc: 'smith', name: 'Костяные знамёна', description: 'Победи 6 костяных стражей за любое число вылазок после принятия задания.', objective: { type: 'killType', enemy: 'skeleton', target: 6 }, reward: { gold: 45, ore: 3 }, building: 'forge', level: 2, requires: 'forge_1' },
  { id: 'forge_3', npc: 'smith', name: 'Железо дозора', description: 'Победи 3 железных дозорных. Они встречаются со второго этажа; прогресс не теряется при гибели.', objective: { type: 'killType', enemy: 'sentinel', target: 3 }, reward: { gold: 80, ore: 3, crystal: 2 }, building: 'forge', level: 3, requires: 'forge_2' },
  { id: 'garden_1', npc: 'herbalist', name: 'Первые ростки', description: 'Доставь из новых вылазок 3 лунные травы. Элира сохранит их в банке и даст ещё один росток.', objective: { type: 'deliver', resource: 'herb', target: 3 }, reward: { gold: 20, herb: 1 }, building: 'garden', level: 1, requires: null },
  { id: 'garden_2', npc: 'herbalist', name: 'Живая искра', description: 'Активируй 2 святилища после принятия задания. Каждое святилище засчитывается один раз.', objective: { type: 'shrines', target: 2 }, reward: { gold: 40, herb: 3 }, building: 'garden', level: 2, requires: 'garden_1' },
  { id: 'garden_3', npc: 'herbalist', name: 'Сад под луной', description: 'Доставь ещё 8 лунных трав после принятия задания. Растения из прежних запасов не считаются новой находкой.', objective: { type: 'deliver', resource: 'herb', target: 8 }, reward: { gold: 70, crystal: 2 }, building: 'garden', level: 3, requires: 'garden_2' },
  { id: 'archive_1', npc: 'archivist', name: 'Забытые страницы', description: 'Открой 2 сундука после принятия задания. Найденные записи дадут допуск к архиву и первый кристалл.', objective: { type: 'chests', target: 2 }, reward: { gold: 25, crystal: 1 }, building: 'archive', level: 1, requires: null },
  { id: 'archive_2', npc: 'archivist', name: 'Голос глубин', description: 'После принятия задания достигни третьего этажа и узнай источник пепельного шёпота.', objective: { type: 'floor', target: 3 }, reward: { gold: 50, crystal: 2 }, building: 'archive', level: 2, requires: 'archive_1' },
  { id: 'archive_3', npc: 'archivist', name: 'Сердце углей', description: 'Победи Владыку углей на пятом этаже. Победа над ним засчитывается даже если ты не успеешь вынести добычу.', objective: { type: 'killType', enemy: 'boss', target: 1 }, reward: { gold: 100, crystal: 3 }, building: 'archive', level: 3, requires: 'archive_2' }
]);
const ASHEN_BUILDINGS = ashenFreeze([
  { id: 'hearth', npc: 'warden', name: 'Очаг дозора', description: 'Тепло очага укрепляет здоровье героя в каждой новой вылазке.', levels: [
    { cost: { gold: 20, wood: 4 }, gate: 'watch_1', bonus: { hp: 6 } },
    { cost: { gold: 55, wood: 7, ore: 3 }, gate: 'watch_2', bonus: { hp: 12 } },
    { cost: { gold: 110, wood: 10, ore: 5, crystal: 2 }, gate: 'watch_3', bonus: { hp: 20, potions: 1 } }
  ] },
  { id: 'forge', npc: 'smith', name: 'Кузница', description: 'Кузнец готовит улучшенное стартовое оружие и укреплённую броню.', levels: [
    { cost: { gold: 25, ore: 3, wood: 2 }, gate: 'forge_1', bonus: { atk: 1 } },
    { cost: { gold: 65, ore: 7, wood: 3 }, gate: 'forge_2', bonus: { atk: 2, armor: 1 } },
    { cost: { gold: 135, ore: 12, wood: 4, crystal: 4 }, gate: 'forge_3', bonus: { atk: 3, armor: 2 } }
  ] },
  { id: 'garden', npc: 'herbalist', name: 'Лунный сад', description: 'Лекарственные растения дают дополнительные стартовые зелья.', levels: [
    { cost: { gold: 20, herb: 4, wood: 2 }, gate: 'garden_1', bonus: { potions: 1 } },
    { cost: { gold: 60, herb: 8, wood: 4 }, gate: 'garden_2', bonus: { potions: 2 } },
    { cost: { gold: 120, herb: 12, wood: 6, crystal: 2 }, gate: 'garden_3', bonus: { potions: 3, hp: 4 } }
  ] },
  { id: 'archive', npc: 'archivist', name: 'Архив искр', description: 'Знания архива усиливают заклинания и запас маны в начале вылазки.', levels: [
    { cost: { gold: 25, ore: 2, crystal: 1 }, gate: 'archive_1', bonus: { mana: 3, spellPower: 1 } },
    { cost: { gold: 80, ore: 4, crystal: 3 }, gate: 'archive_2', bonus: { mana: 6, spellPower: 2 } },
    { cost: { gold: 150, ore: 6, crystal: 6 }, gate: 'archive_3', bonus: { mana: 10, spellPower: 4 } }
  ] }
]);
const ashenResourceKeys = Object.keys(ASHEN_RESOURCES);
const ashenEnemyKeys = ['rat', 'skeleton', 'archer', 'sentinel', 'bomber', 'boss'];
const ashenBonusKeys = ['hp', 'mana', 'atk', 'armor', 'potions', 'spellPower'];
const ashenZeroResources = () => Object.fromEntries(ashenResourceKeys.map(key => [key, 0]));
const ashenClone = value => JSON.parse(JSON.stringify(value));
const ashenResourceText = resources => ashenResourceKeys.filter(key => resources[key]).map(key => `${ASHEN_RESOURCES[key].name}: ${resources[key]}`).join(', ');
const ashenBonusText = bonus => {
  const labels = { hp: 'здоровья', mana: 'маны', atk: 'к атаке', armor: 'к броне', potions: 'стартовых зелий', spellPower: 'к урону заклинаний' };
  return ashenBonusKeys.filter(key => bonus[key]).map(key => `+${bonus[key]} ${labels[key]}`).join(' · ') || 'Пока нет постоянных бонусов';
};
const ashenObservation = engine => {
  const s = engine.state;
  return { kills: s.stats.kills, killsByType: { ...s.stats.killsByType }, floor: s.floor, chests: s.stats.chests, shrines: s.stats.shrines };
};

class AshenCampaign {
  constructor() {
    this.mode = 'camp';
    this.engine = null;
    this.meta = {
      resources: ashenZeroResources(),
      buildings: Object.fromEntries(ASHEN_BUILDINGS.map(building => [building.id, 0])),
      quests: Object.fromEntries(ASHEN_QUESTS.map(quest => [quest.id, { status: 'inactive', progress: 0 }])),
      stats: { runs: 0, wins: 0, deaths: 0, returns: 0, bestFloor: 0 }
    };
    this.lastRun = null;
    this.notice = 'Поговори с жителями лагеря: можно принять несколько поручений сразу.';
    this._activeRun = null;
  }

  _refuse(message) { this.notice = message; return false; }
  _questStatus(quest) {
    const record = this.meta.quests[quest.id];
    if (record.status === 'claimed') return 'claimed';
    if (record.status === 'active') return record.progress >= quest.objective.target ? 'ready' : 'active';
    return quest.requires && this.meta.quests[quest.requires].status !== 'claimed' ? 'locked' : 'available';
  }
  _objectiveText(quest) {
    const o = quest.objective;
    if (o.type === 'kills') return 'Победить врагов';
    if (o.type === 'killType') return { skeleton: 'Победить костяных стражей', sentinel: 'Победить железных дозорных', boss: 'Победить Владыку углей' }[o.enemy];
    if (o.type === 'floor') return 'Достичь этажа';
    if (o.type === 'chests') return 'Открыть сундуки';
    if (o.type === 'shrines') return 'Активировать святилища';
    return 'Доставить в лагерь: ' + ASHEN_RESOURCES[o.resource].name;
  }
  getQuestViews(npcId) {
    return ASHEN_QUESTS.filter(quest => npcId === undefined || quest.npc === npcId).map(quest => {
      const building = ASHEN_BUILDINGS.find(item => item.id === quest.building);
      const previous = ASHEN_QUESTS.find(item => item.id === quest.requires);
      return { id: quest.id, npc: quest.npc, name: quest.name, description: quest.description, status: this._questStatus(quest), progress: this.meta.quests[quest.id].progress, target: quest.objective.target,
        objectiveText: this._objectiveText(quest), reward: { ...ashenZeroResources(), ...quest.reward }, unlockText: `${building.name}: уровень ${quest.level}`, nextPrerequisiteText: previous ? `Сначала сдай задание «${previous.name}».` : 'Доступно с начала.' };
    });
  }
  getBuildingViews(npcId) {
    return ASHEN_BUILDINGS.filter(building => npcId === undefined || building.npc === npcId).map(building => {
      const level = this.meta.buildings[building.id], next = building.levels[level], current = building.levels[level - 1];
      let reason = '';
      if (this.mode !== 'camp') reason = 'Строительство доступно только в лагере.';
      else if (!next) reason = 'Максимальный уровень достигнут.';
      else if (this.meta.quests[next.gate].status !== 'claimed') reason = `Нужен допуск: сдай «${ASHEN_QUESTS.find(quest => quest.id === next.gate).name}».`;
      else {
        const missing = Object.fromEntries(Object.entries(next.cost).filter(([key, amount]) => this.meta.resources[key] < amount).map(([key, amount]) => [key, amount - this.meta.resources[key]]));
        if (Object.keys(missing).length) reason = 'Не хватает: ' + ashenResourceText(missing) + '.';
      }
      return { id: building.id, npc: building.npc, name: building.name, description: building.description, level, maxLevel: building.levels.length, cost: next ? { ...ashenZeroResources(), ...next.cost } : ashenZeroResources(), gateText: next ? 'Сдать задание «' + ASHEN_QUESTS.find(quest => quest.id === next.gate).name + '»' : 'Все допуски получены', bonusText: ashenBonusText(current ? current.bonus : {}), nextBonusText: next ? ashenBonusText(next.bonus) : 'Максимальный уровень', canUpgrade: !reason, reason };
    });
  }
  getBonuses() {
    const bonuses = Object.fromEntries(ashenBonusKeys.map(key => [key, 0]));
    for (const building of ASHEN_BUILDINGS) {
      const level = this.meta.buildings[building.id];
      if (level > 0) for (const [key, value] of Object.entries(building.levels[level - 1].bonus)) bonuses[key] += value;
    }
    return bonuses;
  }

  acceptQuest(id) {
    if (this.mode !== 'camp') return this._refuse('Задания принимают у жителей лагеря.');
    const quest = ASHEN_QUESTS.find(item => item.id === id);
    if (!quest) return this._refuse('Такого задания нет.');
    const status = this._questStatus(quest);
    if (status !== 'available') return this._refuse(status === 'locked' ? 'Сначала сдай предыдущее задание этого жителя.' : 'Это задание уже принято или сдано.');
    this.meta.quests[id] = { status: 'active', progress: 0 };
    this.notice = `Принято: «${quest.name}». Прогресс считается с этого момента.`;
    return true;
  }
  claimQuest(id) {
    if (this.mode !== 'camp') return this._refuse('Сдать задание можно только в лагере.');
    const quest = ASHEN_QUESTS.find(item => item.id === id);
    if (!quest || this._questStatus(quest) !== 'ready') return this._refuse('Задание ещё не выполнено или награда уже получена.');
    const resources = this._addResources(quest.reward);
    if (!resources) return this._refuse('Банк переполнен. Сначала потрать часть ресурсов.');
    this.meta.resources = resources;
    this.meta.quests[id] = { status: 'claimed', progress: quest.objective.target };
    this.notice = `Сдано: «${quest.name}». ${ashenResourceText(quest.reward)}. Допуск получен; строительство оплачивается отдельно.`;
    return true;
  }
  upgradeBuilding(id) {
    if (this.mode !== 'camp') return this._refuse('Строительство доступно только в лагере.');
    const view = this.getBuildingViews().find(item => item.id === id);
    if (!view || !view.canUpgrade) return this._refuse(view ? view.reason : 'Такого здания нет.');
    const resources = { ...this.meta.resources };
    for (const key of ashenResourceKeys) resources[key] -= view.cost[key];
    this.meta.resources = resources;
    this.meta.buildings[id]++;
    this.notice = `${view.name}: уровень ${this.meta.buildings[id]}. ${this.getBuildingViews().find(item => item.id === id).bonusText}. Бонусы действуют со следующей вылазки.`;
    return true;
  }
  _addResources(added) {
    const resources = { ...this.meta.resources };
    for (const key of ashenResourceKeys) {
      const value = added[key] || 0;
      if (!Number.isSafeInteger(value) || value < 0 || resources[key] + value > 1000000000) return null;
      resources[key] += value;
    }
    return resources;
  }
  startRun(options = {}) {
    if (this.mode !== 'camp') return this._refuse('Сначала заверши текущую вылазку и вернись в лагерь.');
    if (!options || typeof options !== 'object' || Array.isArray(options)) return this._refuse('Некорректные параметры вылазки.');
    const { seed = String(Date.now()), classId = 'warden' } = options;
    if (!AshenCampaignClasses.some(hero => hero.id === classId) || !['string', 'number'].includes(typeof seed) || (typeof seed === 'number' && !Number.isFinite(seed)) || String(seed).length > 200) return this._refuse('Выбери героя и корректный код подземелья.');
    if (this.meta.stats.runs >= 1000000) return this._refuse('Достигнут предел числа вылазок в этом сохранении.');
    const engine = new AshenCampaignEngine({ seed, classId, bonuses: this.getBonuses() });
    this.engine = engine;
    this.meta.stats.runs++;
    this._activeRun = { id: this.meta.stats.runs, settled: false, observed: ashenObservation(engine) };
    this.mode = 'run';
    this.lastRun = null;
    this.meta.stats.bestFloor = Math.max(this.meta.stats.bestFloor, 1);
    this._progressObjectives(null, this._activeRun.observed);
    engine._log('Ресурсы в рюкзаке сохранятся только при безопасном возвращении. У входа или лестницы можно выйти в лагерь, если не видно врагов.', 'info');
    this.notice = 'Новая вылазка: уровень 1, новые дары; постоянные бонусы лагеря уже учтены.';
    return true;
  }
  act(action) {
    if (this.mode !== 'run' || !this.engine || !this._activeRun || this._activeRun.settled) return this._refuse('Сейчас вылазка не идёт.');
    const s = this.engine.state, p = s.player;
    // The exit changes engine status irreversibly. Validate the bank transfer
    // first: even an imported bank at its numeric limit must not create an
    // unclosed run/won state that cannot be resumed or abandoned.
    if (action && action.type === 'interact' && s.status === 'playing' && s.floor === 5 && s.bossDefeated && p.x === s.stairs.x && p.y === s.stairs.y && !this._addResources({ gold: p.gold, ...p.materials })) {
      return this._refuse('В банке нет места для всей добычи. Выход не завершён, рюкзак сохранён. Можно продолжить вылазку или оставить её через меню.');
    }
    this.notice = '';
    const changed = this.engine.act(action);
    if (changed) this._observeRun();
    this._finishTerminal();
    return changed;
  }
  choose(id) {
    if (this.mode !== 'run' || !this.engine || !this._activeRun || this._activeRun.settled) return this._refuse('Сейчас нельзя выбрать дар.');
    this.notice = '';
    const changed = this.engine.choose(id);
    if (changed) this._observeRun();
    this._finishTerminal();
    return changed;
  }
  _progressObjectives(before, after) {
    for (const quest of ASHEN_QUESTS) {
      const record = this.meta.quests[quest.id], o = quest.objective;
      if (record.status !== 'active' || o.type === 'deliver') continue;
      let progress = record.progress;
      if (o.type === 'floor') progress = Math.max(progress, after.floor);
      else if (before) {
        const delta = o.type === 'killType' ? after.killsByType[o.enemy] - before.killsByType[o.enemy] : after[o.type] - before[o.type];
        progress += Math.max(0, delta);
      }
      record.progress = Math.min(o.target, progress);
    }
  }
  _observeRun() {
    const observed = ashenObservation(this.engine);
    this._progressObjectives(this._activeRun.observed, observed);
    this._activeRun.observed = observed;
    this.meta.stats.bestFloor = Math.max(this.meta.stats.bestFloor, observed.floor);
  }
  _finishTerminal() {
    if (this.mode !== 'run' || !this.engine || this._activeRun.settled) return;
    if (this.engine.state.status === 'dead') this._settle('death');
    if (this.mode === 'run' && this.engine.state.status === 'won') this._settle('victory');
  }
  canReturn() {
    if (this.mode === 'result') return { ok: true, reason: 'Итоги вылазки уже сохранены. Вернуться в лагерь.' };
    if (this.mode !== 'run' || !this.engine) return { ok: false, reason: 'Ты уже в лагере.' };
    const s = this.engine.state, p = s.player;
    if (s.status !== 'playing') return { ok: false, reason: s.status === 'choice' ? 'Сначала выбери дар нового уровня.' : 'Вылазка уже завершена.' };
    if (!((p.x === s.entry.x && p.y === s.entry.y) || (p.x === s.stairs.x && p.y === s.stairs.y))) return { ok: false, reason: 'Для безопасного выхода встань у входа этажа или на лестницу.' };
    if (s.enemies.some(enemy => s.visible[enemy.y][enemy.x])) return { ok: false, reason: 'Рядом видны враги. Разберись с ними или скройся из виду.' };
    if (!this._addResources({ gold: p.gold, ...p.materials })) return { ok: false, reason: 'В банке нет места для всей добычи. Рюкзак сохранён; оставить вылазку без добычи можно через меню.' };
    return { ok: true, reason: 'Безопасный выход: вся добыча перейдёт в банк лагеря.' };
  }
  _settle(outcome) {
    if (this.mode !== 'run' || !this._activeRun || this._activeRun.settled || !this.engine) return false;
    this._observeRun();
    const s = this.engine.state, resources = { gold: s.player.gold, ...s.player.materials }, safe = outcome === 'return' || outcome === 'victory';
    const bank = safe ? this._addResources(resources) : { ...this.meta.resources };
    if (!bank) return this._refuse('Банк переполнен: возвращение не завершено.');
    // Compute first, then commit the complete settlement synchronously. Saving
    // any public state after this call contains both bank credit and closed run.
    this.meta.resources = bank;
    if (safe) {
      for (const quest of ASHEN_QUESTS) {
        const record = this.meta.quests[quest.id], o = quest.objective;
        if (record.status === 'active' && o.type === 'deliver') record.progress = Math.min(o.target, record.progress + resources[o.resource]);
      }
    }
    if (outcome === 'return') this.meta.stats.returns++;
    if (outcome === 'death') this.meta.stats.deaths++;
    if (outcome === 'victory') this.meta.stats.wins++;
    this._activeRun.settled = true;
    this.lastRun = { outcome, seed: s.seed, floor: s.floor, level: s.player.level, kills: s.stats.kills, earned: safe ? resources : ashenZeroResources(), lost: safe ? ashenZeroResources() : resources };
    this.mode = outcome === 'return' ? 'camp' : 'result';
    this.notice = safe ? 'Ты вернулся. Добыча в банке; выполненные задания можно сдать жителям.' : 'Вылазка окончена. Рюкзак потерян; постройки, банк и прогресс боевых поручений сохранены.';
    if (outcome === 'return') { this.engine = null; this._activeRun = null; }
    return true;
  }
  returnToCamp() {
    if (this.mode === 'result') {
      this.mode = 'camp'; this.engine = null; this._activeRun = null;
      this.notice = 'Ты в лагере. Проверь задания и начни новую вылазку с первого уровня.';
      return true;
    }
    const result = this.canReturn();
    if (!result.ok) return this._refuse(result.reason);
    return this._settle('return');
  }
  abandonRun() {
    if (this.mode !== 'run' || !this.engine) return this._refuse('Активной вылазки нет.');
    if (this.engine.state.status === 'dead' || this.engine.state.status === 'won') { this._finishTerminal(); return false; }
    return this._settle('abandon');
  }

  serialize() {
    return JSON.stringify({ format: 'ashen-campaign', version: 2, mode: this.mode, meta: this.meta, engine: this.engine ? JSON.parse(this.engine.serialize()) : null, activeRun: this._activeRun, lastRun: this.lastRun });
  }
  static fromSave(text) {
    const bad = () => { throw new Error('Сохранение лагеря повреждено или относится к другой версии.'); };
    if (typeof text !== 'string' || text.length > 3500000) return bad();
    let save;
    try { save = JSON.parse(text); } catch (_) { return bad(); }
    const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    const integer = (value, max = 1000000000) => Number.isSafeInteger(value) && value >= 0 && value <= max;
    const exactKeys = (value, keys) => record(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
    const resources = value => exactKeys(value, ashenResourceKeys) && ashenResourceKeys.every(key => integer(value[key]));
    if (!record(save)) return bad();
    if (save.format === 'ashen-vault' && save.version === 1) {
      const engine = AshenCampaignEngine.fromSave(text), campaign = new AshenCampaign();
      campaign.engine = engine; campaign.mode = 'run'; campaign.meta.stats.runs = 1; campaign.meta.stats.bestFloor = engine.state.floor;
      campaign._activeRun = { id: 1, settled: false, observed: ashenObservation(engine) };
      campaign._finishTerminal();
      campaign.notice = 'Старая вылазка перенесена без повторного начисления бонусов. Личный лагерь добавлен; завершённая вылазка рассчитана по её исходу.';
      return campaign;
    }
    if (save.format !== 'ashen-campaign' || save.version !== 2 || !['camp', 'run', 'result'].includes(save.mode) || !record(save.meta)) return bad();
    const m = save.meta;
    if (!exactKeys(m, ['resources', 'buildings', 'quests', 'stats']) || !resources(m.resources) || !exactKeys(m.buildings, ASHEN_BUILDINGS.map(building => building.id)) || !ASHEN_BUILDINGS.every(building => integer(m.buildings[building.id], 3))) return bad();
    if (!exactKeys(m.quests, ASHEN_QUESTS.map(quest => quest.id))) return bad();
    for (const quest of ASHEN_QUESTS) {
      const q = m.quests[quest.id];
      if (!exactKeys(q, ['status', 'progress']) || !['inactive', 'active', 'claimed'].includes(q.status) || !integer(q.progress, quest.objective.target) || (q.status === 'inactive' && q.progress !== 0) || (q.status === 'claimed' && q.progress !== quest.objective.target)) return bad();
      if (q.status !== 'inactive' && quest.requires && m.quests[quest.requires].status !== 'claimed') return bad();
    }
    for (const building of ASHEN_BUILDINGS) for (let level = 0; level < m.buildings[building.id]; level++) if (m.quests[building.levels[level].gate].status !== 'claimed') return bad();
    const statsKeys = ['runs', 'wins', 'deaths', 'returns', 'bestFloor'];
    if (!exactKeys(m.stats, statsKeys) || !statsKeys.every(key => integer(m.stats[key], key === 'bestFloor' ? 5 : 1000000)) || m.stats.wins + m.stats.deaths + m.stats.returns > m.stats.runs || (m.stats.runs === 0) !== (m.stats.bestFloor === 0)) return bad();
    let engine = null;
    if (save.mode === 'camp') {
      if (save.engine !== null || save.activeRun !== null) return bad();
    } else {
      if (!record(save.engine) || !record(save.engine.state) || save.engine.state.campExtension !== 1) return bad();
      engine = AshenCampaignEngine.fromSave(JSON.stringify(save.engine));
      const run = save.activeRun;
      if (!exactKeys(run, ['id', 'settled', 'observed']) || !integer(run.id, 1000000) || run.id < 1 || run.id !== m.stats.runs || typeof run.settled !== 'boolean' || run.settled !== (save.mode === 'result')) return bad();
      const observed = ashenObservation(engine);
      if (!exactKeys(run.observed, Object.keys(observed)) || !exactKeys(run.observed.killsByType, ashenEnemyKeys) || Object.keys(observed).some(key => key === 'killsByType' ? ashenEnemyKeys.some(enemy => run.observed.killsByType[enemy] !== observed.killsByType[enemy]) : run.observed[key] !== observed[key])) return bad();
      if (engine.state.floor > m.stats.bestFloor) return bad();
      if (save.mode === 'run' && (!['playing', 'choice'].includes(engine.state.status) || save.lastRun !== null || m.stats.wins + m.stats.deaths + m.stats.returns >= m.stats.runs)) return bad();
    }
    const last = save.lastRun;
    if (last !== null) {
      if (!exactKeys(last, ['outcome', 'seed', 'floor', 'level', 'kills', 'earned', 'lost']) || !['return', 'death', 'victory', 'abandon'].includes(last.outcome) || typeof last.seed !== 'string' || last.seed.length > 200 || !integer(last.floor, 5) || last.floor < 1 || !integer(last.level, 1000000) || last.level < 1 || !integer(last.kills) || !resources(last.earned) || !resources(last.lost) || last.floor > m.stats.bestFloor || m.stats.runs < 1) return bad();
      const safe = last.outcome === 'return' || last.outcome === 'victory';
      if (ashenResourceKeys.some(key => (safe ? last.lost[key] : last.earned[key]) !== 0)) return bad();
      if ((last.outcome === 'victory' && (!m.stats.wins || last.floor !== 5)) || (last.outcome === 'death' && !m.stats.deaths) || (last.outcome === 'return' && !m.stats.returns)) return bad();
      if (save.mode === 'result') {
        if (last.outcome === 'return' || (last.outcome === 'death' ? engine.state.status !== 'dead' : last.outcome === 'victory' ? engine.state.status !== 'won' : !['playing', 'choice'].includes(engine.state.status))) return bad();
        const s = engine.state, bag = { gold: s.player.gold, ...s.player.materials }, resultBag = safe ? last.earned : last.lost;
        if (last.seed !== s.seed || last.floor !== s.floor || last.level !== s.player.level || last.kills !== s.stats.kills || ashenResourceKeys.some(key => bag[key] !== resultBag[key])) return bad();
      }
    } else if (save.mode === 'result' || (save.mode === 'camp' && m.stats.runs > 0)) return bad();
    const campaign = Object.create(AshenCampaign.prototype);
    campaign.mode = save.mode; campaign.meta = ashenClone(m); campaign.engine = engine; campaign.lastRun = ashenClone(last); campaign._activeRun = ashenClone(save.activeRun);
    campaign.notice = 'Сохранение загружено. Лагерь и вылазка восстановлены вместе.';
    return campaign;
  }
}


/* Trusted corpus compatibility surface. All rules remain in the reviewed
 * AshenEngine/AshenCampaign above. Never used as a generation template. */
class GameEngine extends AshenCampaign {
  constructor({seed='embers',classId='mage'}={}) {
    super(); this._forgeSeed=String(seed);this._forgeClass=classId;this._forgePaused=false;
  }
  reset({seed=this._forgeSeed,classId=this._forgeClass}={}) {
    Object.assign(this,new GameEngine({seed,classId}));return this.snapshot();
  }
  act(action) {
    if(!action||typeof action!=='object')return false;
    if(action.type==='pause'){this._forgePaused=!!action.value;return true;}
    if(this._forgePaused)return false;
    if(action.type==='start')return this.startRun({seed:action.seed??this._forgeSeed,classId:action.classId??this._forgeClass});
    if(action.type==='acceptQuest')return this.acceptQuest(action.id);
    if(action.type==='claimQuest')return this.claimQuest(action.id);
    if(action.type==='upgradeBuilding')return this.upgradeBuilding(action.id);
    if(action.type==='choose')return this.choose(action.id);
    if(action.type==='return')return this.returnToCamp();
    if(action.type==='abandon'){
      const ok=this.abandonRun();if(ok&&this.mode==='result')this.returnToCamp();return ok;
    }
    return super.act(action);
  }
  snapshot() {
    const campaign=JSON.parse(this.serialize());
    // Reload intentionally discards presentation events, never game rules.
    const events=campaign.engine?campaign.engine.state.events.map(event=>({...event,id:String(event.id)})):[];
    if(campaign.engine)campaign.engine.state.events=[];
    return {campaign,bonuses:this.getBonuses(),quests:this.getQuestViews(),buildings:this.getBuildingViews(),
      paused:this._forgePaused,events};
  }
  exportSave(){return this.serialize();}
  loadSave(text){return this.importSave(text).ok;}
  importSave(text){
    try{
      const restored=GameEngine.fromSave(text);
      restored._forgeSeed=this._forgeSeed;restored._forgeClass=this._forgeClass;
      Object.assign(this,restored);return {ok:true};
    }catch(_){return {ok:false};}
  }
  static fromSave(text){
    const restored=AshenCampaign.fromSave(text);
    Object.setPrototypeOf(restored,GameEngine.prototype);
    restored._forgeSeed=restored.engine?restored.engine.state.seed:'embers';
    restored._forgeClass=restored.engine?restored.engine.state.player.classId:'mage';
    restored._forgePaused=false;return restored;
  }
  dispose(){this._forgePaused=true;}
}
