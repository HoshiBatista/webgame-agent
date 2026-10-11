function createGame(ctx) {
  const root = ctx.root;
  let state;
  const reset = () => {
    state = { phase: 'ready', roundsPlayed: 0, playerRemaining: [1,2,3], botRemaining: [1,2,3], botOrder: [2,3,1], playerScore: 0, botScore: 0, history: [], result: 'none' };
  };
  root.innerHTML = `<main class="higher-card">
    <header><span class="eyebrow">ТРИ КАРТЫ · ТРИ РАУНДА</span><h1>Старшая карта</h1><p>Выберите момент для своей сильной карты.</p></header>
    <section class="scoreboard" aria-label="Счет"><div>Вы <strong class="player-score">0</strong></div><span class="round-label">Раунды: 0 / 3</span><div><strong class="bot-score">0</strong> Бот</div></section>
    <p class="message" role="status" aria-live="polite"></p>
    <section class="table" aria-label="Сыгранные карты"><div class="seat"><span>Вы</span><div class="table-card player-card">—</div></div><span class="versus">против</span><div class="seat"><span>Бот</span><div class="table-card bot-card">—</div></div></section>
    <section class="hand-section" aria-label="Ваши карты"><h2>Ваша рука</h2><div class="hand"></div><p class="hint">Нажмите карту или клавишу 1, 2, 3.<br>Tab — выбор кнопки, Enter / Пробел — ход.</p></section>
    <section class="history-section"><h2>История раундов</h2><ol class="history"></ol><p class="empty-history">Здесь появятся результаты ваших ходов.</p></section>
    <section class="rules"><h2>Как играть</h2><p>У каждого по три карты: 1, 2 и 3. Каждая играется один раз. Старшая карта приносит очко; равные карты — без очков.</p><p>Бот всегда играет в порядке <b>2 → 3 → 1</b>, независимо от вашего выбора. После трех раундов сравнивается счет.</p><p>Начните кнопкой «Start» на панели. «Restart» сбрасывает партию; затем нажмите «Start» снова.</p></section>
  </main>`;
  const find = s => root.querySelector(s);
  const buttons = [1,2,3].map(value => {
    const button = root.ownerDocument.createElement('button');
    button.type = 'button';
    button.className = 'hand-card';
    button.dataset.testid = 'card-' + value;
    button.innerHTML = `<span class="corner">${value}</span><span class="number">${value}</span><span class="card-state"></span>`;
    find('.hand').appendChild(button);
    ctx.input.on(button, 'click', () => dispatch({ type: 'PLAY_CARD', value }));
    ctx.input.on(button, 'keydown', event => {
      if (event.repeat && (event.key === 'Enter' || event.key === ' ')) event.preventDefault();
    });
    return button;
  });
  function render() {
    find('.player-score').textContent = state.playerScore;
    find('.bot-score').textContent = state.botScore;
    find('.round-label').textContent = 'Раунды: ' + state.roundsPlayed + ' / 3';
    const outcomes = { victory: 'Победа!', defeat: 'Поражение', draw: 'Ничья' };
    find('.message').textContent = state.phase === 'ready' ? 'Готовы? Нажмите «Start», чтобы начать.' : state.phase === 'playing' ? 'Раунд ' + (state.roundsPlayed + 1) + ': выберите оставшуюся карту' : outcomes[state.result] + ' · Итоговый счет ' + state.playerScore + ':' + state.botScore;
    const last = state.history[state.history.length - 1];
    find('.player-card').textContent = last ? last.playerCard : '—';
    find('.bot-card').textContent = last ? last.botCard : '—';
    buttons.forEach((button, index) => {
      const used = !state.playerRemaining.includes(index + 1);
      button.disabled = used || state.phase !== 'playing';
      button.classList.toggle('used', used);
      const label = used ? 'Использована' : state.phase === 'ready' ? 'До начала' : 'Выбрать';
      button.querySelector('.card-state').textContent = label;
      button.setAttribute('aria-label', 'Карта ' + (index + 1) + '. ' + label);
    });
    find('.history').replaceChildren();
    state.history.forEach(entry => {
      const item = root.ownerDocument.createElement('li');
      const result = entry.winner === 'player' ? 'Вам +1' : entry.winner === 'bot' ? 'Боту +1' : 'Ничья · без очков';
      item.textContent = 'Вы ' + entry.playerCard + ' : ' + entry.botCard + ' Бот — ' + result;
      find('.history').appendChild(item);
    });
    find('.empty-history').hidden = state.history.length > 0;
  }
  function dispatch(action) {
    if (!action || typeof action !== 'object') return;
    if (action.type === 'RESTART') {
      reset();
      render();
      return;
    }
    if (action.type === 'START') {
      if (state.phase !== 'ready') return;
      state.phase = 'playing';
      render();
      return;
    }
    if (action.type !== 'PLAY_CARD' || state.phase !== 'playing') return;
    const value = action.value;
    if (!state.playerRemaining.includes(value)) return;
    const botCard = state.botOrder[state.roundsPlayed];
    const winner = value > botCard ? 'player' : value < botCard ? 'bot' : 'draw';
    state.playerRemaining = state.playerRemaining.filter(card => card !== value);
    state.botRemaining = state.botRemaining.filter(card => card !== botCard);
    if (winner === 'player') state.playerScore++;
    if (winner === 'bot') state.botScore++;
    state.roundsPlayed++;
    state.history.push({ round: state.roundsPlayed, playerCard: value, botCard, winner });
    if (state.roundsPlayed === 3) {
      state.result = state.playerScore > state.botScore ? 'victory' : state.playerScore < state.botScore ? 'defeat' : 'draw';
      state.phase = state.result === 'defeat' ? 'lost' : 'won';
    }
    render();
  }
  ctx.input.key((key, event) => {
    if (event.repeat) return;
    if (key === '1' || key === '2' || key === '3') {
      event.preventDefault();
      dispatch({ type: 'PLAY_CARD', value: Number(key) });
    }
  });
  reset();
  render();
  return { snapshot: () => JSON.parse(JSON.stringify(state)), dispatch };
}
