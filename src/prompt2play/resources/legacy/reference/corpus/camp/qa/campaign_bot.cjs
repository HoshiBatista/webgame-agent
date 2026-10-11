'use strict';
// A deterministic, legal-action player used only for progression evidence.
// The route planner sees the entire map. This is not a blind human playtest.
const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];
const distance = (a, b) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
function path(game, target) {
  const s = game.state, p = s.player, queue = [{ x: p.x, y: p.y, first: null }], seen = new Set([p.x + ',' + p.y]);
  for (let i = 0; i < queue.length; i++) {
    const c = queue[i];
    if (c.x === target.x && c.y === target.y) return c.first;
    for (const [dx, dy] of DIRS) {
      const x = c.x + dx, y = c.y + dy, key = x + ',' + y;
      if (!game._walkable(x, y) || seen.has(key) || s.enemies.some(e => e.x === x && e.y === y && (x !== target.x || y !== target.y))) continue;
      seen.add(key); queue.push({ x, y, first: c.first || { type: 'move', dx, dy } });
    }
  }
  return null;
}
function driveRun(campaign, { stopWhen = null, maxSteps = 6000, trace = [] } = {}) {
  let retreat = false, steps = 0, targetId = null;
  const act = action => {
    const ok = campaign.act(action);
    if (ok) trace.push({ method: 'act', action: { ...action } });
    return ok;
  };
  for (; steps < maxSteps && campaign.mode === 'run'; steps++) {
    const game = campaign.engine, s = game.state, p = s.player;
    if (s.status === 'choice') {
      const order = ['armor', 'vampire', 'strength', 'vitality', 'sorcery', 'focus', 'evasion', 'precision'];
      const id = [...s.choices].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))[0].id;
      if (!campaign.choose(id)) throw Error('Bot choice rejected');
      trace.push({ method: 'choose', id }); continue;
    }
    if (stopWhen && stopWhen(campaign)) retreat = true;
    if (retreat && campaign.canReturn().ok) {
      if (!campaign.returnToCamp()) throw Error('Bot return rejected');
      trace.push({ method: 'returnToCamp' }); break;
    }
    const visible = s.enemies.filter(e => s.visible[e.y][e.x]);
    const aoe = s.enemies.filter(e => game._line(p.x, p.y, e.x, e.y) && (p.x - e.x) ** 2 + (p.y - e.y) ** 2 <= 6.25);
    const threats = visible.filter(e => (e.armed && Math.abs(e.x - p.x) <= 1 && Math.abs(e.y - p.y) <= 1) || (e.intent === 'nova' && (e.x - p.x) ** 2 + (e.y - p.y) ** 2 <= 6.25));
    if (threats.length) {
      const moves = DIRS.map(([dx, dy]) => ({ x: p.x + dx, y: p.y + dy, dx, dy })).filter(c => game._walkable(c.x, c.y) && !s.enemies.some(e => e.x === c.x && e.y === c.y));
      moves.sort((a, b) => Math.min(...threats.map(e => distance(b, e))) - Math.min(...threats.map(e => distance(a, e))));
      if (moves.length) { act({ type: 'move', dx: moves[0].dx, dy: moves[0].dy }); continue; }
    }
    if (p.hp < p.maxHp * .6 && p.potions > 0) { act({ type: 'potion' }); continue; }
    if (aoe.length >= 2 && p.mana >= 5) { act({ type: 'cast', skill: 'nova' }); continue; }
    if (visible.length) {
      visible.sort((a, b) => distance(a, p) - distance(b, p) || a.hp - b.hp);
      const adjacent = visible.filter(e => distance(e, p) === 1).sort((a, b) => a.hp - b.hp);
      if (p.mana >= 3) {
        const target = [...visible].sort((a, b) => (a.hp <= 9 + p.spellPower ? -10 : 0) - (b.hp <= 9 + p.spellPower ? -10 : 0) + distance(a, p) - distance(b, p))[0];
        if (act({ type: 'cast', skill: 'bolt', x: target.x, y: target.y })) continue;
      }
      if (adjacent.length) { act({ type: 'move', dx: adjacent[0].x - p.x, dy: adjacent[0].y - p.y }); continue; }
      const move = path(game, visible[0]); if (move) { act(move); continue; }
    }
    if (!s.enemies.some(e => distance(e, p) <= 8) && (p.hp < p.maxHp || p.mana < p.maxMana)) { act({ type: 'wait' }); continue; }
    if (retreat) { if (!act(path(game, s.entry) || { type: 'wait' })) throw Error('Bot cannot retreat'); continue; }
    // Keep an exploration target until collected. Re-selecting Manhattan-nearest
    // loot every step can oscillate on opposite sides of a long wall.
    const targets = [...s.items, ...s.features.filter(f => !f.used && (f.type !== 'fountain' || p.hp < p.maxHp * .8 || p.mana < p.maxMana / 2)), ...s.enemies].sort((a, b) => (a.id === targetId ? -1 : b.id === targetId ? 1 : distance(a, p) - distance(b, p)));
    let moved = false;
    for (const target of targets) {
      if (target.x === p.x && target.y === p.y && act({ type: 'interact' })) { moved = true; break; }
      const move = path(game, target); if (move && act(move)) { targetId = target.id; moved = true; break; }
    }
    if (moved) continue;
    if (p.x === s.stairs.x && p.y === s.stairs.y) { act({ type: 'interact' }); continue; }
    act(path(game, s.stairs) || { type: 'wait' });
  }
  return { steps, mode: campaign.mode, outcome: campaign.lastRun?.outcome || null, trace };
}
module.exports = { driveRun, path };
