function createGame(ctx) {
  let phase = 'ready';
  let beacons = [false, false, false];
  let moves = 0;
  const root = ctx.root;
  const panel = document.createElement('section');
  panel.className = 'three-beacons';
  panel.setAttribute('aria-label', 'Три маяка');
  panel.innerHTML = '<header><p class="eyebrow">ТИХАЯ ГАВАНЬ · ГОЛОВОЛОМКА</p><h1>Три маяка</h1><p class="rules">Нажимайте на маяки или клавиши 1/2/3. Включите все три.</p><p class="hint">Повторное нажатие выключает маяк.</p></header><div class="counters"><span class="lit-count"></span><span class="move-count"></span></div><div class="beacon-grid" role="group" aria-label="Маяки"></div><p class="outcome" role="status" aria-live="polite" aria-atomic="true"></p><footer>Три огня — безопасный путь домой.</footer>';
  const grid = panel.querySelector('.beacon-grid');
  const litLabel = panel.querySelector('.lit-count');
  const movesLabel = panel.querySelector('.move-count');
  const outcome = panel.querySelector('.outcome');
  const buttons = [];
  for (let i = 0; i < 3; i += 1) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'beacon';
    button.dataset.testid = 'beacon-' + (i + 1);
    button.innerHTML = '<span class="beacon-number">0' + (i + 1) + '</span><span class="scene" aria-hidden="true"><span class="lighthouse"><span class="roof"></span><span class="lamp"></span><span class="rail"></span><span class="tower"></span><span class="base"></span></span><span class="water"></span></span><span class="beacon-title">Маяк ' + (i + 1) + '</span><span class="beacon-state"></span><span class="key-hint" aria-hidden="true">Клавиша ' + (i + 1) + '</span>';
    ctx.input.on(button, 'click', function () {
      dispatch({ type: 'TOGGLE_BEACON', beacon: i + 1 });
    });
    grid.appendChild(button);
    buttons.push(button);
  }
  root.appendChild(panel);

  function litCount() {
    return beacons.filter(Boolean).length;
  }
  function render() {
    panel.dataset.phase = phase;
    litLabel.textContent = 'Включено: ' + litCount() + ' из 3';
    movesLabel.textContent = 'Ходов: ' + moves;
    buttons.forEach(function (button, i) {
      const state = beacons[i] ? 'Включен' : 'Выключен';
      button.classList.toggle('is-lit', beacons[i]);
      button.setAttribute('aria-pressed', String(beacons[i]));
      button.setAttribute('aria-label', 'Маяк ' + (i + 1) + ': ' + state);
      button.disabled = phase !== 'playing';
      button.querySelector('.beacon-state').textContent = state;
    });
    outcome.textContent = phase === 'won'
      ? 'Все три маяка включены! Для новой партии нажмите «Restart / Перезапуск».'
      : phase === 'ready'
        ? 'Гавань ждет света. Нажмите «Start / Начать».'
        : 'Зажгите огни: каждый маяк переключается отдельно.';
  }
  function snapshot() {
    return { phase: phase, beacons: beacons.slice(), litCount: litCount(), moves: moves };
  }
  function dispatch(action) {
    if (!action || typeof action !== 'object') return;
    if (action.type === 'RESTART' || (action.type === 'START' && phase === 'ready')) {
      phase = 'playing';
      beacons = [false, false, false];
      moves = 0;
      render();
      return;
    }
    if (action.type !== 'TOGGLE_BEACON' || phase !== 'playing') return;
    const number = action.beacon;
    if (!Number.isInteger(number) || number < 1 || number > 3) return;
    beacons[number - 1] = !beacons[number - 1];
    moves += 1;
    if (litCount() === 3) phase = 'won';
    render();
  }
  ctx.input.key(function (key, event) {
    if (event && (event.repeat || event.ctrlKey || event.altKey || event.metaKey)) return;
    if (key === '1' || key === '2' || key === '3') {
      dispatch({ type: 'TOGGLE_BEACON', beacon: Number(key) });
    }
  });
  render();
  return { snapshot: snapshot, dispatch: dispatch, dispose: function () { panel.remove(); } };
}
