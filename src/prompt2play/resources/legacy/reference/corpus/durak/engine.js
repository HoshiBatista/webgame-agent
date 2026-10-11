(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.DurakEngine = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const VERSION = '1.0.1';
  const SUITS = Object.freeze(['S', 'H', 'D', 'C']);
  const RANKS = Object.freeze([6, 7, 8, 9, 10, 11, 12, 13, 14]);
  const SYMBOLS = { S: '♠', H: '♥', D: '♦', C: '♣' };
  const LABELS = { 11: 'В', 12: 'Д', 13: 'К', 14: 'Т' };
  const ALL_CARDS = SUITS.flatMap(suit => RANKS.map(rank => suit + rank));
  const CARD_SET = new Set(ALL_CARDS);
  const STATE_KEYS = ['schemaVersion', 'seed', 'revision', 'players', 'deck', 'trumpSuit', 'trumpCard', 'discard', 'table', 'phase', 'actor', 'attacker', 'defender', 'taking', 'attackLimit', 'passed', 'round', 'roundResult', 'result', 'lastEvent'];
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const copy = value => JSON.parse(JSON.stringify(value));
  const plain = value => value !== null && typeof value === 'object' && !Array.isArray(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
  const rankOf = id => Number(id.slice(1));

  function card(id) {
    if (!CARD_SET.has(id)) throw new RangeError('Неизвестная карта: ' + String(id));
    const suit = id[0], rank = rankOf(id), rankLabel = LABELS[rank] || String(rank);
    return { id, rank, suit, symbol: SYMBOLS[suit], rankLabel, label: rankLabel + SYMBOLS[suit], red: suit === 'H' || suit === 'D' };
  }

  function beats(attack, defense, trumpSuit) {
    return attack[0] === defense[0] ? rankOf(defense) > rankOf(attack) : defense[0] === trumpSuit && attack[0] !== trumpSuit;
  }

  // Randomness is used only when creating a match. Bot decisions receive no seed.
  function seededRandom(seed) {
    let hash = 2166136261;
    for (let index = 0; index < seed.length; index++) {
      hash ^= seed.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    let value = hash >>> 0;
    return function () {
      value = (value + 0x6D2B79F5) | 0;
      let mixed = Math.imul(value ^ value >>> 15, 1 | value);
      mixed ^= mixed + Math.imul(mixed ^ mixed >>> 7, 61 | mixed);
      return ((mixed ^ mixed >>> 14) >>> 0) / 4294967296;
    };
  }

  function nextActive(state, from) {
    for (let offset = 1; offset <= state.players.length; offset++) {
      const id = (from + offset) % state.players.length;
      if (!state.players[id].out) return id;
    }
    return null;
  }

  function throwOrder(state) {
    const order = [];
    for (let offset = 0; offset < state.players.length; offset++) {
      const id = (state.attacker + offset) % state.players.length;
      if (id !== state.defender && !state.players[id].out) order.push(id);
    }
    return order;
  }

  function endRound(state) {
    state.phase = 'roundEnd';
    state.actor = null;
    state.roundResult = { kind: state.taking ? 'taken' : 'beaten', attacker: state.attacker, defender: state.defender };
  }

  function resumeThrows(state) {
    if (state.table.length >= state.attackLimit) {
      endRound(state);
      return;
    }
    state.phase = 'attack';
    for (const id of throwOrder(state)) {
      if (state.passed.includes(id)) continue;
      if (state.players[id].hand.length === 0) {
        state.passed.push(id);
        continue;
      }
      state.actor = id;
      return;
    }
    endRound(state);
  }

  function newGame(options) {
    options = options === undefined ? {} : options;
    if (!plain(options)) throw new TypeError('Параметры игры должны быть объектом.');
    const playerCount = options.playerCount === undefined ? 2 : options.playerCount;
    if (![2, 3, 4].includes(playerCount)) throw new RangeError('Число игроков — от 2 до 4.');
    const rawSeed = options.seed === undefined ? 'durak-default' : options.seed;
    if (!(typeof rawSeed === 'string' || typeof rawSeed === 'number' && Number.isFinite(rawSeed))) throw new TypeError('Seed должен быть строкой или конечным числом.');
    const seed = String(rawSeed);
    if (seed.length > 512) throw new RangeError('Seed слишком длинный.');
    const random = seededRandom(seed), deck = ALL_CARDS.slice();
    for (let index = deck.length - 1; index > 0; index--) {
      const target = Math.floor(random() * (index + 1));
      [deck[index], deck[target]] = [deck[target], deck[index]];
    }
    const trumpCard = deck[deck.length - 1], trumpSuit = trumpCard[0];
    const names = ['Вы', 'Анна', 'Борис', 'Вера'];
    const players = Array.from({ length: playerCount }, (_, id) => ({ id, name: names[id], hand: [], out: false }));
    for (let deal = 0; deal < 6; deal++) for (const player of players) player.hand.push(deck.shift());
    let attacker = null, lowest = Infinity;
    for (const player of players) for (const id of player.hand) {
      if (id[0] === trumpSuit && rankOf(id) < lowest) {
        lowest = rankOf(id);
        attacker = player.id;
      }
    }
    if (attacker === null) attacker = Math.floor(random() * playerCount);
    const defender = (attacker + 1) % playerCount;
    const state = {
      schemaVersion: 1, seed, revision: 0, players, deck, trumpSuit, trumpCard,
      discard: [], table: [], phase: 'attack', actor: attacker, attacker, defender,
      taking: false, attackLimit: 6, passed: [], round: 1, roundResult: null, result: null,
      lastEvent: { type: 'newGame', player: attacker }
    };
    const report = validate(state);
    if (!report.ok) throw new Error('Ошибка начальной раздачи: ' + report.errors.join(' '));
    return state;
  }

  function actions(state, playerId) {
    if (playerId === undefined) playerId = state.actor;
    if (state.phase === 'finished' || playerId !== state.actor) return [];
    if (state.phase === 'roundEnd') return [{ type: 'continue' }];
    const hand = state.players[playerId].hand;
    if (state.phase === 'defend') {
      const target = state.table.findIndex(pair => pair.defense === null);
      const allowed = hand.filter(id => beats(state.table[target].attack, id, state.trumpSuit))
        .map(id => ({ type: 'defend', card: id, target }));
      allowed.push({ type: 'take' });
      return allowed;
    }
    const ranks = new Set(state.table.flatMap(pair => pair.defense === null ? [rankOf(pair.attack)] : [rankOf(pair.attack), rankOf(pair.defense)]));
    const allowed = state.table.length < state.attackLimit
      ? hand.filter(id => state.table.length === 0 || ranks.has(rankOf(id))).map(id => ({ type: 'attack', card: id }))
      : [];
    if (state.table.length > 0) allowed.push({ type: 'pass' });
    return allowed;
  }

  function settleRound(state) {
    const oldAttacker = state.attacker, oldDefender = state.defender, kind = state.roundResult.kind;
    const cards = state.table.flatMap(pair => pair.defense === null ? [pair.attack] : [pair.attack, pair.defense]);
    if (kind === 'taken') state.players[oldDefender].hand.push(...cards);
    else state.discard.push(...cards);
    state.table = [];
    state.taking = false;
    state.passed = [];

    // Do not mark a temporarily empty hand out before that seat has refilled.
    const drawOrder = throwOrder(state).concat(oldDefender);
    for (const id of drawOrder) {
      const player = state.players[id];
      while (player.hand.length < 6 && state.deck.length) player.hand.push(state.deck.shift());
    }
    if (state.deck.length === 0) for (const player of state.players) player.out = player.hand.length === 0;
    const remaining = state.players.filter(player => !player.out);
    if (remaining.length <= 1) {
      const durak = remaining.length ? remaining[0].id : null;
      state.phase = 'finished';
      state.actor = null;
      state.result = { durak, winners: state.players.filter(player => player.out).map(player => player.id), draw: durak === null };
      state.lastEvent = { type: 'finished', durak, draw: durak === null };
      return;
    }
    state.attacker = kind === 'beaten' && !state.players[oldDefender].out ? oldDefender : nextActive(state, oldDefender);
    state.defender = nextActive(state, state.attacker);
    state.phase = 'attack';
    state.actor = state.attacker;
    state.attackLimit = Math.min(6, state.players[state.defender].hand.length);
    state.round++;
    state.roundResult = null;
    state.lastEvent = { type: 'roundStarted', player: state.attacker, round: state.round };
  }

  function step(state, action) {
    const before = validate(state);
    if (!before.ok) throw new TypeError('Недопустимое состояние: ' + before.errors.join(' '));
    if (!plain(action)) throw new TypeError('Действие должно быть объектом.');
    const jsonErrors = [];
    inspectJson(action, jsonErrors);
    if (jsonErrors.length) throw new TypeError('Действие должно содержать только JSON.');
    if (own(action, 'player') && action.player !== state.actor) throw new Error('Сейчас ход другого игрока.');
    const fields = action.type === 'attack' ? ['type', 'card', 'player']
      : action.type === 'defend' ? ['type', 'card', 'target', 'player'] : ['type', 'player'];
    if (Object.keys(action).some(key => !fields.includes(key))) throw new Error('Неизвестное поле действия.');
    const legal = actions(state).find(candidate => candidate.type === action.type &&
      (!own(candidate, 'card') || candidate.card === action.card) &&
      (!own(candidate, 'target') || candidate.target === action.target));
    if (!legal) throw new Error('Этот ход сейчас невозможен.');

    const next = copy(state), player = state.actor;
    next.revision++;
    if (!Number.isSafeInteger(next.revision)) throw new RangeError('Счётчик действий переполнен.');
    if (legal.type === 'attack') {
      next.players[player].hand.splice(next.players[player].hand.indexOf(legal.card), 1);
      next.table.push({ attack: legal.card, defense: null });
      next.passed = [];
      next.lastEvent = { type: 'attack', player, card: legal.card, target: next.table.length - 1 };
      if (next.taking) resumeThrows(next);
      else { next.phase = 'defend'; next.actor = next.defender; }
    } else if (legal.type === 'defend') {
      next.players[player].hand.splice(next.players[player].hand.indexOf(legal.card), 1);
      next.table[legal.target].defense = legal.card;
      next.passed = [];
      next.lastEvent = { type: 'defend', player, card: legal.card, target: legal.target };
      resumeThrows(next);
    } else if (legal.type === 'take') {
      next.taking = true;
      next.passed = [];
      next.lastEvent = { type: 'take', player };
      resumeThrows(next);
    } else if (legal.type === 'pass') {
      next.passed.push(player);
      next.lastEvent = { type: 'pass', player };
      resumeThrows(next);
    } else {
      settleRound(next);
    }
    const after = validate(next);
    if (!after.ok) throw new Error('Нарушение правил движка: ' + after.errors.join(' '));
    return next;
  }

  function view(state, viewerId) {
    if (viewerId === undefined) viewerId = 0;
    if (!Number.isInteger(viewerId) || viewerId < 0 || viewerId >= state.players.length) throw new RangeError('Неизвестный игрок.');
    const event = {};
    for (const key of ['type', 'player', 'card', 'target', 'kind', 'round', 'durak', 'draw']) {
      if (own(state.lastEvent, key)) event[key] = state.lastEvent[key];
    }
    return copy({
      schemaVersion: state.schemaVersion, revision: state.revision,
      players: state.players.map(player => ({ id: player.id, name: player.name, count: player.hand.length, out: player.out })),
      deckCount: state.deck.length, trumpSuit: state.trumpSuit, trumpCard: state.trumpCard,
      discard: state.discard, table: state.table, phase: state.phase, actor: state.actor,
      attacker: state.attacker, defender: state.defender, taking: state.taking, attackLimit: state.attackLimit,
      passed: state.passed, round: state.round, roundResult: state.roundResult, result: state.result,
      lastEvent: event, viewer: viewerId, hand: state.players[viewerId].hand,
      legalActions: actions(state, viewerId)
    });
  }

  // Persistence is a trust boundary. Reject getters, cyclic/non-JSON values and
  // impossible local rule states before the UI or a resumed bot can use them.
  function inspectJson(value, errors) {
    const active = new Set();
    let nodes = 0;
    function walk(item, depth) {
      if (++nodes > 4096 || depth > 12) { errors.push('JSON слишком большой или глубокий.'); return; }
      if (item === null || typeof item === 'boolean') return;
      if (typeof item === 'string') { if (item.length > 16384) errors.push('Слишком длинная строка.'); return; }
      if (typeof item === 'number') { if (!Number.isFinite(item)) errors.push('Неконечное число.'); return; }
      if (typeof item !== 'object') { errors.push('Значение не является JSON.'); return; }
      if (active.has(item)) { errors.push('Циклический JSON.'); return; }
      if (!Array.isArray(item) && !plain(item)) { errors.push('Объект должен быть простым JSON.'); return; }
      if (Array.isArray(item) && Object.getPrototypeOf(item) !== Array.prototype) { errors.push('У массива должен быть обычный прототип.'); return; }
      if (Object.getOwnPropertySymbols(item).length) { errors.push('Символы не разрешены в JSON.'); return; }
      active.add(item);
      const descriptors = Object.getOwnPropertyDescriptors(item);
      for (const key of Object.keys(descriptors)) {
        if (Array.isArray(item) && key === 'length') continue;
        const descriptor = descriptors[key];
        if (descriptor.get || descriptor.set || !descriptor.enumerable) { errors.push('В JSON не разрешены аксессоры или скрытые поля.'); continue; }
        if (Array.isArray(item) && (!/^(0|[1-9][0-9]*)$/.test(key) || Number(key) >= item.length)) { errors.push('У массива есть постороннее поле.'); continue; }
        walk(descriptor.value, depth + 1);
      }
      if (Array.isArray(item) && Object.keys(item).length !== item.length) errors.push('Разреженный массив не разрешён.');
      active.delete(item);
    }
    try { walk(value, 0); } catch (_) { errors.push('Не удалось прочитать JSON.'); }
  }

  function validate(state) {
    const errors = [];
    inspectJson(state, errors);
    if (errors.length) return { ok: false, errors: [...new Set(errors)] };
    if (!plain(state)) return { ok: false, errors: ['Состояние должно быть объектом.'] };
    function keys(value, expected, label) {
      if (!plain(value)) { errors.push(label + ': требуется объект.'); return false; }
      if (Object.keys(value).some(key => !expected.includes(key)) || expected.some(key => !own(value, key))) errors.push(label + ': неверные поля.');
      return true;
    }
    keys(state, STATE_KEYS, 'Состояние');
    if (state.schemaVersion !== 1) errors.push('Неизвестная версия сохранения.');
    if (typeof state.seed !== 'string' || state.seed.length > 512) errors.push('Некорректный seed.');
    if (!Number.isSafeInteger(state.revision) || state.revision < 0) errors.push('Некорректная ревизия.');
    if (!Number.isSafeInteger(state.round) || state.round < 1) errors.push('Некорректный номер раунда.');
    if (!Array.isArray(state.players) || ![2, 3, 4].includes(state.players.length)) errors.push('Некорректное число игроков.');
    if (!['attack', 'defend', 'roundEnd', 'finished'].includes(state.phase)) errors.push('Некорректная фаза.');
    if (!SUITS.includes(state.trumpSuit) || !CARD_SET.has(state.trumpCard) || state.trumpCard[0] !== state.trumpSuit) errors.push('Некорректный козырь.');
    if (typeof state.taking !== 'boolean') errors.push('Некорректный флаг взятия.');
    if (!Number.isInteger(state.attackLimit) || state.attackLimit < 1 || state.attackLimit > 6) errors.push('Некорректный лимит атаки.');
    if (!plain(state.lastEvent) || typeof state.lastEvent.type !== 'string' || !state.lastEvent.type || state.lastEvent.type.length > 64) errors.push('Некорректное последнее событие.');
    for (const field of ['deck', 'discard', 'table', 'passed']) if (!Array.isArray(state[field])) errors.push('Нет массива ' + field + '.');
    if (errors.length) return { ok: false, errors };

    const playerCount = state.players.length;
    const isSeat = id => Number.isInteger(id) && id >= 0 && id < playerCount;
    if (own(state.lastEvent, 'player') && !isSeat(state.lastEvent.player) ||
      own(state.lastEvent, 'card') && !CARD_SET.has(state.lastEvent.card) ||
      own(state.lastEvent, 'target') && (!Number.isInteger(state.lastEvent.target) || state.lastEvent.target < 0 || state.lastEvent.target > 5) ||
      own(state.lastEvent, 'round') && (!Number.isSafeInteger(state.lastEvent.round) || state.lastEvent.round < 1) ||
      own(state.lastEvent, 'durak') && !(state.lastEvent.durak === null || isSeat(state.lastEvent.durak)) ||
      own(state.lastEvent, 'draw') && typeof state.lastEvent.draw !== 'boolean' ||
      own(state.lastEvent, 'kind') && !['taken', 'beaten'].includes(state.lastEvent.kind)) errors.push('Некорректные поля последнего события.');
    if (!isSeat(state.attacker) || !isSeat(state.defender) || state.attacker === state.defender) errors.push('Некорректная пара атаки/защиты.');
    if (!(state.actor === null || isSeat(state.actor))) errors.push('Некорректный текущий игрок.');
    if (state.deck.length > 36 - playerCount * 6) errors.push('В колоде больше карт, чем после раздачи.');
    if (state.deck.length && state.deck[state.deck.length - 1] !== state.trumpCard) errors.push('Открытый козырь должен быть последним в колоде.');
    if (state.discard.length % 2 !== 0) errors.push('В отбое должны быть полные пары карт.');
    if (state.table.length > state.attackLimit) errors.push('Превышен лимит атаки.');
    if (new Set(state.passed).size !== state.passed.length || state.passed.some(id => !isSeat(id) || id === state.defender)) errors.push('Некорректная очередь пасов.');
    const seen = new Set();
    let total = 0;
    function collect(id) {
      total++;
      if (!CARD_SET.has(id)) errors.push('Неизвестная карта в состоянии.');
      else if (seen.has(id)) errors.push('Одна карта находится в двух местах: ' + id + '.');
      else seen.add(id);
    }
    for (const [index, player] of state.players.entries()) {
      if (!keys(player, ['id', 'name', 'hand', 'out'], 'Игрок')) continue;
      if (player.id !== index || typeof player.name !== 'string' || !player.name.trim() || player.name.length > 80 || typeof player.out !== 'boolean' || !Array.isArray(player.hand)) errors.push('Некорректный игрок.');
      if (Array.isArray(player.hand)) {
        player.hand.forEach(collect);
        if (player.out && (player.hand.length > 0 || state.deck.length > 0)) errors.push('Вышедший игрок должен иметь пустую руку при пустой колоде.');
      }
    }
    state.deck.forEach(collect);
    state.discard.forEach(collect);
    for (const pair of state.table) {
      if (!keys(pair, ['attack', 'defense'], 'Пара на столе')) continue;
      collect(pair.attack);
      if (pair.defense !== null) collect(pair.defense);
    }
    if (total !== 36 || seen.size !== 36) errors.push('Должны сохраниться ровно 36 уникальных карт.');
    if (errors.length) return { ok: false, errors: [...new Set(errors)] };

    for (const pair of state.table) if (pair.defense !== null && !beats(pair.attack, pair.defense, state.trumpSuit)) errors.push('Защита не бьёт карту атаки.');
    const availableRanks = new Set();
    let uncovered = 0, firstUncovered = -1;
    for (const [index, pair] of state.table.entries()) {
      if (index > 0 && !availableRanks.has(rankOf(pair.attack))) errors.push('Подкинута карта отсутствующего на столе ранга.');
      availableRanks.add(rankOf(pair.attack));
      if (pair.defense === null) { uncovered++; if (firstUncovered < 0) firstUncovered = index; }
      else { availableRanks.add(rankOf(pair.defense)); if (firstUncovered >= 0) errors.push('Нельзя отбиваться после объявления взятия.'); }
    }
    if (state.phase === 'finished') {
      const remaining = state.players.filter(player => player.hand.length > 0);
      if (state.actor !== null || state.deck.length || state.table.length || state.taking || state.passed.length || remaining.length > 1) errors.push('Неправдоподобное завершённое состояние.');
      if (state.players.some(player => player.out !== (player.hand.length === 0))) errors.push('Некорректный выход игроков.');
      if (keys(state.result, ['durak', 'winners', 'draw'], 'Результат')) {
        const durak = remaining.length ? remaining[0].id : null;
        const winners = state.players.filter(player => player.out).map(player => player.id);
        if (state.result.durak !== durak || state.result.draw !== (durak === null) || JSON.stringify(state.result.winners) !== JSON.stringify(winners)) errors.push('Результат не соответствует рукам.');
        if (plain(state.roundResult) && state.roundResult.kind === 'taken' && durak !== state.defender) errors.push('После последнего взятия проигрывает защитник.');
      }
      if (keys(state.roundResult, ['kind', 'attacker', 'defender'], 'Результат последнего раунда') &&
        (!['taken', 'beaten'].includes(state.roundResult.kind) || state.roundResult.attacker !== state.attacker || state.roundResult.defender !== state.defender)) errors.push('Нет результата последнего раунда.');
    } else {
      if (state.result !== null) errors.push('Итог игры объявлен раньше времени.');
      if (state.players[state.attacker].out || state.players[state.defender].out || state.defender !== nextActive(state, state.attacker)) errors.push('Участники раунда должны быть соседними активными игроками.');
      if (state.players.filter(player => !player.out).length < 2) errors.push('Для незавершённой игры нужны два активных игрока.');
      if (state.attackLimit !== Math.min(6, state.players[state.defender].hand.length + state.table.filter(pair => pair.defense !== null).length)) errors.push('Лимит не соответствует начальной руке защитника.');
      if (state.passed.some(id => state.players[id].out)) errors.push('Вышедший игрок не участвует в очереди.');
      const order = throwOrder(state);
      if (state.phase === 'roundEnd') {
        if (state.actor !== null || state.table.length === 0) errors.push('Некорректное ожидание завершения раунда.');
        if (keys(state.roundResult, ['kind', 'attacker', 'defender'], 'Результат раунда')) {
          if (state.roundResult.kind !== (state.taking ? 'taken' : 'beaten') || state.roundResult.attacker !== state.attacker || state.roundResult.defender !== state.defender) errors.push('Несогласованный результат раунда.');
        }
        if (state.taking ? uncovered === 0 : uncovered > 0) errors.push('Незаконченная защита не соответствует исходу раунда.');
        if (state.table.length < state.attackLimit && JSON.stringify(state.passed) !== JSON.stringify(order)) errors.push('Раунд завершён до полного круга пасов.');
        if (state.table.length === state.attackLimit && state.passed.length) errors.push('При достижении лимита раунд завершается сразу.');
      } else {
        if (state.roundResult !== null) errors.push('Результат раунда объявлен раньше времени.');
        if (!isSeat(state.actor) || state.players[state.actor].out || state.players[state.actor].hand.length === 0 && state.phase === 'attack') errors.push('Текущий игрок не может ходить.');
        if (state.phase === 'defend') {
          if (state.actor !== state.defender || state.taking || state.passed.length || uncovered !== 1 || firstUncovered !== state.table.length - 1) errors.push('Некорректная очередь защиты.');
        } else {
          if (state.actor === state.defender || state.table.length >= state.attackLimit || (state.taking ? uncovered === 0 : uncovered !== 0)) errors.push('Некорректная очередь атаки.');
          if (state.table.length === 0) {
            if (state.actor !== state.attacker || state.taking || state.passed.length) errors.push('Первую карту должен положить атакующий.');
            if (!state.deck.length && state.players.some(player => !player.out && player.hand.length === 0)) errors.push('Пустая рука должна выйти перед следующим раундом.');
          } else {
            const position = order.indexOf(state.actor);
            if (position < 0 || JSON.stringify(state.passed) !== JSON.stringify(order.slice(0, position))) errors.push('Нарушен приоритет подкидывания.');
          }
        }
      }
    }
    return { ok: errors.length === 0, errors: [...new Set(errors)] };
  }

  return Object.freeze({ VERSION, SUITS, RANKS, newGame, actions, step, view, card, validate });
});

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./engine.js'));
  else root.DurakBots = factory(root.DurakEngine);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Engine) {
  'use strict';

  function chooseAction(actorView) {
    if (!actorView || !Array.isArray(actorView.legalActions) || !actorView.legalActions.length) return null;
    const legal = actorView.legalActions;
    const rankCounts = {};
    for (const id of actorView.hand || []) {
      const rank = Engine.card(id).rank;
      rankCounts[rank] = (rankCounts[rank] || 0) + 1;
    }
    const defender = actorView.players.find(player => player.id === actorView.defender);
    // A fixed high-card endgame policy can circulate the same unanswerable
    // cards forever. Vary only the attack preference using public counters.
    // This changes no rule and does not reveal the shuffle seed to the bot.
    let publicMix = Math.imul(actorView.round | 0, 0x45d9f3b) ^ Math.imul(actorView.revision | 0, 0x27d4eb2d) ^ (actorView.viewer | 0);
    publicMix = Math.imul(publicMix ^ publicMix >>> 16, 0x45d9f3b);
    publicMix = (publicMix ^ publicMix >>> 16) >>> 0;
    const closeFinish = actorView.deckCount === 0 && defender && defender.count <= 2 && publicMix % 3 === 0;
    function score(action) {
      const value = Engine.card(action.card), trump = value.suit === actorView.trumpSuit;
      // The engine supplies legal moves; the bot ranks them without seeing any
      // opponent hand, future draw order or the random seed.
      if (action.type === 'defend') return (trump ? 32 : 0) + value.rank;
      const rankScore = closeFinish ? (14 - value.rank) * 0.55 : value.rank;
      return (trump ? 28 : 0) + rankScore - Math.min(3, (rankCounts[value.rank] || 1) - 1) * 1.6;
    }
    const plays = legal.filter(action => action.type === 'defend' || action.type === 'attack');
    if (plays.length) {
      return plays.map((action, index) => ({ action, score: score(action), index }))
        .sort((left, right) => left.score - right.score || left.action.card.localeCompare(right.action.card, 'en') || left.index - right.index)[0].action;
    }
    return legal.find(action => action.type === 'take') || legal.find(action => action.type === 'pass') || legal[0];
  }

  return Object.freeze({ chooseAction });
});

