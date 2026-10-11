/* Reviewed runtime fixture; not a live-generated result. */
function createGame(ctx) {
  let phase = "ready", position = 0, elapsed = 0;
  ctx.root.innerHTML = '<article><h1>Orbit Courier</h1><p>Move right four times: ArrowRight or tap the track. Reach the green beacon.</p><p id="progress"></p><canvas id="track" width="640" height="280" aria-label="Courier track"></canvas></article>';
  const canvas = ctx.root.querySelector("canvas"), progress = ctx.root.querySelector("#progress"), pen = canvas.getContext("2d");
  function render() {
    progress.textContent = phase === "won" ? "Delivered! Press Restart to fly again." : `Beacons ${position}/4 · ${phase}`;
    pen.fillStyle = "#172439"; pen.fillRect(0, 0, canvas.width, canvas.height);
    pen.fillStyle = "#43d39e"; pen.fillRect(canvas.width - 65, 100, 32, 70);
    pen.strokeStyle = "#526d96"; pen.beginPath(); pen.moveTo(20, 135); pen.lineTo(canvas.width - 40, 135); pen.stroke();
    pen.fillStyle = "#fed169"; pen.beginPath(); pen.arc(30 + position * (canvas.width - 100) / 4, 135 + Math.sin(elapsed * 3) * 3, 18, 0, Math.PI * 2); pen.fill();
  }
  function dispatch(action) {
    if (action.type === "START" && phase === "ready") phase = "playing";
    if (action.type === "MOVE" && phase === "playing") { position++; if (position >= 4) phase = "won"; }
    if (action.type === "STEP" && phase === "playing") elapsed += 1 / 60;
    render();
  }
  ctx.input.key(key => { if (key === "ArrowRight" || key === " ") dispatch({type: "MOVE"}); });
  ctx.input.pointer(canvas, () => dispatch({type: "MOVE"}));
  ctx.resize(width => { canvas.width = Math.max(240, Math.min(640, width)); canvas.height = 280; render(); });
  ctx.clock.fixedStep(dt => { if (phase === "playing") { elapsed += dt; render(); } });
  render();
  return {snapshot: () => ({phase, position, elapsed: Math.round(elapsed * 60) / 60}), dispatch};
}
