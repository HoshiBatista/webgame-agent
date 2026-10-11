function createGame(ctx) {
  const root = ctx.root;
  root.innerHTML = '<section class="targets-game"><header><div class="eyebrow">ТОЧНОСТЬ · 01</div><h1>Мишени</h1><p class="subtitle">Три цели. Три права на ошибку.</p></header><div class="scoreboard" role="status" aria-live="polite" aria-atomic="true"><div>ПОПАДАНИЯ<strong class="score">0 / 3</strong></div><div>ПОПЫТКИ<strong class="attempts">3 / 3</strong></div></div><div class="field"><canvas aria-label="Три движущиеся мишени на отдельных дорожках"></canvas><div class="target-layer"></div></div><p class="result" role="status" aria-live="polite"></p><p class="instructions">Нажмите Start. Стреляйте кликом или касанием по кругу.<br>Клавиши <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> — прицельный выстрел. Три промаха — конец игры.</p><footer>ПОРАЗИТЕ ВСЕ ТРИ МИШЕНИ</footer></section>';
  const field = root.querySelector('.field');
  const canvas = root.querySelector('canvas');
  const layer = root.querySelector('.target-layer');
  const scoreText = root.querySelector('.score');
  const attemptsText = root.querySelector('.attempts');
  const result = root.querySelector('.result');
  const g = canvas.getContext('2d');
  let phase = 'ready', misses = 0, score = 0, paused = false, simulationTicks = 0;
  let disposed = false;
  let targets;
  const areas = new Map();
  function reset() {
    phase = 'ready'; misses = 0; score = 0; simulationTicks = 0;
    targets = [80, 180, 280].map((x, i) => ({ id: i + 1, x, y: 90 + 120 * i, radius: 32, vx: i === 1 ? -18 : 18, alive: true }));
  }
  function paint() {
    if (disposed) return;
    scoreText.textContent = score + ' / 3';
    attemptsText.textContent = (3 - misses) + ' / 3';
    const message = phase === 'won' ? 'Победа! Все три мишени поражены.' : phase === 'lost' ? 'Игра окончена. Попробуйте еще раз — Restart.' : phase === 'ready' ? 'Готовы? Нажмите Start.' : paused ? 'Пауза' : 'Цельтесь в круги. Попадания не расходуют попытки.';
    if (result.textContent !== message) result.textContent = message;
    result.dataset.phase = phase;
    g.setTransform(canvas.width / 360, 0, 0, canvas.height / 420, 0, 0);
    g.fillStyle = '#101f34'; g.fillRect(0, 0, 360, 420);
    for (let i = 0; i < 3; i++) {
      const y = 90 + i * 120;
      g.fillStyle = i % 2 ? '#14263e' : '#122239'; g.fillRect(0, y - 49, 360, 98);
      g.strokeStyle = '#30435a'; g.lineWidth = 1;
      g.beginPath(); g.moveTo(18, y); g.lineTo(342, y); g.stroke();
      g.fillStyle = '#718398'; g.font = '10px sans-serif'; g.textAlign = 'left';
      g.fillText('0' + (i + 1), 17, y - 34);
    }
    targets.forEach(t => {
      let area = areas.get(t.id);
      if (!t.alive) { if (area) { area.remove(); areas.delete(t.id); } return; }
      if (!area) {
        area = document.createElement('div');
        area.className = 'target-area';
        area.dataset.testid = 'target-' + t.id;
        area.setAttribute('aria-label', 'Мишень ' + t.id + ', клавиша ' + t.id);
        layer.appendChild(area); areas.set(t.id, area);
      }
      area.style.left = ((t.x - t.radius) / 360 * 100) + '%';
      area.style.top = ((t.y - t.radius) / 420 * 100) + '%';
      area.style.width = (64 / 360 * 100) + '%';
      area.style.height = (64 / 420 * 100) + '%';
      g.shadowColor = '#0006'; g.shadowBlur = 10; g.shadowOffsetY = 4;
      g.fillStyle = '#f78070'; g.beginPath(); g.arc(t.x, t.y, 32, 0, Math.PI * 2); g.fill();
      g.shadowBlur = 0; g.shadowOffsetY = 0;
      g.strokeStyle = '#ffedcf'; g.lineWidth = 3;
      g.beginPath(); g.arc(t.x, t.y, 24, 0, Math.PI * 2); g.stroke();
      g.fillStyle = '#ffedcf'; g.beginPath(); g.arc(t.x, t.y, 16, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#16243a'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.font = 'bold 21px sans-serif';
      g.fillText(String(t.id), t.x, t.y + 1); g.textBaseline = 'alphabetic';
    });
  }
  function shoot(x, y) {
    if (phase !== 'playing' || paused || !Number.isFinite(x) || !Number.isFinite(y)) return;
    const target = targets.find(t => t.alive && (t.x-x)*(t.x-x)+(t.y-y)*(t.y-y) <= t.radius*t.radius);
    if (target) {
      target.alive = false; score++;
      if (ctx.audio) { try { const played = ctx.audio.tone(880, 0.12); if (played && played.catch) played.catch(() => {}); } catch (_) {} }
    } else misses++;
    if (score === 3) phase = 'won';
    else if (misses === 3) phase = 'lost';
  }
  function dispatch(action) {
    if (disposed || !action) return;
    switch (action.type) {
      case 'START': if (phase === 'ready') phase = 'playing'; break;
      case 'RESTART': reset(); break;
      case 'SET_HIDDEN': paused = !!action.hidden; break;
      case 'SHOOT': shoot(action.x, action.y); break;
      case 'SHOOT_TARGET': {
        const t = targets.find(t => t.id === Number(action.id) && t.alive);
        if (t) shoot(t.x, t.y);
        break;
      }
      case 'STEP':
      case 'FIXED_STEP':
        if (phase === 'playing' && !paused) {
          targets.forEach(t => {
            if (!t.alive) return;
            t.x += t.vx / 60;
            if (t.x > 320) { t.x = 640 - t.x; t.vx = -Math.abs(t.vx); }
            if (t.x < 40) { t.x = 80 - t.x; t.vx = Math.abs(t.vx); }
          });
          simulationTicks++;
        }
        break;
    }
    paint();
  }
  function pointer(event) {
    if (event.isPrimary === false || event.button !== 0) return;
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    dispatch({ type: 'SHOOT', x: (event.clientX - rect.left) * 360 / rect.width, y: (event.clientY - rect.top) * 420 / rect.height });
  }
  ctx.input.on(field, 'pointerdown', pointer);
  ctx.input.key((key, event) => {
    if (event.repeat || !/^[123]$/.test(key)) return;
    event.preventDefault();
    dispatch({ type: 'SHOOT_TARGET', id: Number(key) });
  });
  reset();
  canvas.width = 720; canvas.height = 840;
  ctx.resize((width, height, dpr) => {
    const rect = canvas.getBoundingClientRect();
    const ratio = Number.isFinite(dpr) && dpr > 0 ? dpr : 1;
    canvas.width = Math.max(1, Math.round(rect.width * ratio));
    canvas.height = Math.max(1, Math.round(rect.height * ratio));
    paint();
  });
  if (ctx.clock) ctx.clock.fixedStep(() => dispatch({ type: 'FIXED_STEP' }), 1 / 60);
  paint();
  return {
    snapshot() { return { phase, score, misses, attemptsLeft: 3 - misses, paused, targets: targets.map(t => ({ ...t })), simulationTicks }; },
    dispatch,
    pause(hidden) { dispatch({ type: 'SET_HIDDEN', hidden }); },
    dispose() { disposed = true; }
  };
}