/* Compatibility adapter for the exact reviewed Durak engine above.
 * The original state machine remains authoritative; this file adds no rules. */
class GameEngine {
  constructor({seed='durak-corpus',playerCount=2}={}) {
    this.seed=String(seed);this.playerCount=playerCount;this.state=null;
    this.paused=false;this.events=[];this.session=0;
  }
  static get rules(){return globalThis.DurakEngine;}
  static get bots(){return globalThis.DurakBots;}
  reset({seed=this.seed,playerCount=this.playerCount}={}) {
    this.seed=String(seed);this.playerCount=playerCount;this.state=null;
    this.paused=false;this.events=[];this.session++;return this.snapshot();
  }
  act(action) {
    if(!action||typeof action!=='object'||Array.isArray(action))return false;
    if(action.type==='start'){
      try{this.state=GameEngine.rules.newGame({seed:action.seed??this.seed,playerCount:action.playerCount??this.playerCount});}
      catch(_){return false;}
      this.seed=this.state.seed;this.playerCount=this.state.players.length;
      this.paused=false;this.session++;this.recordEvent('deal');return true;
    }
    if(action.type==='pause'){this.paused=Boolean(action.value);return true;}
    if(this.paused||!this.state||this.state.phase==='finished')return false;
    // QA transports plain JSON across realms; reconstruct the canonical data
    // in the engine realm before the original strict plain-object validator.
    let chosen;try{chosen=JSON.parse(JSON.stringify(action));}catch(_){return false;}
    if(action.type==='stepBot') {
      if(this.state.actor===null||this.state.actor===0)return false;
      chosen=GameEngine.bots.chooseAction(GameEngine.rules.view(this.state,this.state.actor));
    } else if(action.type==='continue'){
      if(this.state.phase!=='roundEnd')return false;
    } else if(this.state.actor!==0||this.state.phase==='roundEnd')return false;
    try{const next=GameEngine.rules.step(this.state,chosen);this.state=next;this.recordEvent(chosen.type);return true;}
    catch(_){return false;}
  }
  recordEvent(type){this.events=[{id:this.session+':'+this.state.revision,type:this.state.phase==='finished'?(this.state.result.durak===0?'lose':'win'):type}];}
  snapshot() {
    // This public observation contains no opponent cards or deck order.
    const position=this.state?GameEngine.rules.view(this.state,0):null;
    const totalCards=this.state?this.state.deck.length+this.state.discard.length+
      this.state.players.reduce((n,p)=>n+p.hand.length,0)+
      this.state.table.reduce((n,p)=>n+1+Number(p.defense!==null),0):36;
    return {position,paused:this.paused,totalCards,events:JSON.parse(JSON.stringify(this.events))};
  }
  drainEvents(){const events=this.events;this.events=[];return events;}
  serialize(){return JSON.stringify({format:1,state:this.state,history:[]});}
  exportSave(){return this.serialize();}
  static parseSave(text){
    if(typeof text!=='string'||new TextEncoder().encode(text).byteLength>512000)return null;
    try{
      const saved=JSON.parse(text);
      if(!saved||saved.format!==1||!saved.state||!GameEngine.rules.validate(saved.state).ok)return null;
      return {state:saved.state,history:Array.isArray(saved.history)?saved.history.filter(x=>typeof x==='string'&&x.length<=240).slice(-80):[]};
    }catch(_){return null;}
  }
  loadSave(text){return this.importSave(text).ok;}
  importSave(text){
    const saved=GameEngine.parseSave(text);if(!saved)return {ok:false};
    this.state=saved.state;this.seed=this.state.seed;this.playerCount=this.state.players.length;
    this.paused=false;this.events=[];this.session++;return {ok:true};
  }
  dispose(){this.paused=true;this.events=[];}
}
