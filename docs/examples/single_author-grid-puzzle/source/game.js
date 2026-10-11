function createGame(ctx) {
  let phase = 'ready';
  let beacons = [false, false, false];
  let moves = 0;
  const root = ctx.root;
  root.innerHTML = `<section class="beacon-game" aria-labelledby="beacon-title">
    <header class="game-header"><p class="eyebrow">ТИХАЯ ГАВАНЬ · ГОЛОВОЛОМКА</p><h1 id="beacon-title">Три маяка</h1><p class="rules">Нажимайте на маяки или клавиши 1/2/3.<br>Включите все три.</p></header>
    <div class="scoreboard" aria-label="Прогресс"><span class="lit-score"></span><span class="move-score"></span></div>
    <div class="beacon-row" role="group" aria-label="Маяки"></div>
    <div class="outcome" role="status" aria-live="polite" aria-atomic="true"></div>
    <p class="footer-note">Каждое нажатие переключает один маяк.</p>
  </section>`;
  const row = root.querySelector('.beacon-row');
  const litScore = root.querySelector('.lit-score');
  const moveScore = root.querySelector('.move-score');
  const outcome = root.querySelector('.outcome');
  const buttons = [];
  for (let i = 0; i < 3; i++) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'beacon';
    button.dataset.testid = 'beacon-' + (i + 1);
    button.innerHTML = `<span class="beacon-number">0${i + 1}</span><span class="seascape" aria-hidden="true"><span class="halo"></span><span class="tower"><span class="roof"></span><span class="lantern"></span><span class="shaft"></span><span class="base"></span></span><span class="water water-one"></span><span class="water water-two"></span></span><span class="beacon-name">Маяк ${i + 1}</span><span class="beacon-state"></span><span class="key-hint" aria-hidden="true">${i + 1}</span>`;
    row.appendChild(button);
    ctx.input.on(button, 'click', function (event) {
      if (event.detail === 0 && event.repeat) return;
      dispatch({ type: 'TOGGLE_BEACON', index: i });
    });
    ctx.input.on(button, 'keydown', function (event) {
      if (event.repeat && (event.key === 'Enter' || event.key === ' ')) event.preventDefault();
    });
    buttons.push(button);
  }
  ctx.input.key(function (key, event) {
    if (event && event.repeat) return;
    if (key === '1' || key === '2' || key === '3') {
      if (event) event.preventDefault();
      dispatch({ type: 'TOGGLE_BEACON', index: Number(key) - 1 });
    }
  });
  function litCount() { return beacons.filter(Boolean).length; }
  function render() {
    const count = litCount();
    litScore.textContent = 'Включено: ' + count + '/3';
    moveScore.textContent = 'Ходов: ' + moves;
    buttons.forEach(function (button, index) {
      button.classList.toggle('is-lit', beacons[index]);
      button.setAttribute('aria-pressed', String(beacons[index]));
      button.setAttribute('aria-disabled', String(phase !== 'playing'));
      button.querySelector('.beacon-state').textContent = beacons[index] ? 'Включен' : 'Выключен';
    });
    outcome.classList.toggle('is-won', phase === 'won');
    if (phase === 'ready') outcome.textContent = 'Нажмите «Начать», чтобы зажечь маяки.';
    else if (phase === 'won') outcome.textContent = 'Все три маяка включены! Для новой партии нажмите «Перезапуск».';
    else outcome.textContent = 'Зажгите огни — укажите путь в гавань.';
  }
  function snapshot() {
    return { phase: phase, beacons: beacons.slice(), litCount: litCount(), moves: moves };
  }
  function dispatch(action) {
    if (!action || typeof action !== 'object') return;
    if (action.type === 'START' && phase === 'ready') {
      phase = 'playing';
    } else if (action.type === 'RESTART') {
      phase = 'playing';
      beacons = [false, false, false];
      moves = 0;
    } else if (action.type === 'TOGGLE_BEACON' && phase === 'playing' && Number.isInteger(action.index) && action.index >= 0 && action.index < 3) {
      beacons[action.index] = !beacons[action.index];
      moves += 1;
      if (litCount() === 3) phase = 'won';
    } else return;
    render();
  }
  render();
  return { snapshot: snapshot, dispatch: dispatch };
}
