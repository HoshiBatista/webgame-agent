function createGame(ctx) {
  const root = ctx.root;
  root.innerHTML = '<section class="courier-game"><header class="courier-header"><div><p class="eyebrow">ЭКСПРЕСС · ГОРОДСКОЙ МАРШРУТ</p><h1>Прыжок курьера</h1></div><span class="route-badge">01 → 03</span></header><p class="rules">Перепрыгните три барьера и доставьте посылку. <strong>Пробел / ↑</strong> или кнопка «Прыжок».</p><div class="stats"><span class="distance">Дистанция <strong>0%</strong></span><span class="barriers">Барьеры <strong>0/3</strong></span></div><div class="progress-track"><div class="progress-fill"></div></div><canvas class="courier-scene" width="720" height="400" role="img" aria-label="Курьер, три дорожных барьера и финиш на одной городской улице"></canvas><div class="message" role="status" aria-live="polite"></div><button class="jump-button" type="button" data-testid="jump" aria-label="Прыжок">Прыжок <span aria-hidden="true">↑</span></button><p class="footer-note">Одна посылка · три барьера · шесть секунд пути</p></section>';
  const canvas = root.querySelector('canvas');
  const g = canvas.getContext('2d');
  const message = root.querySelector('.message');
  const distance = root.querySelector('.distance strong');
  const barriers = root.querySelector('.barriers strong');
  const fill = root.querySelector('.progress-fill');
  const jump = root.querySelector('.jump-button');
  const obstacles = [210, 370, 530].map(x => ({ x, width: 20, height: 36 }));
  const dt = 1 / 120;
  let phase, player, ticks, paused = false, passedObstacles, progress;
  let disposed = false;
  function reset() {
    phase = 'ready';
    player = { x: 60, bottomY: 310, vy: 0, grounded: true };
    ticks = 0;
    progress = 0;
    passedObstacles = 0;
  }
  function rect(x, y, w, h, color) {
    g.fillStyle = color;
    g.fillRect(x, y, w, h);
  }
  function label(text, x, y, color, size, align) {
    g.fillStyle = color;
    g.font = 'bold ' + size + 'px system-ui, sans-serif';
    g.textAlign = align || 'left';
    g.fillText(text, x, y);
  }
  function draw() {
    g.setTransform(canvas.width / 720, 0, 0, canvas.height / 400, 0, 0);
    rect(0, 0, 720, 400, '#eaf7fc');
    g.fillStyle = '#fff4c4';
    g.beginPath(); g.arc(603, 66, 30, 0, Math.PI * 2); g.fill();
    const buildings = [[0,142,70],[82,109,80],[176,161,62],[249,126,96],[357,92,70],[440,152,72],[525,119,66],[607,143,113]];
    buildings.forEach((b, i) => {
      rect(b[0], b[1], b[2], 282 - b[1], i % 2 ? '#cfdee7' : '#dbe7ed');
      for (let x = b[0] + 12; x < b[0] + b[2] - 8; x += 23) {
        for (let y = b[1] + 17; y < 260; y += 31) rect(x, y, 8, 12, '#b7ceda');
      }
    });
    rect(0, 279, 720, 25, '#a8cbbd');
    rect(0, 304, 720, 6, '#f7fbfc');
    rect(0, 310, 720, 90, '#293e50');
    rect(0, 310, 720, 4, '#172c3c');
    for (let x = 15; x < 720; x += 56) rect(x, 360, 28, 3, '#536675');
    rect(654, 195, 5, 115, '#187557');
    rect(659, 197, 54, 32, '#237e5e');
    label('ФИНИШ', 686, 217, '#ffffff', 10, 'center');
    for (let row = 0; row < 3; row++) for (let col = 0; col < 2; col++) rect(652 + col * 8, 313 + row * 8, 8, 8, (row + col) % 2 ? '#293e50' : '#eaf7fc');
    obstacles.forEach((o, i) => {
      rect(o.x - 4, 306, 28, 4, '#142c3a');
      rect(o.x, 274, 20, 36, '#ef7e39');
      rect(o.x + 2, 279, 16, 5, '#fff4cf');
      rect(o.x + 2, 292, 16, 5, '#fff4cf');
      label(String(i + 1).padStart(2, '0'), o.x + 10, 337, '#b2c6d2', 11, 'center');
    });
    const x = player.x, y = player.bottomY;
    g.fillStyle = 'rgba(14,35,48,.18)';
    g.beginPath(); g.ellipse(x, 310, 17, 3, 0, 0, Math.PI * 2); g.fill();
    rect(x - 12, y - 22, 24, 17, '#2563b5');
    rect(x - 7, y - 32, 15, 11, '#eebc8d');
    rect(x - 9, y - 34, 18, 5, '#214d8c');
    rect(x + 5, y - 30, 9, 3, '#214d8c');
    rect(x + 5, y - 23, 13, 13, '#f3c644');
    rect(x + 10, y - 23, 3, 5, '#fff0a7');
    rect(x - 10, y - 5, 8, 5, '#17344e');
    rect(x + 4, y - 5, 9, 5, '#17344e');
    label('ДОСТАВКА № 042', 23, 34, '#48687b', 12);
    label('Короткий путь домой', 23, 56, '#708c9d', 11);
    if (phase === 'won' || phase === 'lost') {
      rect(154, 74, 412, 62, phase === 'won' ? '#176347' : '#813c32');
      label(phase === 'won' ? 'Доставка выполнена!' : 'Посылка не доставлена', 360, 112, '#ffffff', 24, 'center');
    }
  }
  function render() {
    distance.textContent = Math.floor(progress * 100) + '%';
    barriers.textContent = passedObstacles + '/3';
    fill.style.width = (progress * 100) + '%';
    const text = phase === 'ready' ? 'Готовы? Нажмите «Начать» над игрой.' : phase === 'won' ? 'Доставка выполнена! 100% пути · 3/3 барьера. Можно начать заново.' : phase === 'lost' ? 'Посылка не доставлена. Нажмите «Перезапуск» и попробуйте снова.' : paused ? 'Пауза — маршрут подождёт.' : 'Курьер в пути! Прыгайте чуть раньше барьера.';
    if (message.textContent !== text) message.textContent = text;
    jump.setAttribute('aria-disabled', String(phase !== 'playing' || paused));
    draw();
  }
  function step() {
    if (phase !== 'playing' || paused) return;
    ticks++;
    player.x = 60 + ticks * 100 / 120;
    player.bottomY += player.vy * dt + 600 * dt * dt;
    player.vy += 1200 * dt;
    if (player.bottomY >= 310) {
      player.bottomY = 310;
      player.vy = 0;
      player.grounded = true;
    }
    progress = Math.max(0, Math.min(1, (player.x - 60) / 600));
    passedObstacles = obstacles.filter(o => player.x - 12 >= o.x + o.width).length;
    for (const o of obstacles) {
      if (player.x + 12 > o.x && player.x - 12 < o.x + o.width && player.bottomY > 310 - o.height && player.bottomY - 32 < 310) {
        phase = 'lost';
        break;
      }
    }
    if (phase === 'playing' && player.x >= 660) phase = 'won';
  }
  function dispatch(action) {
    if (disposed || !action) return;
    const type = typeof action === 'string' ? action : action.type;
    if (type === 'START' && phase === 'ready') phase = 'playing';
    else if (type === 'RESTART') reset();
    else if (type === 'JUMP' && phase === 'playing' && !paused && player.grounded) {
      player.vy = -420;
      player.grounded = false;
    } else if (type === 'TICK' || type === 'STEP') step();
    else if (type === 'SET_VISIBILITY') paused = typeof action.hidden === 'boolean' ? action.hidden : action.visible === false;
    render();
  }
  ctx.input.on(jump, 'click', () => dispatch({ type: 'JUMP' }));
  ctx.input.key((key, event) => {
    if (key !== 'Space' && key !== ' ' && key !== 'Spacebar' && key !== 'ArrowUp') return;
    if (event) event.preventDefault();
    if (event && event.repeat) return;
    dispatch({ type: 'JUMP' });
  });
  reset();
  // The runtime owns the fixed-step accumulator and visibility time baseline.
  ctx.clock.fixedStep(() => {
    if (disposed || paused || phase !== 'playing') return;
    step();
    render();
  }, dt);
  ctx.resize((width, height, dpr) => {
    const w = Math.max(1, Math.min(720, width || 720));
    const scale = Math.max(1, Math.min(3, dpr || 1));
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(w * 400 / 720 * scale);
    draw();
  });
  render();
  return {
    snapshot() {
      return { phase, player: { ...player }, obstacles: obstacles.map(o => ({ ...o })), ticks, elapsed: ticks / 120, progress, passedObstacles, paused };
    },
    dispatch,
    pause(hidden) { paused = !!hidden; render(); },
    dispose() { disposed = true; }
  };
}
