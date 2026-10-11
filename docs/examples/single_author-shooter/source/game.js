function createGame(ctx) {
  const root = ctx.root;
  root.innerHTML = `<section class="range-game"><header><div class="eyebrow">КОРОТКИЙ ТИР · 01</div><h1>Мишени</h1><p class="subtitle">Три цели. Три права на ошибку.</p></header><div class="scoreboard"><span class="score"></span><span class="attempts"></span></div><div class="arena" tabindex="0" aria-label="Тир: нажимайте на круглые мишени"><canvas aria-label="Три движущиеся мишени"></canvas><div class="target" data-testid="target-1" aria-label="Мишень 1"></div><div class="target" data-testid="target-2" aria-label="Мишень 2"></div><div class="target" data-testid="target-3" aria-label="Мишень 3"></div></div><p class="outcome" role="status" aria-live="polite"></p><p class="rules">Нажмите Start, затем стреляйте касанием или кликом по кругам. Клавиши <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> попадают в соответствующие цели. Три попадания — победа, три промаха — поражение. Попадания не расходуют попытки.</p><footer>360 × 360 <span>ТОЧНОСТЬ ВАЖНЕЕ СКОРОСТИ</span></footer></section>`;
  const arena = root.querySelector('.arena');
  const canvas = root.querySelector('canvas');
  const g = canvas.getContext('2d');
  const areas = Array.from(root.querySelectorAll('.target'));
  const scoreLabel = root.querySelector('.score');
  const attemptsLabel = root.querySelector('.attempts');
  const outcome = root.querySelector('.outcome');
  const colors = ['#57e6c1', '#ffca68', '#b7a0ff'];
  let phase, score, misses, targets, simulationTick;
  let paused = false;
  let disposed = false;
  let pixelRatio = 1;
  function reset() {
    phase = 'ready'; score = 0; misses = 0; simulationTick = 0;
    targets = [
      {id: 1, alive: true, x: 80, y: 70, radius: 26, vx: 18},
      {id: 2, alive: true, x: 180, y: 180, radius: 26, vx: -22},
      {id: 3, alive: true, x: 280, y: 290, radius: 26, vx: 16}
    ];
  }
  function render() {
    scoreLabel.textContent = `Попадания: ${score}/3`;
    attemptsLabel.textContent = `Осталось попыток: ${3 - misses}`;
    outcome.dataset.phase = phase;
    outcome.textContent = phase === 'won' ? 'Победа! Все три мишени поражены. Ещё партия — Restart.' : phase === 'lost' ? 'Попытки закончились. Попробуйте снова — Restart.' : paused ? 'Пауза' : phase === 'ready' ? 'Готовы? Нажмите Start.' : 'Цельтесь в круги — или нажимайте 1 / 2 / 3.';
    g.setTransform(canvas.width / 360, 0, 0, canvas.height / 360, 0, 0);
    g.fillStyle = '#101c2c'; g.fillRect(0, 0, 360, 360);
    g.strokeStyle = '#203047'; g.lineWidth = 0.6;
    for (let n = 20; n < 360; n += 20) {
      g.beginPath(); g.moveTo(n, 0); g.lineTo(n, 360); g.stroke();
      g.beginPath(); g.moveTo(0, n); g.lineTo(360, n); g.stroke();
    }
    targets.forEach((t, i) => {
      const area = areas[i];
      area.hidden = !t.alive;
      area.style.left = `${(t.x - t.radius) / 3.6}%`;
      area.style.top = `${(t.y - t.radius) / 3.6}%`;
      area.style.width = `${2 * t.radius / 3.6}%`;
      area.style.height = `${2 * t.radius / 3.6}%`;
      g.strokeStyle = '#304159'; g.setLineDash([3, 6]);
      g.beginPath(); g.moveTo(16, t.y); g.lineTo(344, t.y); g.stroke(); g.setLineDash([]);
      if (!t.alive) {
        g.fillStyle = colors[i]; g.font = '12px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillText('ПОПАДАНИЕ', 180, t.y); return;
      }
      g.shadowColor = colors[i]; g.shadowBlur = 14;
      g.fillStyle = colors[i]; g.beginPath(); g.arc(t.x, t.y, 26, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
      g.fillStyle = '#162336'; g.beginPath(); g.arc(t.x, t.y, 21, 0, Math.PI * 2); g.fill();
      g.strokeStyle = colors[i]; g.lineWidth = 2;
      g.beginPath(); g.arc(t.x, t.y, 16, 0, Math.PI * 2); g.stroke();
      g.fillStyle = '#ffffff'; g.font = 'bold 20px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText(String(t.id), t.x, t.y + 1);
    });
  }
  function resize() {
    const size = arena.getBoundingClientRect().width || 360;
    const pixels = Math.max(1, Math.round(size * pixelRatio));
    if (canvas.width !== pixels || canvas.height !== pixels) { canvas.width = pixels; canvas.height = pixels; }
    render();
  }
  function dispatch(action) {
    if (disposed || !action || typeof action.type !== 'string') return;
    if (action.type === 'RESTART') { reset(); render(); return; }
    if (action.type === 'START') {
      if (phase === 'ready') { phase = 'playing'; render(); }
      return;
    }
    if (action.type === 'SET_VISIBILITY') {
      paused = Boolean(action.hidden === undefined ? action.paused : action.hidden); render(); return;
    }
    if (phase !== 'playing' || paused) return;
    if (action.type === 'FIXED_STEP' || action.type === 'STEP') {
      targets.forEach(t => {
        if (!t.alive) return;
        t.x += t.vx / 60;
        if (t.x > 328) { t.x = 656 - t.x; t.vx = -Math.abs(t.vx); }
        if (t.x < 32) { t.x = 64 - t.x; t.vx = Math.abs(t.vx); }
      });
      simulationTick++; render(); return;
    }
    if (action.type === 'FIRE_TARGET') {
      const t = targets.find(t => t.id === Number(action.id) && t.alive);
      if (t) dispatch({type: 'FIRE_AT', x: t.x, y: t.y});
      return;
    }
    if (action.type !== 'FIRE_AT' || !Number.isFinite(action.x) || !Number.isFinite(action.y)) return;
    if (action.x < 0 || action.x > 360 || action.y < 0 || action.y > 360) return;
    const hit = targets.find(t => t.alive && (action.x - t.x) ** 2 + (action.y - t.y) ** 2 <= t.radius ** 2);
    if (hit) {
      hit.alive = false; score++;
      if (ctx.audio) { try { ctx.audio.tone(660, 0.12); } catch (_) {} }
    } else misses++;
    if (score === 3) phase = 'won';
    else if (misses === 3) phase = 'lost';
    render();
  }
  reset(); resize();
  ctx.input.on(arena, 'pointerdown', event => {
    if (event.button !== undefined && event.button !== 0) return;
    event.preventDefault();
    const rect = arena.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    arena.focus({preventScroll: true});
    dispatch({type: 'FIRE_AT', x: (event.clientX - rect.left) * 360 / rect.width, y: (event.clientY - rect.top) * 360 / rect.height});
  });
  ctx.input.key((key, event) => {
    if (event.repeat || !['1', '2', '3'].includes(key)) return;
    event.preventDefault(); dispatch({type: 'FIRE_TARGET', id: Number(key)});
  });
  ctx.resize((width, height, dpr) => { pixelRatio = Number.isFinite(dpr) && dpr > 0 ? dpr : 1; resize(); });
  if (ctx.clock) ctx.clock.fixedStep(() => dispatch({type: 'FIXED_STEP'}), 1 / 60);
  return {
    snapshot() { return {phase, score, misses, attemptsRemaining: 3 - misses, targets: targets.map(t => ({...t})), paused, simulationTick}; },
    dispatch,
    pause(hidden) { if (!disposed) { paused = Boolean(hidden); render(); } },
    dispose() { disposed = true; }
  };
}
