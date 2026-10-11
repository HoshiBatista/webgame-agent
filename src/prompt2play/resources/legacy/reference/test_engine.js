'use strict';
const assert = require('node:assert/strict');
const { AshenEngine, ASHEN_CLASSES } = require('./engine.js');

function arena(classId = 'warden') {
  const game = new AshenEngine({ seed: 'rules-fixture', classId });
  const s = game.state;
  s.tiles = Array.from({ length: 29 }, (_, y) => Array.from({ length: 41 }, (_, x) => x && y && x < 40 && y < 28 ? 1 : 0));
  s.stairs = { x: 39, y: 27 }; s.tiles[27][39] = 2;
  s.enemies = []; s.items = []; s.features = []; s.events = [];
  s.player.x = 10; s.player.y = 10;
  game._updateFov();
  return game;
}

// Procedural output must remain connected, reproducible, and serializable.
for (let seed = 0; seed < 60; seed++) {
  const game = new AshenEngine({ seed, classId: ASHEN_CLASSES[seed % 3].id });
  assert(game.state.rooms.length >= 3);
  for (let floor = 1; floor <= 5; floor++) {
    const s = game.state, d = game._distances(s.player.x, s.player.y);
    s.tiles.forEach((row, y) => row.forEach((tile, x) => { if (tile) assert(d[y][x] >= 0); }));
    const objects = [s.player, s.stairs, ...s.enemies, ...s.features, ...s.items];
    assert.equal(new Set(objects.map(o => o.x + ',' + o.y)).size, objects.length);
    assert.equal(s.enemies.filter(e => e.type === 'boss').length, floor === 5 ? 1 : 0);
    assert(s.visible[s.player.y][s.player.x]);
    assert.deepEqual(AshenEngine.fromSave(game.serialize()).state.tiles, s.tiles);
    if (floor < 5) { s.player.x = s.stairs.x; s.player.y = s.stairs.y; assert(game.act({ type: 'interact' })); }
  }
}

// Saving preserves the random stream as well as the state of combat.
{
  const a = arena(), enemy = a._makeEnemy('sentinel', 11, 10);
  enemy.hp = enemy.maxHp = 400; a.state.enemies.push(enemy);
  const b = AshenEngine.fromSave(a.serialize());
  for (let i = 0; i < 8; i++) {
    assert.equal(a.act({ type: 'move', dx: 1, dy: 0 }), b.act({ type: 'move', dx: 1, dy: 0 }));
    assert.equal(a.serialize(), b.serialize());
  }
}

// Invalid actions consume neither turns nor mana; walls occlude spells.
{
  const game = arena('mage'), s = game.state;
  const enemy = game._makeEnemy('sentinel', 13, 10); enemy.hp = enemy.maxHp = 40; enemy.armor = 100;
  s.enemies.push(enemy); s.tiles[10][11] = 0; game._updateFov();
  const mana = s.player.mana;
  assert.equal(game.act({ type: 'cast', skill: 'bolt', x: 13, y: 10 }), false);
  assert.equal(game.act({ type: 'move', dx: 1, dy: 1 }), false);
  assert.equal(game.act({ type: 'move', dx: 1, dy: 0 }), false);
  assert.equal(s.turn, 0); assert.equal(s.player.mana, mana);
  s.tiles[10][11] = 1; game._updateFov();
  assert(game.act({ type: 'cast', skill: 'bolt', x: 13, y: 10 }));
  assert(enemy.hp < 40); assert.equal(s.player.mana, mana - 3);
}

