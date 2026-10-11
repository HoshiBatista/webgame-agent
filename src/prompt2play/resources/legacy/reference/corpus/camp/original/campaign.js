/* Ashen Vault — camp, quests and permanent progression.
 * DOM-free. The campaign is the sole owner of banking and settlement.
 * Engine events are presentation only; monotonic counters drive objectives.
 */
const AshenCampaignEngine = typeof module !== 'undefined' && module.exports ? require('./engine.js').AshenEngine : AshenEngine;
const AshenCampaignClasses = typeof module !== 'undefined' && module.exports ? require('./engine.js').ASHEN_CLASSES : ASHEN_CLASSES;
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

if (typeof module !== 'undefined' && module.exports) module.exports = { AshenCampaign, ASHEN_NPCS, ASHEN_RESOURCES, ASHEN_QUESTS, ASHEN_BUILDINGS };
