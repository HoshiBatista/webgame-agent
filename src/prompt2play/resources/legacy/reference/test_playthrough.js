'use strict';
// Balance smoke test: uses only act()/choose() to change the game.
// The route planner can read the full map; this is not a blind/FOV player test.
const assert = require('node:assert/strict');
const { AshenEngine } = require('./engine.js');
const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];
const distance = (a, b) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);

function path(game, target) {
  const s = game.state, p = s.player;
  const queue = [{ x: p.x, y: p.y, first: null }], seen = new Set([p.x + ',' + p.y]);
  for (let i = 0; i < queue.length; i++) {
    const c = queue[i];
    if (c.x === target.x && c.y === target.y) return c.first;
    for (const [dx, dy] of DIRS) {
      const x = c.x + dx, y = c.y + dy, key = x + ',' + y;
      const occupied = s.enemies.some(e => e.x === x && e.y === y && (x !== target.x || y !== target.y));
      if (!game._walkable(x, y) || seen.has(key) || occupied) continue;
      seen.add(key); queue.push({ x, y, first: c.first || { type: 'move', dx, dy } });
    }
  }
  return null;
}

function play(seed, classId) {
  const game = new AshenEngine({ seed, classId }), trace = [], actions = {};
  const act = action => {
    const ok = game.act(action);
    if (ok) { trace.push(action); actions[action.type] = (actions[action.type] || 0) + 1; }
    return ok;
  };
  for (let step = 0; step < 6000 && ['playing', 'choice'].includes(game.state.status); step++) {
    const s = game.state, p = s.player;
    if (s.status === 'choice') {
      const order = ['armor', 'vampire', 'strength', 'vitality', 'sorcery', 'focus', 'evasion', 'precision'];
      const id = [...s.choices].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))[0].id;
      assert(game.choose(id)); trace.push({ type: 'choose', id }); continue;
    }
    const visible = s.enemies.filter(e => s.visible[e.y][e.x]);
    const aoe = s.enemies.filter(e => game._line(p.x, p.y, e.x, e.y) && (p.x - e.x) ** 2 + (p.y - e.y) ** 2 <= 6.25);
    const threats = visible.filter(e => (e.armed && Math.abs(e.x - p.x) <= 1 && Math.abs(e.y - p.y) <= 1) || (e.intent === 'nova' && (e.x - p.x) ** 2 + (e.y - p.y) ** 2 <= 6.25));
    if (threats.length) {
      const moves = DIRS.map(([dx, dy]) => ({ x: p.x + dx, y: p.y + dy, dx, dy }))
        .filter(c => game._walkable(c.x, c.y) && !s.enemies.some(e => e.x === c.x && e.y === c.y));
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
    if (!s.enemies.some(e => distance(e, p) <= 8) && (p.hp < p.maxHp || p.mana < p.maxMana)) {
      act({ type: 'wait' }); continue;
    }
    const targets = [...s.items, ...s.features.filter(f => !f.used && (f.type !== 'fountain' || p.hp < p.maxHp * .8 || p.mana < p.maxMana / 2)), ...s.enemies];
    targets.sort((a, b) => distance(a, p) - distance(b, p));
    let moved = false;
    for (const target of targets) {
      if (target.x === p.x && target.y === p.y && act({ type: 'interact' })) { moved = true; break; }
      const move = path(game, target); if (move && act(move)) { moved = true; break; }
    }
    if (moved) continue;
    if (p.x === s.stairs.x && p.y === s.stairs.y) { act({ type: 'interact' }); continue; }
    act(path(game, s.stairs) || { type: 'wait' });
  }
  const s = game.state;
  assert.equal(s.status, 'won', `${classId} failed: floor ${s.floor}, HP ${s.player.hp}`);
  assert.equal(s.floor, 5); assert(s.bossDefeated); assert(s.stats.spells > 0);
  assert(s.stats.chests > 0); assert(actions.wait > 0);
  // Replay the actual legal action sequence from a fresh, unmodified engine.
  const replay = new AshenEngine({ seed, classId });
  for (const action of trace) assert(action.type === 'choose' ? replay.choose(action.id) : replay.act(action));
  assert.equal(replay.state.status, 'won');
  assert.deepEqual(replay.state.player, s.player);
  assert.deepEqual(replay.state.stats, s.stats);
  console.log(JSON.stringify({ seed, classId, status: s.status, turns: s.turn, level: s.player.level, hp: s.player.hp, maxHp: s.player.maxHp, kills: s.stats.kills, spells: s.stats.spells, potionsUsed: s.stats.potionsUsed, chests: s.stats.chests, rests: actions.wait }));
}

for (const classId of ['warden', 'rogue', 'mage']) play('embers', classId);
console.log('PASS: all three classes completed five floors and the final exit via normal actions; full action replays matched.');