// FOV and enemy LOS must agree, including Bresenham tie cases and corners.
{
  const game = arena(), s = game.state;
  s.player.x = 2; s.player.y = 2; s.tiles[2][3] = 0;
  const archer = game._makeEnemy('archer', 4, 3); archer.actions = 1;
  s.enemies = [archer]; game._updateFov();
  assert.equal(game._line(2, 2, 4, 3), false);
  assert.equal(game._line(4, 3, 2, 2), false);
  assert.equal(s.visible[3][4], false);
  const hp = s.player.hp;
  assert(game.act({ type: 'wait' }));
  assert.equal(s.player.hp, hp);
  assert(!s.events.some(event => event.type === 'cast' && event.text === 'arrow'));
  s.tiles[3][2] = 0;
  assert.equal(game._line(2, 2, 3, 3), false);
  assert.equal(game._line(3, 3, 2, 2), false);
  for (let ay = 1; ay <= 7; ay++) for (let ax = 1; ax <= 7; ax++) {
    for (let by = 1; by <= 7; by++) for (let bx = 1; bx <= 7; bx++) {
      assert.equal(game._line(ax, ay, bx, by), game._line(bx, by, ax, ay));
    }
  }
}

// Level choices cannot produce a surprise enemy attack or accept arbitrary perks.
{
  const game = arena(), s = game.state, p = s.player;
  const victim = game._makeEnemy('rat', 11, 10); victim.hp = 1;
  const threat = game._makeEnemy('skeleton', 10, 11); threat.atk = 999;
  s.enemies = [victim, threat]; p.xp = p.xpNext - 1; p.dodge = 0;
  assert(game.act({ type: 'move', dx: 1, dy: 0 }));
  assert.equal(s.status, 'choice'); assert.equal(s.choices.length, 3);
  assert.equal(game.choose('not-a-perk'), false);
  const turn = s.turn; assert(game.choose(s.choices[0].id));
  assert.equal(s.status, 'playing'); assert.equal(s.turn, turn); assert(p.hp > 0);
}

// Telegraphs give an adjacent player time to escape using ordinary moves.
for (const type of ['bomber', 'boss']) {
  const game = arena(), s = game.state, p = s.player;
  const enemy = game._makeEnemy(type, 11, 10); if (type === 'boss') enemy.actions = 3;
  s.enemies = [enemy]; const hp = p.hp;
  game.act({ type: 'wait' }); assert(enemy.intent);
  game.act({ type: 'move', dx: -1, dy: 0 });
  if (type === 'boss') game.act({ type: 'move', dx: -1, dy: 0 });
  assert.equal(p.hp, hp);
  if (type === 'bomber') assert.equal(s.enemies.length, 0);
}

// Death is terminal, and the final exit requires defeating the boss.
{
  const game = arena(), s = game.state;
  const enemy = game._makeEnemy('skeleton', 11, 10); enemy.atk = 999;
  s.enemies.push(enemy); s.player.dodge = 0; game.act({ type: 'wait' });
  assert.equal(s.status, 'dead'); assert.equal(game.act({ type: 'wait' }), false);
  assert.equal(AshenEngine.fromSave(game.serialize()).state.status, 'dead');
}
{
  const game = arena(), s = game.state;
  s.floor = 5; s.player.x = s.stairs.x; s.player.y = s.stairs.y;
  assert.equal(game.act({ type: 'interact' }), false);
  const boss = game._makeEnemy('boss', 38, 27); boss.hp = 1; s.enemies.push(boss);
  game.act({ type: 'move', dx: -1, dy: 0 });
  while (s.status === 'choice') game.choose(s.choices[0].id);
  assert(s.bossDefeated); assert(game.act({ type: 'interact' })); assert.equal(s.status, 'won');
  assert.equal(AshenEngine.fromSave(game.serialize()).state.status, 'won');
}

for (const invalid of ['', 'null', '{}', '[]', '{']) assert.throws(() => AshenEngine.fromSave(invalid));
{
  const save = JSON.parse(new AshenEngine({ seed: 'corruption' }).serialize());
  save.state.player.x = -10; assert.throws(() => AshenEngine.fromSave(JSON.stringify(save)));
  save.state.player.x = 0; save.state.tiles = []; assert.throws(() => AshenEngine.fromSave(JSON.stringify(save)));
}
console.log('PASS: 300 generated floors, deterministic resumed combat, save validation, symmetric LOS/no invisible shots, spell armor bypass, invalid input, level respite, telegraphs, death and victory.');
