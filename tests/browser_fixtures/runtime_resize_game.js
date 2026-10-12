// Authored regression: a percentage-height Grid/Canvas layout like an RTS.
function createGame(ctx) {
  ctx.root.dataset.layout = 'viewport';
  let phase = 'ready', moves = 0;
  ctx.root.innerHTML = '<div class="resize-shell" style="height:100%;display:grid;grid-template-rows:48px minmax(0,1fr) 80px"><div>Resources</div><div class="resize-map" style="min-height:0;overflow:hidden"><canvas style="width:100%;height:100%" aria-label="Resize map"></canvas></div><button id="resize-move">Move 0</button></div>';
  const canvas = ctx.root.querySelector('canvas'), button = ctx.root.querySelector('button');
  function render() {
    const pen = canvas.getContext('2d');
    pen.fillStyle = '#15352a'; pen.fillRect(0, 0, canvas.width, canvas.height);
    pen.fillStyle = '#e9bf65'; pen.fillRect(20 + moves * 15, 20, 60, 60);
    button.textContent = 'Move ' + moves;
  }
  ctx.resize((width, height, dpr) => {
    const box = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.round(box.width * dpr);
    canvas.height = Math.round(box.height * dpr);
    render();
  });
  ctx.input.on(button, 'click', () => { moves++; render(); });
  return {snapshot: () => ({phase, moves}), dispatch(action) { if (action.type === 'START') phase = 'playing'; }};
}
