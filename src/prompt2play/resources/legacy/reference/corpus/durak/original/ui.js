(function (root) {
  'use strict';

  const E = root.DurakEngine;
  const B = root.DurakBots;
  const doc = root.document;
  const STORAGE_KEY = 'durak.cardclub.match.v1';
  const PREFS_KEY = 'durak.cardclub.preferences.v1';
  const $ = id => doc.getElementById(id);
  const copy = value => JSON.parse(JSON.stringify(value));
  const esc = value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
  const SUIT_NAMES = { S: 'пики', H: 'червы', D: 'бубны', C: 'трефы' };
  const RANK_NAMES = { 6: 'Шестёрка', 7: 'Семёрка', 8: 'Восьмёрка', 9: 'Девятка', 10: 'Десятка', 11: 'Валет', 12: 'Дама', 13: 'Король', 14: 'Туз' };
  let state = null;
  let selected = null;
  let target = null;
  let session = 0;
  let advanceTimer = null;
  let advanceTicket = 0;
  let manualPaused = false;
  let pageHidden = false;
  let modal = null;
  let returnModal = null;
  let previousFocus = null;
  let initialized = false;
  let destroyed = false;
  let renderedView = null;
  let renderedSession = -1;
  let shownResult = null;
  let saveText = 'Без регистрации · работает без сети';
  let saveWarning = false;
  let observedSave = null;
  let saveConflict = false;
  let history = [];
  let preferences = { playerCount: 2, sound: false, quick: false };
  let audioContext = null;
  let audioMaster = null;
  let noiseBuffer = null;
  let audioResumePending = null;
  const audioNodes = new Map();
  const listeners = [];

  function listen(element, event, callback, options) {
    if (!element) return;
    element.addEventListener(event, callback, options);
    listeners.push(() => element.removeEventListener(event, callback, options));
  }

  function fullCardLabel(id) {
    const c = E.card(id);
    return RANK_NAMES[c.rank] + ', ' + SUIT_NAMES[c.suit];
  }

  function cardArt(id) {
    const c = E.card(id);
    const ink = c.red ? '#b3423e' : '#263d3d';
    const accent = '#b08b43';
    const smallRank = c.rank === 10 ? 18 : 21;
    const corner = '<text x="12" y="23" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="' + smallRank + '" font-weight="700">' + c.rankLabel + '</text><text x="12" y="40" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="17">' + c.symbol + '</text>';
    let middle = '';
    if (c.rank === 14) {
      middle = '<path d="M50 35 72 72 50 109 28 72Z" fill="none" stroke="' + accent + '" stroke-opacity=".3" stroke-width=".7"/><text x="50" y="89" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="55">' + c.symbol + '</text><path d="M39 118h22" stroke="' + accent + '" stroke-width=".9"/>';
    } else if (c.rank > 10) {
      const crown = c.rank === 13
        ? '<path d="m33 41-3-12 12 6 8-13 8 13 12-6-3 12Z" fill="' + accent + '"/><path d="M35 37h30M38 29l2 4m20-4-2 4" stroke="#faeed0" stroke-width="1"/>'
        : c.rank === 12
          ? '<path d="m33 40 3-13 8 7 6-11 6 11 8-7 3 13Z" fill="' + accent + '"/><circle cx="50" cy="29" r="2" fill="' + ink + '"/><path d="M36 40h29" stroke="#f7e9c5" stroke-width="1.3"/>'
          : '<path d="M31 40q8-15 21-14l14 9 4 7Z" fill="' + ink + '"/><path d="M38 34h23M57 26l8-5-3 8" stroke="' + accent + '" fill="none" stroke-width="2"/>';
      const portrait = crown + '<path d="M36 42q0 20 14 22 14-2 14-22" fill="#ebcf9d" stroke="' + accent + '" stroke-width="1"/><path d="M39 46h7m8 0h7M50 48l-2 7h4m-8 3q6 4 12 0" fill="none" stroke="' + ink + '" stroke-width="1"/><path d="m35 45 2 16 9 5-15 6m34-27-2 16-9 5 15 6" fill="none" stroke="' + ink + '" stroke-width="2.2"/><path d="m26 72 14-11 10 9 10-9 14 11" fill="' + ink + '" stroke="' + accent + '" stroke-width="1"/><path d="m38 64 12 8 12-8M31 70l6 4m32-4-6 4" fill="none" stroke="' + accent + '" stroke-width="2"/>';
      middle = '<rect x="24" y="22" width="52" height="100" rx="2" fill="#f2e5c8" stroke="' + accent + '" stroke-width=".75"/><g>' + portrait + '</g><g transform="rotate(180 50 72)">' + portrait + '</g><path d="M25 72h50" stroke="' + accent + '" stroke-width="2"/><path d="m43 72 7-5 7 5-7 5Z" fill="' + accent + '"/><text x="18" y="77" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="12">' + c.symbol + '</text><text x="82" y="77" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="12">' + c.symbol + '</text>';
    } else {
      const pipLayouts = {
        6: [[31,36],[69,36],[31,72],[69,72],[31,108],[69,108]],
        7: [[31,36],[69,36],[31,72],[69,72],[31,108],[69,108],[50,53]],
        8: [[31,36],[69,36],[31,72],[69,72],[31,108],[69,108],[50,53],[50,91]],
        9: [[31,34],[69,34],[31,59],[69,59],[31,85],[69,85],[31,110],[69,110],[50,72]],
        10: [[31,34],[69,34],[31,59],[69,59],[31,85],[69,85],[31,110],[69,110],[50,47],[50,97]]
      };
      middle = pipLayouts[c.rank].map(([x, y]) => '<g transform="translate(' + x + ' ' + y + ') ' + (y > 72 ? 'rotate(180)' : '') + '"><text y="8" text-anchor="middle" fill="' + ink + '" font-family="Georgia,serif" font-size="24">' + c.symbol + '</text></g>').join('');
    }
    return '<svg class="card-art" viewBox="0 0 100 144" aria-hidden="true" focusable="false"><rect x=".5" y=".5" width="99" height="143" rx="8" fill="#fbf7e9" stroke="#e3decb"/>' + corner + '<g transform="rotate(180 50 72)">' + corner + '</g>' + middle + '</svg>';
  }

  function cardsWord(count) {
    const teen = count % 100;
    return count + ' ' + (teen >= 11 && teen <= 14 ? 'карт' : count % 10 === 1 ? 'карта' : count % 10 >= 2 && count % 10 <= 4 ? 'карты' : 'карт');
  }

  function playerName(id, view) {
    const player = view.players.find(item => item.id === id);
    return player ? player.name : 'Игрок';
  }

  function roleFor(player, view) {
    if (player.out) return 'Вышли без карт';
    if (view.phase === 'finished') return view.result && view.result.durak === player.id ? 'Остался с картами' : 'Партия завершена';
    if (view.taking && view.defender === player.id) return 'Берёт карты';
    if (view.phase === 'roundEnd') return view.defender === player.id ? 'Завершает раунд' : 'Ожидает раздачи';
    if (view.actor === player.id) return view.phase === 'defend' ? 'Отбивается' : view.table.length ? 'Может подкинуть' : 'Ходит первым';
    if (view.defender === player.id) return 'Защищается';
    return 'Ожидает хода';
  }

  function renderOpponents(view) {
    if (!view) {
      $('opponents').innerHTML = '<div class="seat"><div class="seat-heading"><div class="seat-avatar">♣</div><div class="seat-info"><span class="seat-name">Место напротив</span><span class="seat-role">Скоро займут</span></div></div><div class="seat-hand"><span class="mini-back" style="--x:0px;--r:0deg"></span></div></div>';
      return;
    }
    $('opponents').innerHTML = view.players.filter(player => player.id !== 0).map(player => {
      const backs = Math.min(7, player.count);
      const stack = Array.from({ length: backs }, (_, index) => '<span class="mini-back" style="--x:' + ((index - (backs - 1) / 2) * 10) + 'px;--r:' + ((index - (backs - 1) / 2) * 4) + 'deg"></span>').join('');
      const thinking = view.actor === player.id && view.phase !== 'roundEnd' && view.phase !== 'finished' ? '<span class="thinking" aria-hidden="true"><i></i><i></i><i></i></span>' : '';
      return '<div class="seat' + (view.actor === player.id ? ' active' : '') + (player.out ? ' out' : '') + '" data-seat="' + player.id + '" aria-label="' + esc(player.name + ', ' + cardsWord(player.count) + '. ' + roleFor(player, view)) + '"><div class="seat-heading"><div class="seat-avatar" aria-hidden="true">' + (player.out ? '✓' : esc(player.name.slice(0, 1))) + '</div><div class="seat-info"><span class="seat-name">' + esc(player.name) + '</span><span class="seat-role">' + esc(roleFor(player, view)) + thinking + '</span></div></div><div class="seat-hand" aria-hidden="true">' + (player.out ? '<span class="seat-out-mark">ВЫШЕЛ ✓</span>' : stack + '<span class="seat-card-count">' + player.count + '</span>') + '</div></div>';
    }).join('');
  }

  function renderDeck(view) {
    const stack = $('deck-stack');
    stack.className = 'deck-stack';
    if (!view) {
      stack.innerHTML = '<div class="deck-back" aria-hidden="true"></div>';
      $('deck-count').textContent = '36';
      $('trump-label').textContent = 'Козырь после раздачи';
      stack.setAttribute('aria-label', 'Колода 36 карт');
      return;
    }
    $('deck-count').textContent = String(view.deckCount);
    const trump = E.card(view.trumpCard);
    if (view.deckCount === 0) {
      stack.classList.add('empty');
      stack.innerHTML = '<span aria-hidden="true">' + trump.symbol + '</span>';
      stack.setAttribute('aria-label', 'Колода закончилась');
    } else {
      if (view.deckCount === 1) stack.classList.add('last');
      stack.innerHTML = '<div class="trump-card" role="img" aria-label="Открытый козырь: ' + esc(fullCardLabel(view.trumpCard)) + '">' + cardArt(view.trumpCard) + '</div>' + (view.deckCount > 1 ? '<div class="deck-back" aria-hidden="true"></div>' : '');
      stack.setAttribute('aria-label', cardsWord(view.deckCount) + ' в колоде');
    }
    $('trump-label').innerHTML = 'Козырь <span class="trump-symbol' + (trump.red ? ' red' : '') + '" aria-label="' + SUIT_NAMES[trump.suit] + '">' + trump.symbol + '</span>';
  }

  function renderTable(view, changed) {
    const field = $('battlefield');
    field.className = 'battlefield';
    field.setAttribute('data-pairs', String(view ? view.table.length : 0));
    $('round-toast').classList.remove('visible');
    $('round-toast').textContent = '';
    if (!view || view.table.length === 0) {
      let title = 'Партия начинается с хода';
      let text = 'Раздайте карты, а мы подскажем, что делать дальше.';
      if (view) {
        title = view.phase === 'finished' ? 'Партия завершена.' : view.actor === 0 ? 'Ваш первый ход' : 'Ходит ' + playerName(view.actor, view);
        text = view.phase === 'finished' ? 'Можно устроить ещё одну партию.' : view.actor === 0 ? 'Выберите любую карту из руки и положите её на стол.' : 'Соперник выбирает карту. Немного терпения.';
      }
      field.innerHTML = '<div class="empty-table"><span class="empty-suit" aria-hidden="true">♧</span><strong>' + esc(title) + '</strong><p>' + esc(text) + '</p></div>';
      return;
    }
    const previousCards = new Set(renderedView && renderedSession === session ? renderedView.table.flatMap(pair => [pair.attack, pair.defense]).filter(Boolean) : []);
    const targetActions = view.legalActions.filter(action => action.type === 'defend');
    const selectedActions = targetActions.filter(action => action.card === selected);
    if (selectedActions.length && !selectedActions.some(action => action.target === target)) target = selectedActions[0].target;
    field.innerHTML = view.table.map((pair, index) => {
      const canTarget = targetActions.some(action => action.target === index);
      const targeted = pair.defense === null && (target === index && selectedActions.length || targetActions.some(action => action.target === index));
      const attackClass = 'table-card' + (canTarget ? ' target-card' : '') + (changed && !previousCards.has(pair.attack) ? ' card-arrive' : '');
      const tag = canTarget ? 'button' : 'div';
      const attack = '<' + tag + ' class="' + attackClass + '"' + (canTarget ? ' type="button" data-target="' + index + '"' : ' role="img"') + ' aria-label="' + esc((canTarget ? 'Отбить: ' : 'Атака: ') + fullCardLabel(pair.attack)) + '">' + cardArt(pair.attack) + '</' + tag + '>';
      const defense = pair.defense ? '<div class="table-card defense-card' + (changed && !previousCards.has(pair.defense) ? ' card-arrive' : '') + '" role="img" aria-label="' + esc('Защита: ' + fullCardLabel(pair.defense)) + '">' + cardArt(pair.defense) + '</div>' : '';
      return '<div class="card-pair' + (pair.defense === null ? ' uncovered' : '') + (targeted ? ' targeted' : '') + '">' + attack + defense + (canTarget ? '<span class="target-label">' + (selected ? 'Бьём эту карту' : 'Нужно отбить') + '</span>' : '') + '</div>';
    }).join('');
    if (view.phase === 'roundEnd') {
      field.classList.add('settling');
      if (view.roundResult.kind === 'taken') field.classList.add('taken');
      $('round-toast').textContent = view.roundResult.kind === 'taken' ? playerName(view.defender, view) + (view.defender === 0 ? ' забираете стол' : ' забирает стол') : 'Отбой. Все карты побиты';
      $('round-toast').classList.add('visible');
    } else if (view.taking) {
      $('round-toast').textContent = (view.defender === 0 ? 'Вы берёте' : playerName(view.defender, view) + ' берёт') + ' · ещё можно подкинуть';
      $('round-toast').classList.add('visible');
    }
  }

  function renderHand(view, changed) {
    const scroll = $('hand-scroll');
    const previousScroll = scroll.scrollLeft || 0;
    if (!view || view.hand.length === 0) {
      const out = view && view.players[0].out;
      $('hand').innerHTML = '<div class="no-hand">' + (out ? '<span class="spectator-mark" aria-hidden="true">✧</span><strong>Вы вышли без карт.</strong><p>' + (view.phase === 'finished' ? 'Отличный повод сыграть ещё раз.' : 'Теперь можно посмотреть финал соперников.') + '</p>' : '<span class="spectator-mark" aria-hidden="true">♠</span><p>' + (view ? 'Карт на руках нет. Дождитесь завершения раунда.' : 'Ваша рука появится здесь') + '</p>') + '</div>';
      return;
    }
    const previousHand = new Set(renderedView && renderedSession === session ? renderedView.hand : []);
    const legalCards = new Set(view.legalActions.filter(action => action.card).map(action => action.card));
    const hand = view.hand.slice().sort((a, b) => {
      const ca = E.card(a), cb = E.card(b);
      const ta = ca.suit === view.trumpSuit ? 1 : 0, tb = cb.suit === view.trumpSuit ? 1 : 0;
      return ta - tb || E.SUITS.indexOf(ca.suit) - E.SUITS.indexOf(cb.suit) || ca.rank - cb.rank;
    });
    $('hand').innerHTML = hand.map((id, index) => {
      const playable = legalCards.has(id);
      const isSelected = selected === id;
      const trump = E.card(id).suit === view.trumpSuit;
      const arrival = changed && !previousHand.has(id);
      const classes = 'hand-card' + (playable ? ' selectable' : '') + (isSelected ? ' selected' : '') + (arrival ? ' deal-in' : '');
      const label = fullCardLabel(id) + (trump ? ', козырь' : '') + (isSelected ? ', выбрана' : playable ? ', можно сыграть' : ', сейчас сыграть нельзя');
      return '<button type="button" class="' + classes + '" data-card="' + id + '" aria-label="' + esc(label) + '" aria-pressed="' + isSelected + '"' + (!playable ? ' disabled' : '') + (arrival ? ' style="animation-delay:' + (Math.min(index, 7) * 35) + 'ms"' : '') + '>' + cardArt(id) + (trump ? '<span class="trump-badge" aria-hidden="true">КОЗЫРЬ</span>' : '') + (isSelected ? '<span class="selected-check" aria-hidden="true">✓</span>' : '') + '</button>';
    }).join('');
    scroll.scrollLeft = previousScroll;
  }

  function renderStatus(view) {
    const play = $('btn-play'), pass = $('btn-pass'), take = $('btn-take');
    play.hidden = false;
    play.disabled = true;
    pass.hidden = true;
    take.hidden = true;
    $('hand-panel').classList.toggle('human-turn', Boolean(view && view.actor === 0));
    if (!view) {
      $('match-label').textContent = 'ВАШ СТОЛ ГОТОВ';
      $('round-number').textContent = '01';
      $('discard-count').textContent = '0';
      $('round-limit').textContent = 'Колода 36 карт';
      $('hand-count').textContent = '0 карт';
      $('human-role').textContent = 'Участник клуба';
      $('turn-label').textContent = 'ГОТОВЫ К ПАРТИИ?';
      $('turn-message').textContent = 'Выберите число игроков и раздайте карты.';
      $('hand-hint').textContent = 'Устраивайтесь поудобнее. Сейчас раздадим.';
      play.innerHTML = 'Выберите карту <span aria-hidden="true">↗</span>';
      return;
    }
    $('match-label').textContent = 'ПАРТИЯ · ' + view.players.length + ' ИГРОКА';
    $('round-number').textContent = String(view.round).padStart(2, '0');
    $('discard-count').textContent = String(view.discard.length);
    $('round-limit').textContent = view.phase === 'finished' ? 'Партия завершена' : 'На столе ' + view.table.length + ' из ' + view.attackLimit;
    $('hand-count').textContent = cardsWord(view.hand.length);
    $('human-role').textContent = roleFor(view.players[0], view);
    const legal = view.legalActions;
    const cards = legal.filter(action => action.card);
    const chosen = cards.find(action => action.card === selected && (action.type !== 'defend' || action.target === target));
    pass.hidden = !legal.some(action => action.type === 'pass');
    take.hidden = !legal.some(action => action.type === 'take');
    pass.textContent = view.taking ? 'Не подкидываю' : 'Больше не подкидываю';
    play.disabled = !chosen;
    play.innerHTML = (chosen ? (chosen.type === 'defend' ? 'Отбить ' : 'Сыграть ') + esc(E.card(chosen.card).label) : 'Выберите карту') + ' <span aria-hidden="true">↗</span>';
    if (!cards.length) play.hidden = true;
    let label, message, hint;
    if (view.phase === 'finished') {
      label = 'ПАРТИЯ ЗАВЕРШЕНА';
      message = view.result.draw ? 'Ничья: ни у кого не осталось карт.' : view.result.durak === 0 ? 'В этот раз карты остались у вас. Сыграем ещё?' : playerName(view.result.durak, view) + ' — последний игрок с картами. Вы вышли из игры!';
      hint = 'Новая раздача — новая история.';
    } else if (view.phase === 'roundEnd') {
      label = 'ЗАВЕРШАЕМ РАУНД';
      message = view.roundResult.kind === 'beaten' ? 'Отбой. Игроки добирают карты до шести.' : (view.defender === 0 ? 'Вы забираете' : playerName(view.defender, view) + ' забирает') + ' карты со стола. Затем — добор.';
      hint = 'Следующий заход начнётся автоматически.';
    } else if (view.players[0].out) {
      label = 'ВЫ УЖЕ ВЫШЛИ';
      message = 'Игра продолжается. ' + playerName(view.actor, view) + (view.phase === 'defend' ? ' отбивается.' : ' выбирает ход.');
      hint = 'Смотрим финал компьютерных соперников.';
    } else if (view.actor === 0) {
      if (view.phase === 'defend') {
        label = 'ВАШ ХОД · ЗАЩИТА';
        const attack = view.table.find(pair => pair.defense === null);
        message = attack ? 'Нужно побить ' + E.card(attack.attack).label + '. ' + (cards.length ? 'Выберите подходящую карту или нажмите «Беру».' : 'Подходящих карт нет. Нажмите «Беру».') : 'Выберите карту для защиты.';
        hint = cards.length ? 'Подсвечены карты, которыми можно отбиться.' : 'Нет подходящей карты — можно забрать стол.';
      } else {
        label = view.table.length ? 'ВАШ ХОД · ПОДКИДЫВАЕМ' : 'ВАШ ХОД · АТАКА';
        message = !view.table.length ? 'Начните с любой карты. Следующий игрок будет отбиваться.' : view.taking ? 'Защитник берёт. Можно подкинуть до лимита или спасовать.' : cards.length ? 'Можно подкинуть карту того же достоинства, что есть на столе, или спасовать.' : 'Подкинуть нечего. Нажмите «Больше не подкидываю».';
        hint = selected ? 'Карта выбрана. Подтвердите ход кнопкой.' : cards.length ? 'Сначала выберите карту, затем подтвердите ход.' : 'В этом заходе вы можете пропустить подкидывание.';
      }
    } else {
      label = 'ХОД СОПЕРНИКА';
      message = playerName(view.actor, view) + (view.phase === 'defend' ? ' решает, чем отбиться.' : view.taking ? ' решает, что подкинуть перед взятием.' : view.table.length ? ' может подкинуть ещё одну карту.' : ' выбирает первую карту.');
      hint = view.taking && view.defender === 0 ? 'Решение «Беру» принято. Ждём остальных.' : 'Ваши карты никуда не торопятся.';
    }
    if (view.hand.length >= 9) hint += ' Руку можно прокручивать вбок.';
    $('turn-label').textContent = label;
    $('turn-message').textContent = message;
    $('hand-hint').textContent = hint;
  }

  function renderPreferences() {
    $('btn-sound').setAttribute('aria-pressed', String(preferences.sound));
    $('btn-sound').setAttribute('title', preferences.sound ? 'Выключить звуки' : 'Включить звуки');
    $('btn-sound').setAttribute('aria-label', preferences.sound ? 'Выключить звуки' : 'Включить звуки');
    $('sound-label').textContent = preferences.sound ? 'Звук вкл.' : 'Звук выкл.';
    $('btn-speed').setAttribute('aria-pressed', String(preferences.quick));
    $('speed-label').textContent = preferences.quick ? 'Быстрый темп' : 'Обычный темп';
    doc.documentElement.classList.toggle('quick-tempo', preferences.quick);
    doc.querySelectorAll('[data-player-count]').forEach(button => {
      const chosen = Number(button.getAttribute('data-player-count')) === preferences.playerCount;
      button.classList.toggle('selected', chosen);
      button.setAttribute('aria-pressed', String(chosen));
    });
    $('save-status').textContent = saveText;
    $('save-status').classList.toggle('warning', saveWarning);
  }

  function renderHistory() {
    $('last-move').textContent = history.length ? history[history.length - 1] : '36 карт. Никакой спешки.';
    $('history-list').innerHTML = history.length ? history.slice().reverse().map(entry => '<li>' + esc(entry) + '</li>').join('') : '<li>Пока ни одного хода. Всё впереди.</li>';
  }

  function render() {
    if (destroyed) return;
    const focused = doc.activeElement;
    const focusedCard = focused && $('hand').contains(focused) ? focused.getAttribute('data-card') : null;
    const focusedTarget = focused && $('battlefield').contains(focused) ? focused.getAttribute('data-target') : null;
    const view = state ? E.view(state, 0) : null;
    const changed = Boolean(view && (renderedSession !== session || !renderedView || renderedView.revision !== view.revision));
    if (selected && (!view || !view.legalActions.some(action => action.card === selected))) { selected = null; target = null; }
    renderOpponents(view);
    renderDeck(view);
    renderTable(view, changed);
    renderHand(view, changed);
    renderStatus(view);
    renderPreferences();
    renderHistory();
    // These controls are replaced by rendering; preserve their keyboard identity.
    if (focusedCard !== null) focusControl($('hand').querySelector('[data-card="' + focusedCard + '"]'));
    else if (focusedTarget !== null) focusControl($('battlefield').querySelector('[data-target="' + focusedTarget + '"]'));
    renderedView = view;
    renderedSession = session;
    if (view && view.phase === 'finished' && shownResult !== session + ':' + view.revision) {
      shownResult = session + ':' + view.revision;
      renderResult(view);
      openModal('result');
    }
    scheduleAdvance();
  }

  function notice(message) {
    $('notice').textContent = message || '';
    $('notice').hidden = !message;
  }

  function updateSaveStatus(text, warning) {
    saveText = text;
    saveWarning = Boolean(warning);
    if ($('save-status')) {
      $('save-status').textContent = text;
      $('save-status').classList.toggle('warning', saveWarning);
    }
  }

  function writePreferences() {
    try { root.localStorage.setItem(PREFS_KEY, JSON.stringify(preferences)); }
    catch (_) { updateSaveStatus('Только в этой вкладке · сохранение недоступно', true); }
  }

  function markSaveConflict() {
    saveConflict = true;
    updateSaveStatus('Сохранение изменено в другой вкладке · эта партия только здесь', true);
    return false;
  }

  function checkSaveSlot() {
    if (!state || saveConflict) return !saveConflict;
    try {
      if (root.localStorage.getItem(STORAGE_KEY) !== observedSave) return markSaveConflict();
      return true;
    } catch (_) {
      updateSaveStatus('Только в этой вкладке · сохранение недоступно', true);
      return false;
    }
  }

  function saveMatch(explicitNewGame) {
    if (!state) return false;
    if (saveConflict && !explicitNewGame) return markSaveConflict();
    try {
      if (!E.validate(state).ok) throw new Error('Invalid state');
      const current = root.localStorage.getItem(STORAGE_KEY);
      if (explicitNewGame) { observedSave = current; saveConflict = false; }
      else if (current !== observedSave) return markSaveConflict();
      const serialized = JSON.stringify({ format: 1, state, history: history.slice(-80) });
      root.localStorage.setItem(STORAGE_KEY, serialized);
      // Only a successful write becomes the checkpoint for this live branch.
      observedSave = serialized;
      updateSaveStatus('Партия сохранена на этом устройстве', false);
      return true;
    } catch (_) {
      updateSaveStatus('Только в этой вкладке · сохранение недоступно', true);
      return false;
    }
  }

  function loadStorage() {
    try {
      const rawPreferences = root.localStorage.getItem(PREFS_KEY);
      if (rawPreferences) {
        const saved = JSON.parse(rawPreferences);
        if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
          if ([2, 3, 4].includes(saved.playerCount)) preferences.playerCount = saved.playerCount;
          if (typeof saved.sound === 'boolean') preferences.sound = saved.sound;
          if (typeof saved.quick === 'boolean') preferences.quick = saved.quick;
        }
      }
    } catch (_) { updateSaveStatus('Настройки доступны только в этой вкладке', true); }
    try {
      const raw = root.localStorage.getItem(STORAGE_KEY);
      observedSave = raw;
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (!saved || saved.format !== 1 || !saved.state || !E.validate(saved.state).ok) {
        updateSaveStatus('Сохранение повреждено · начните новую партию', true);
        return;
      }
      state = copy(saved.state);
      session++;
      history = Array.isArray(saved.history) ? saved.history.filter(entry => typeof entry === 'string' && entry.length <= 240).slice(-80) : [];
      updateSaveStatus('Найдена сохранённая партия', false);
    } catch (_) { updateSaveStatus('Сохранение недоступно · можно играть в этой вкладке', true); }
  }

  function addHistory(message) {
    history.push(message);
    if (history.length > 160) history.splice(0, history.length - 160);
  }

  function describeAction(action, before, after) {
    const view = E.view(before, 0);
    const name = playerName(before.actor, view);
    if (action.type === 'attack') return name + (before.actor === 0 ? (before.table.length ? ' подкидываете ' : ' ходите ') : (before.table.length ? ' подкидывает ' : ' ходит ')) + E.card(action.card).label + '.';
    if (action.type === 'defend') return name + (before.actor === 0 ? ' бьёте ' : ' бьёт ') + E.card(before.table[action.target].attack).label + ' картой ' + E.card(action.card).label + '.';
    if (action.type === 'take') return name + (before.actor === 0 ? ' решили забрать карты.' : ' решает забрать карты.');
    if (action.type === 'pass') return name + (before.actor === 0 ? ' больше не подкидываете.' : ' больше не подкидывает.');
    if (action.type === 'continue') {
      const result = before.roundResult;
      const base = 'Раунд ' + before.round + ': ' + (result.kind === 'beaten' ? 'отбой.' : playerName(result.defender, view) + (result.defender === 0 ? ' забираете ' : ' забирает ') + cardsWord(before.table.reduce((sum, pair) => sum + (pair.defense ? 2 : 1), 0)) + '.');
      if (after.phase === 'finished') return base + ' Партия завершена.';
      return base + ' Следующий ход: ' + playerName(after.attacker, view) + '.';
    }
    return 'Началась новая партия.';
  }

  function actionEqual(a, b) {
    if (!a || !b || typeof a !== 'object' || Array.isArray(a)) return false;
    const fields = b.type === 'attack' ? ['type', 'card', 'player'] : b.type === 'defend' ? ['type', 'card', 'target', 'player'] : ['type', 'player'];
    return Object.keys(a).every(key => fields.includes(key)) && a.type === b.type && a.card === b.card && a.target === b.target && (a.player === undefined || a.player === state.actor);
  }

  function applyAction(action, source) {
    if (!state || destroyed) return false;
    if (source === 'human' && (state.actor !== 0 || isPaused() || state.phase === 'roundEnd' || state.phase === 'finished')) return false;
    const legal = source === 'system' && state.phase === 'roundEnd' ? E.actions(state) : E.actions(state, source === 'human' ? 0 : state.actor);
    const canonical = legal.find(candidate => actionEqual(action, candidate));
    if (!canonical) return false;
    const before = state;
    try {
      const next = E.step(before, canonical);
      state = next;
      selected = null;
      target = null;
      notice('');
      addHistory(describeAction(canonical, before, next));
      if (before.players[0].out === false && next.players[0].out && next.phase !== 'finished') addHistory('Вы вышли без карт. Теперь можно посмотреть финал соперников.');
      saveMatch();
      sound(next.phase === 'finished' ? (next.result.durak === 0 ? 'lose' : 'win') : canonical.type);
      render();
      return true;
    } catch (_) {
      notice('Не удалось выполнить ход. Состояние партии сохранено; попробуйте другую допустимую карту.');
      cancelAdvance();
      return false;
    }
  }

  function isPaused() { return manualPaused || pageHidden || Boolean(doc.hidden) || Boolean(modal) || destroyed; }

  function cancelAdvance() {
    advanceTicket++;
    if (advanceTimer !== null) { root.clearTimeout(advanceTimer); advanceTimer = null; }
  }

  function scheduleAdvance() {
    cancelAdvance();
    if (!state || isPaused() || state.phase === 'finished' || state.actor === 0 && state.phase !== 'roundEnd') return;
    const expectedSession = session;
    const expectedRevision = state.revision;
    const expectedPhase = state.phase;
    const expectedTicket = advanceTicket;
    const delay = state.phase === 'roundEnd' ? (preferences.quick ? 340 : 860) : (preferences.quick ? 300 : 820 + state.revision % 3 * 95);
    advanceTimer = root.setTimeout(() => {
      if (expectedTicket !== advanceTicket) return;
      advanceTimer = null;
      if (!state || isPaused() || session !== expectedSession || state.revision !== expectedRevision || state.phase !== expectedPhase) return;
      if (state.phase === 'roundEnd') { applyAction({ type: 'continue' }, 'system'); return; }
      if (state.actor === 0 || state.actor === null) return;
      try {
        const actorView = E.view(state, state.actor);
        const action = B.chooseAction(actorView);
        if (!action || !applyAction(action, 'bot')) throw new Error('Bot did not return an available move');
      } catch (_) {
        cancelAdvance();
        notice('Соперник не смог завершить ход. Откройте и закройте правила, чтобы повторить попытку, или начните новую партию.');
      }
    }, delay);
  }

  function freshSeed() {
    try {
      const bytes = new Uint32Array(2);
      root.crypto.getRandomValues(bytes);
      return Date.now().toString(36) + '-' + bytes[0].toString(36) + bytes[1].toString(36);
    } catch (_) { return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2); }
  }

  function newGame(options, seed) {
    if (destroyed) return null;
    const settings = typeof options === 'number' ? { playerCount: options, seed } : options || {};
    const count = settings.playerCount === undefined ? preferences.playerCount : settings.playerCount;
    if (![2, 3, 4].includes(count)) throw new RangeError('Выберите от 2 до 4 игроков.');
    const next = E.newGame({ playerCount: count, seed: settings.seed === undefined ? freshSeed() : settings.seed });
    cancelAdvance();
    session++;
    state = next;
    manualPaused = false;
    selected = null;
    target = null;
    shownResult = null;
    history = [];
    preferences.playerCount = count;
    addHistory('Новая партия на ' + count + ' игроков. Козырь: ' + E.card(next.trumpCard).symbol + '. Первым ходит ' + playerName(next.attacker, E.view(next, 0)) + '.');
    closeModal(true);
    $('history-panel').hidden = true;
    $('btn-history').setAttribute('aria-expanded', 'false');
    notice('');
    writePreferences();
    saveMatch(true);
    cancelSounds();
    if (preferences.sound && audioContext) unlockAudio();
    sound('deal');
    render();
    return copy(state);
  }

  function selectCard(id) {
    if (!state || isPaused() || state.actor !== 0) return false;
    const view = E.view(state, 0);
    const options = view.legalActions.filter(action => action.card === id);
    if (!options.length) return false;
    selected = selected === id ? null : id;
    target = selected && options[0].type === 'defend' ? options[0].target : null;
    notice('');
    sound('select');
    render();
    const button = $('hand').querySelector('[data-card="' + id + '"]');
    if (button) {
      try { button.focus({ preventScroll: true }); } catch (_) { /* Older webviews may not support focus options. */ }
      if (typeof button.scrollIntoView === 'function') button.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'auto' });
    }
    return true;
  }

  function selectTarget(index) {
    if (!state || isPaused() || state.actor !== 0 || !Number.isInteger(index)) return false;
    const actions = E.view(state, 0).legalActions.filter(action => action.type === 'defend' && action.target === index);
    if (!actions.length) return false;
    target = index;
    if (selected && !actions.some(action => action.card === selected)) selected = null;
    render();
    return true;
  }

  function playSelected() {
    if (!state || !selected) return false;
    const action = E.view(state, 0).legalActions.find(item => item.card === selected && (item.type !== 'defend' || item.target === target));
    return action ? applyAction(action, 'human') : false;
  }

  function openModal(name) {
    if (destroyed) return;
    if (name === 'rules') returnModal = modal === 'start' || modal === 'result' ? modal : null;
    else returnModal = null;
    if (!modal) previousFocus = doc.activeElement;
    ['start', 'rules', 'result'].forEach(item => { $('modal-' + item).hidden = item !== name; });
    modal = name;
    cancelAdvance();
    doc.body.classList.add('modal-open');
    $('app').setAttribute('inert', '');
    $('app').setAttribute('aria-hidden', 'true');
    if (name === 'start') {
      $('welcome-title').textContent = state ? 'Новая партия.' : 'Дурак.';
      $('welcome-copy').innerHTML = state ? 'Выберите компанию для следующей раздачи.<br>Текущая партия заменится после нажатия кнопки.' : 'Знакомая игра. Достойная компания.<br>Один стол — вы и компьютерные соперники.';
      $('btn-resume').hidden = !state;
      $('btn-resume').textContent = state && state.phase === 'finished' ? 'Посмотреть завершённую партию' : 'Продолжить партию';
      $('btn-close-start').hidden = !state;
    }
    const overlay = $('modal-' + name);
    const focusable = overlay.querySelector('button:not([hidden]):not([disabled])');
    if (focusable && typeof focusable.focus === 'function') focusable.focus();
  }

  function closeModal(force) {
    if (!force && modal === 'rules' && returnModal) {
      const destination = returnModal;
      returnModal = null;
      openModal(destination);
      return;
    }
    if (!force && !state) { openModal('start'); return; }
    ['start', 'rules', 'result'].forEach(item => { $('modal-' + item).hidden = true; });
    modal = null;
    returnModal = null;
    doc.body.classList.remove('modal-open');
    $('app').removeAttribute('inert');
    $('app').removeAttribute('aria-hidden');
    if (!focusControl(previousFocus)) focusControl($('btn-new'));
    previousFocus = null;
    scheduleAdvance();
  }

  function focusControl(element) {
    if (!element || element === doc.body || !doc.contains(element) || element.disabled || element.closest('[hidden], [inert]') || typeof element.focus !== 'function') return false;
    try { element.focus({ preventScroll: true }); }
    catch (_) { try { element.focus(); } catch (_) { return false; } }
    return true;
  }

  function renderResult(view) {
    const result = view.result;
    let title, description, emblem;
    if (result.draw) {
      title = 'Ничья. Красиво.';
      description = 'Последние карты ушли в отбой. За этим столом сегодня нет дурака.';
      emblem = '♧';
    } else if (result.durak === 0) {
      title = 'Реванш?';
      description = 'На этот раз карты остались у вас. Колода уже ждёт, чтобы всё переиграть.';
      emblem = '♦';
    } else {
      title = 'Вы вышли!';
      description = 'У вас не осталось карт. ' + playerName(result.durak, view) + ' завершает эту партию с картами на руках.';
      emblem = '♠';
    }
    $('result-title').textContent = title;
    $('result-copy').textContent = description;
    $('result-emblem').textContent = emblem;
    $('result-summary').innerHTML = '<div><strong>' + view.round + '</strong><span>раундов</span></div><div><strong>' + view.players.length + '</strong><span>игрока</span></div><div><strong>' + (result.draw ? '—' : esc(playerName(result.durak, view))) + '</strong><span>' + (result.draw ? 'дурака нет' : 'остался с картами') + '</span></div>';
  }

  function unlockAudio() {
    if (!preferences.sound || destroyed || manualPaused || pageHidden || doc.hidden) return false;
    try {
      if (!audioContext) {
        const Context = root.AudioContext || root.webkitAudioContext;
        if (!Context) throw new Error('No audio');
        audioContext = new Context();
        audioMaster = audioContext.createGain();
        audioMaster.gain.value = 0.24;
        audioMaster.connect(audioContext.destination);
      }
      if (audioContext.state !== 'running' && audioContext.state !== 'closed' && typeof audioContext.resume === 'function' && !audioResumePending) {
        const context = audioContext;
        const resumed = context.resume();
        if (resumed && typeof resumed.then === 'function') {
          const pending = { context };
          audioResumePending = pending;
          resumed.then(() => {
            if (audioResumePending === pending) audioResumePending = null;
            if (context === audioContext && (!preferences.sound || destroyed || manualPaused || pageHidden || doc.hidden)) suspendAudio();
          }, () => { if (audioResumePending === pending) audioResumePending = null; });
        }
      }
      return true;
    } catch (_) {
      preferences.sound = false;
      renderPreferences();
      notice('Этот браузер не поддерживает звуки игры. Партию можно продолжить без звука.');
      return false;
    }
  }

  function trackSound(source, nodes) {
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      source.onended = null;
      nodes.forEach(node => { try { node.disconnect(); } catch (_) { /* Already disconnected. */ } });
      audioNodes.delete(source);
    };
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
    if (!preferences.sound || destroyed || manualPaused || pageHidden || doc.hidden || modal && modal !== 'result' || !audioContext || audioContext.state !== 'running') return;
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

  function suspendAudio() {
    cancelSounds();
    if (audioContext && audioContext.state === 'running' && typeof audioContext.suspend === 'function') {
      try {
        const context = audioContext;
        const promise = context.suspend();
        if (promise && typeof promise.then === 'function') promise.then(() => {
          // A newer unmute may have arrived while suspend was still pending.
          if (context === audioContext && preferences.sound && !destroyed && !manualPaused && !pageHidden && !doc.hidden) unlockAudio();
        }, () => {});
      } catch (_) { /* Best effort. */ }
    }
  }

  function init() {
    if (initialized && !destroyed) return root.DurakApp;
    if (!E || !B || !doc) throw new Error('Durak engine, bots and document are required.');
    initialized = true;
    destroyed = false;
    cancelAdvance();
    session++;
    state = null; selected = null; target = null;
    manualPaused = false; modal = null; returnModal = null; previousFocus = null;
    renderedView = null; renderedSession = -1; shownResult = null;
    observedSave = null; saveConflict = false; history = [];
    preferences = { playerCount: 2, sound: false, quick: false };
    updateSaveStatus('Без регистрации · работает без сети', false);
    ['start', 'rules', 'result'].forEach(name => { $('modal-' + name).hidden = true; });
    $('history-panel').hidden = true;
    $('btn-history').setAttribute('aria-expanded', 'false');
    notice('');
    pageHidden = Boolean(doc.hidden);
    $('welcome-queen').innerHTML = cardArt('H12');
    $('welcome-ace').innerHTML = cardArt('S14');
    listen($('hand'), 'click', event => {
      const card = event.target.closest ? event.target.closest('[data-card]') : null;
      if (card && !card.disabled && $('hand').contains(card)) { unlockAudio(); selectCard(card.getAttribute('data-card')); }
    });
    listen($('battlefield'), 'click', event => {
      const element = event.target.closest ? event.target.closest('[data-target]') : null;
      if (element && $('battlefield').contains(element)) selectTarget(Number(element.getAttribute('data-target')));
    });
    listen($('btn-play'), 'click', () => { unlockAudio(); playSelected(); });
    listen($('btn-pass'), 'click', () => { unlockAudio(); applyAction({ type: 'pass' }, 'human'); });
    listen($('btn-take'), 'click', () => { unlockAudio(); applyAction({ type: 'take' }, 'human'); });
    listen($('btn-start'), 'click', () => { unlockAudio(); newGame(); });
    listen($('btn-new'), 'click', () => openModal('start'));
    listen($('btn-close-start'), 'click', () => closeModal());
    listen($('btn-resume'), 'click', () => { unlockAudio(); closeModal(true); if (state && state.phase === 'finished') { renderResult(E.view(state, 0)); openModal('result'); } });
    listen($('btn-rules'), 'click', () => openModal('rules'));
    listen($('btn-welcome-rules'), 'click', () => openModal('rules'));
    listen($('btn-close-rules'), 'click', () => closeModal());
    listen($('btn-rules-done'), 'click', () => closeModal());
    listen($('btn-close-result'), 'click', () => closeModal());
    listen($('btn-result-table'), 'click', () => closeModal());
    listen($('btn-again'), 'click', () => openModal('start'));
    listen($('btn-sound'), 'click', () => {
      preferences.sound = !preferences.sound;
      if (preferences.sound) { unlockAudio(); sound('select'); } else suspendAudio();
      writePreferences(); renderPreferences();
    });
    listen($('btn-speed'), 'click', () => { preferences.quick = !preferences.quick; writePreferences(); renderPreferences(); scheduleAdvance(); });
    doc.querySelectorAll('[data-player-count]').forEach(button => listen(button, 'click', () => { preferences.playerCount = Number(button.getAttribute('data-player-count')); writePreferences(); renderPreferences(); }));
    listen($('btn-history'), 'click', () => { const show = $('history-panel').hidden; $('history-panel').hidden = !show; $('btn-history').setAttribute('aria-expanded', String(show)); });
    listen($('btn-close-history'), 'click', () => { $('history-panel').hidden = true; $('btn-history').setAttribute('aria-expanded', 'false'); $('btn-history').focus(); });
    ['start', 'rules', 'result'].forEach(name => listen($('modal-' + name), 'click', event => { if (event.target === $('modal-' + name) && state) closeModal(); }));
    listen(doc, 'keydown', event => {
      if (event.key === 'Escape') {
        if (modal) { event.preventDefault(); closeModal(); }
        else if (selected) { selected = null; target = null; render(); event.preventDefault(); }
      } else if (event.key === 'Tab' && modal) {
        const buttons = Array.from($('modal-' + modal).querySelectorAll('button:not([hidden]):not([disabled])')).filter(button => !button.closest('[hidden]'));
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (buttons.length && event.shiftKey && (doc.activeElement === first || !buttons.includes(doc.activeElement))) { event.preventDefault(); last.focus(); }
        else if (buttons.length && !event.shiftKey && (doc.activeElement === last || !buttons.includes(doc.activeElement))) { event.preventDefault(); first.focus(); }
      } else if (event.key === 'Enter' && !modal && selected) {
        const element = event.target;
        const handCard = element && element.closest ? element.closest('.hand-card') : null;
        if (!element || element === doc || element === doc.body || element.id === 'btn-play' || handCard && handCard.getAttribute('data-card') === selected) { event.preventDefault(); unlockAudio(); playSelected(); }
      }
    });
    listen(doc, 'visibilitychange', () => { pageHidden = Boolean(doc.hidden); if (pageHidden) { cancelAdvance(); suspendAudio(); } else { checkSaveSlot(); if (preferences.sound && audioContext) unlockAudio(); scheduleAdvance(); } });
    listen(root, 'pagehide', () => { pageHidden = true; cancelAdvance(); suspendAudio(); });
    listen(root, 'pageshow', () => { pageHidden = Boolean(doc.hidden); checkSaveSlot(); if (!pageHidden && preferences.sound && audioContext) unlockAudio(); scheduleAdvance(); });
    listen(root, 'storage', event => { if (event.key === null || event.key === STORAGE_KEY) checkSaveSlot(); });
    loadStorage();
    render();
    openModal('start');
    return root.DurakApp;
  }

  function setPaused(value) {
    manualPaused = Boolean(value);
    if (manualPaused) { cancelAdvance(); suspendAudio(); }
    else { if (preferences.sound && audioContext) unlockAudio(); scheduleAdvance(); }
    return manualPaused;
  }

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    session++;
    cancelAdvance();
    listeners.splice(0).forEach(remove => remove());
    cancelSounds();
    if (audioMaster) { try { audioMaster.disconnect(); } catch (_) { /* Best effort. */ } }
    if (audioContext && typeof audioContext.close === 'function') {
      try { const promise = audioContext.close(); if (promise && typeof promise.catch === 'function') promise.catch(() => {}); } catch (_) { /* Best effort. */ }
    }
    audioContext = null; audioMaster = null; noiseBuffer = null; audioResumePending = null;
    doc.body.classList.remove('modal-open');
    $('app').removeAttribute('inert');
    $('app').removeAttribute('aria-hidden');
  }

  root.DurakApp = Object.freeze({
    init, newGame, selectCard, selectTarget, playSelected,
    dispatch: action => applyAction(action, 'human'),
    getState: () => state ? copy(state) : null,
    getView: () => state ? E.view(state, 0) : null,
    setPaused, destroy,
    storageKey: STORAGE_KEY,
    preferencesKey: PREFS_KEY
  });
  init();
})(typeof window !== 'undefined' ? window : globalThis);
