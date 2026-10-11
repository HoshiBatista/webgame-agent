function createGame(ctx) {
  const root = ctx.root;
  let state;
  function reset() {
    state = { phase: 'ready', roundsPlayed: 0, playerRemaining: [1,2,3], botRemaining: [1,2,3], botOrder: [2,3,1], playerScore: 0, botScore: 0, history: [], result: 'none' };
  }
  reset();
  const surface = document.createElement('section');
  surface.className = 'high-card';
  surface.innerHTML = `
    <header class="game-heading"><span class="eyebrow">КАРТОЧНЫЙ ПОЕДИНОК · 3 РАУНДА</span><h1>Старшая карта</h1><p>Выберите карту. Старшая приносит очко.</p></header>
    <div class="scoreboard" aria-label="Счет"><div><span>Вы</span><strong class="player-score">0</strong></div><span class="score-colon">:</span><div><span>Бот</span><strong class="bot-score">0</strong></div><div class="round-label">Раунд 0 / 3</div></div>
    <section class="bot-zone" aria-label="Карты бота"><div class="zone-heading"><h2>Рука бота</h2><span>Скрыта до выбора</span></div><div class="bot-hand"></div></section>
    <section class="table-zone" aria-label="Последние раскрытые карты"><div class="table-pair"><div><span class="card-owner">Вы</span><div class="table-card player-table">—</div></div><span class="versus">VS</span><div><span class="card-owner">Бот</span><div class="table-card bot-table">—</div></div></div><p class="table-caption">Стол пуст — партия еще не началась</p></section>
    <div class="game-message" role="status" aria-live="polite"></div>
    <section class="player-zone" aria-label="Ваши карты"><div class="zone-heading"><h2>Ваши карты</h2><span>Нажмите или используйте 1 / 2 / 3</span></div><div class="player-hand"></div></section>
    <section class="history-zone"><h2>История раундов</h2><ol class="round-history"></ol><p class="empty-history">Здесь появятся результаты трех раундов.</p></section>
    <footer class="rules"><h2>Как играть</h2><p>У каждого карты 1, 2 и 3. Каждую можно сыграть один раз. Старшая карта дает 1 очко, равные — 0. После трех раундов сравниваем счет.</p><p>Порядок бота предопределен до партии и не зависит от вашего выбора. Его следующая карта скрыта. Для начала нажмите «Start», для новой партии — «Restart», затем «Start».</p></footer>`;
  root.appendChild(surface);
  const find = selector => surface.querySelector(selector);
  const buttons = [];
  [1,2,3].forEach(value => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'hand-card';
    button.dataset.testid = 'card-' + value;
    button.innerHTML = '<span class="corner">' + value + '</span><strong>' + value + '</strong><span class="card-state"></span>';
    ctx.input.on(button, 'click', () => dispatch({ type: 'PLAY_CARD', value }));
    find('.player-hand').appendChild(button);
    buttons.push(button);
  });
  ctx.input.key((key, event) => {
    if (event.repeat || event.ctrlKey || event.altKey || event.metaKey) return;
    if (key === '1' || key === '2' || key === '3') {
      event.preventDefault();
      dispatch({ type: 'PLAY_CARD', value: Number(key) });
    }
  });
  function render() {
    find('.player-score').textContent = state.playerScore;
    find('.bot-score').textContent = state.botScore;
    find('.round-label').textContent = state.phase === 'playing' ? 'Раунд ' + (state.roundsPlayed + 1) + ' / 3' : 'Сыграно ' + state.roundsPlayed + ' / 3';
    const botHand = find('.bot-hand');
    botHand.replaceChildren();
    for (let i = 0; i < 3; i++) {
      const card = document.createElement('div');
      const past = state.history[i];
      card.className = 'bot-card' + (past ? ' used' : ' hidden-card');
      const number = document.createElement('strong');
      number.textContent = past ? String(past.botCard) : '?';
      const label = document.createElement('span');
      label.textContent = past ? 'Использована' : 'Закрыта';
      card.append(number, label);
      botHand.appendChild(card);
    }
    const last = state.history[state.history.length - 1];
    find('.player-table').textContent = last ? last.playerCard : '—';
    find('.bot-table').textContent = last ? last.botCard : '—';
    find('.table-zone').classList.toggle('revealed', !!last);
    find('.table-caption').textContent = last ? 'Раунд ' + last.round + ': ' + (last.winner === 'player' ? 'ваше очко' : last.winner === 'bot' ? 'очко бота' : 'равные карты — без очков') : 'Стол пуст — карты еще не раскрыты';
    const message = find('.game-message');
    message.classList.toggle('outcome', state.result !== 'none');
    message.textContent = state.phase === 'ready' ? 'Готовы? Нажмите Start, чтобы начать.' : state.phase === 'playing' ? 'Ваш ход — выберите доступную карту' : (state.result === 'victory' ? 'Победа!' : state.result === 'defeat' ? 'Поражение' : 'Ничья') + ' · ' + state.playerScore + ':' + state.botScore + ' · Партия завершена';
    buttons.forEach((button, index) => {
      const value = index + 1;
      const used = !state.playerRemaining.includes(value);
      button.disabled = state.phase !== 'playing' || used;
      button.classList.toggle('used', used);
      button.querySelector('.card-state').textContent = used ? 'Использована' : state.phase === 'ready' ? 'До начала' : 'Выбрать';
      button.setAttribute('aria-label', 'Карта ' + value + (used ? ', использована' : ''));
    });
    const history = find('.round-history');
    history.replaceChildren();
    state.history.forEach(entry => {
      const item = document.createElement('li');
      item.textContent = entry.round + '. Вы ' + entry.playerCard + ' : ' + entry.botCard + ' Бот — ' + (entry.winner === 'player' ? '+1 вам' : entry.winner === 'bot' ? '+1 боту' : 'ничья');
      history.appendChild(item);
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
    if (action.type !== 'PLAY_CARD' || state.phase !== 'playing' || !state.playerRemaining.includes(action.value)) return;
    const playerCard = action.value;
    const botCard = state.botOrder[state.roundsPlayed];
    const winner = playerCard > botCard ? 'player' : playerCard < botCard ? 'bot' : 'tie';
    state.playerRemaining = state.playerRemaining.filter(value => value !== playerCard);
    state.botRemaining = state.botRemaining.filter(value => value !== botCard);
    if (winner === 'player') state.playerScore++;
    if (winner === 'bot') state.botScore++;
    state.roundsPlayed++;
    state.history.push({ round: state.roundsPlayed, playerCard, botCard, winner });
    if (state.roundsPlayed === 3) {
      state.result = state.playerScore > state.botScore ? 'victory' : state.playerScore < state.botScore ? 'defeat' : 'draw';
      state.phase = state.result === 'defeat' ? 'lost' : 'won';
    }
    render();
  }
  render();
  return { snapshot() { return JSON.parse(JSON.stringify(state)); }, dispatch };
}
