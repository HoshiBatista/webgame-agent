/* Reviewed turn-based fixture; no clock, audio or persistence obligation. */
function createGame(ctx) {
  let phase = "ready", moves = 0, cells = [false, false, false];
  ctx.root.innerHTML = '<article><h1>Beacon Grid</h1><p>Light every beacon. Click or tap a beacon, or press 1, 2, 3.</p><div id="beacons"></div><p id="progress"></p></article>';
  const board = ctx.root.querySelector("#beacons"), progress = ctx.root.querySelector("#progress");
  const buttons = cells.map((_, index) => {
    const button = document.createElement("button"); button.id = `move-${index}`; button.style.margin = ".5rem"; button.style.minHeight = "80px";
    board.append(button); ctx.input.on(button, "click", () => dispatch({type: "MOVE", index})); return button;
  });
  function render() {
    buttons.forEach((button, index) => { button.textContent = `Beacon ${index + 1}: ${cells[index] ? "ON" : "OFF"}`; button.style.background = cells[index] ? "#227a58" : "#263950"; });
    progress.textContent = phase === "won" ? `All lit in ${moves} moves! Restart to play again.` : `${cells.filter(Boolean).length}/3 lit · ${phase}`;
  }
  function dispatch(action) {
    if (action.type === "START" && phase === "ready") phase = "playing";
    if (action.type === "MOVE" && phase === "playing" && Number.isInteger(action.index) && action.index >= 0 && action.index < cells.length) {
      cells[action.index] = !cells[action.index]; moves++;
      if (cells.every(Boolean)) { phase = "won"; if (ctx.audio) ctx.audio.tone(660, .12); }
      if (ctx.storage) ctx.storage.save({version: 1, cells, moves});
    }
    render();
  }
  ctx.input.key(key => { if (["1", "2", "3"].includes(key)) dispatch({type: "MOVE", index: Number(key) - 1}); });
  render();
  const snapshot = () => ({phase, cells: [...cells], moves});
  const api = {snapshot, dispatch};
  if (ctx.storage) {
    api.exportSave = () => ctx.storage.export({version: 1, ...snapshot()});
    api.importSave = text => {
      let data;
      try { data = ctx.storage.import(text); } catch (_) { return false; }
      if (!data || data.version !== 1 || !["ready", "playing", "won"].includes(data.phase) || !Array.isArray(data.cells) || data.cells.length !== 3 || data.cells.some(value => typeof value !== "boolean") || !Number.isInteger(data.moves) || data.moves < 0 || (data.phase === "won") !== data.cells.every(Boolean)) return false;
      phase = data.phase; cells = [...data.cells]; moves = data.moves; render(); return true;
    };
  }
  return api;
}
