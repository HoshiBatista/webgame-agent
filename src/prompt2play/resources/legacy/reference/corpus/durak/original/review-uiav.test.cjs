'use strict';

// Review regressions execute dist/Durak.html through the existing DOM, timer,
// and Web Audio command model. They make no browser layout or listening claim.
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../src/engine.js');
const B = require('../src/bots.js');
const { loadGame } = require('./ui-harness.cjs');

function seedFor(predicate, tag) {
  for (let i = 0; i < 300; i++) {
    const seed = `review-uiav-${tag}-${i}`;
    if (predicate(E.newGame({ playerCount: 2, seed }))) return seed;
  }
  throw new Error('Could not find the deterministic public-UI setup');
}

const humanOpenSeed = () => seedFor(s => s.actor === 0, 'human-open');
const humanDefendSeed = () => seedFor(s => {
  if (s.actor !== 1) return false;
  const next = E.step(s, B.chooseAction(E.view(s, 1)));
  return next.actor === 0 && E.actions(next).some(a => a.type === 'defend');
}, 'human-defend');

function newHumanGame(h) {
  h.app.newGame({ playerCount: 2, seed: humanOpenSeed() });
}

function activeSources(context) {
  return context.nodes.filter(node => node.started && !node.ended);
}

function assertDisconnected(sources, message) {
  assert.ok(sources.every(source => source.connections.length === 0), message);
}

test('review UI: closing nested rules restores focus to the original game control', () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    const before = JSON.stringify(h.app.getState());
    h.click('#btn-new');
    h.click('#btn-welcome-rules');
    h.click('#btn-rules-done');
    assert.equal(h.$('#modal-start').hidden, false);
    h.click('#btn-close-start');
    assert.equal(h.$('#modal-start').hidden, true);
    assert.equal(h.document.activeElement.id, 'btn-new', 'Focus must return to the invoking toolbar control, never a hidden rules button');
    assert.equal(Boolean(h.document.activeElement.closest('[hidden]')), false);
    assert.equal(JSON.stringify(h.app.getState()), before, 'Reading rules does not change the match');
  } finally { h.dispose(); }
});

test('review UI: Escape deselects a hand card without discarding keyboard focus', () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    const card = h.app.getView().legalActions.find(a => a.card).card;
    h.click(`#hand [data-card="${card}"]`);
    const before = JSON.stringify(h.app.getState());
    h.key('Escape');
    assert.equal(h.$(`#hand [data-card="${card}"]`).getAttribute('aria-pressed'), 'false');
    assert.equal(h.document.activeElement.getAttribute('data-card'), card, 'The same still-present card must retain focus after deselection');
    assert.equal(JSON.stringify(h.app.getState()), before);
  } finally { h.dispose(); }
});

test('review UI: choosing an attack to cover retains focus on its table control', () => {
  const h = loadGame();
  try {
    h.app.newGame({ playerCount: 2, seed: humanDefendSeed() });
    h.advance(5000);
    const defense = h.app.getView().legalActions.find(a => a.type === 'defend');
    assert.ok(defense, 'The real bot has made a legally defendable attack');
    h.click(`#battlefield [data-target="${defense.target}"]`);
    assert.equal(h.document.activeElement.getAttribute('data-target'), String(defense.target), 'Selecting a defense target must not remove the focused control');
    h.click(`#hand [data-card="${defense.card}"]`);
    h.key('Enter');
    assert.equal(h.app.getState().table[defense.target].defense, defense.card);
  } finally { h.dispose(); }
});

test('review UI: Enter on a different focused hand card selects it without playing the old selection', () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    const cards = [...h.document.querySelectorAll('#hand [data-card]:not([disabled])')];
    assert.ok(cards.length >= 2);
    const first = cards[0].getAttribute('data-card'), second = cards[1].getAttribute('data-card');
    h.click(`#hand [data-card="${first}"]`);
    const focused = h.$(`#hand [data-card="${second}"]`);
    focused.focus(); // Native Tab navigation arrives at the next button.
    const revision = h.app.getState().revision;
    const enter = h.event(focused, 'keydown', { key: 'Enter', code: 'Enter' });
    // Linkedom has no browser default actions. Explicitly model Enter's native
    // button click only when the application's handler did not prevent it.
    if (!enter.defaultPrevented) focused.click();
    assert.equal(h.app.getState().revision, revision, 'Changing the keyboard-selected card must not play the previously selected card');
    assert.equal(h.$(`#hand [data-card="${second}"]`).getAttribute('aria-pressed'), 'true');
    h.event(h.document.activeElement, 'keydown', { key: 'Enter', code: 'Enter' });
    assert.equal(h.app.getState().revision, revision + 1);
    assert.equal(h.app.getState().table[0].attack, second);
  } finally { h.dispose(); }
});

test('review audio: muting cancels scheduled deal sources instead of preserving them for replay', async () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    h.click('#btn-sound');
    await h.settle();
    h.advance(100);
    newHumanGame(h);
    const context = h.contexts[0];
    const obsolete = activeSources(context);
    assert.ok(obsolete.length >= 6, 'A real six-card deal sound must be pending before mute');
    h.click('#btn-sound');
    h.advance(5000);
    assertDisconnected(obsolete, 'Muted one-shots must be disconnected so that resume cannot replay the old deal');
    h.click('#btn-sound');
    await h.settle();
    assertDisconnected(obsolete, 'Enabling sound must not reconnect obsolete effects');
    assert.equal(h.contexts.length, 1, 'Reuse the existing context');
    assert.equal(context.state, 'running');
  } finally { h.dispose(); }
});

test('review audio: hiding the page clears pending effects and returning resumes sound', async () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    h.click('#btn-sound');
    await h.settle();
    h.advance(100);
    newHumanGame(h);
    const context = h.contexts[0], obsolete = activeSources(context);
    assert.ok(obsolete.length > 0);
    h.visibility(true);
    h.advance(5000);
    assertDisconnected(obsolete, 'Hidden-page one-shots must not wait to replay on return');
    h.visibility(false);
    await h.settle();
    assert.equal(context.state, 'running');
    assertDisconnected(obsolete, 'Return must preserve cancellation of old effects');
  } finally { h.dispose(); }
});

test('review audio: pagehide/pageshow without a visibility event resumes the existing context and bots', async () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    h.click('#btn-sound');
    await h.settle();
    h.app.newGame({ playerCount: 2, seed: humanDefendSeed() });
    const context = h.contexts[0], revision = h.app.getState().revision;
    h.event(h.window, 'pagehide');
    h.advance(5000);
    assert.equal(h.app.getState().revision, revision, 'Background page lifecycle must pause bots');
    h.event(h.window, 'pageshow');
    await h.settle();
    assert.equal(context.state, 'running', 'A visible bfcache-style return must resume the already-unlocked sound context');
    h.advance(5000);
    assert.equal(h.app.getState().revision, revision + 1);
    assert.equal(h.app.getState().actor, 0);
    assert.equal(h.contexts.length, 1);
  } finally { h.dispose(); }
});

test('review audio: a browser-delayed resume cannot accumulate one-shots at frozen audio time', async () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    h.click('#btn-sound');
    await h.settle();
    h.advance(100);
    const context = h.contexts[0];
    context.state = 'suspended';
    let resumeRequests = 0;
    context.resume = () => { resumeRequests++; return new Promise(() => {}); }; // Browser leaves resume pending until audio is available.
    const startsBefore = h.audioEvents.filter(e => e.type === 'start').length;
    const card = h.app.getView().legalActions.find(a => a.card).card;
    for (let i = 0; i < 12; i++) h.click(`#hand [data-card="${card}"]`);
    assert.equal(h.audioEvents.filter(e => e.type === 'start').length, startsBefore, 'Suspended audio must skip transient effects instead of queuing a later burst');
    assert.equal(resumeRequests, 1, 'Reuse a pending browser resume request until it settles');
    assert.equal(h.contexts.length, 1);
    assert.equal(h.app.getState().revision, 0, 'Selection still works while audio is unavailable');
  } finally { h.dispose(); }
});

test('review audio: a delayed resume completing after mute cannot turn sound back on', async () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    let completeResume;
    h.window.AudioContext.prototype.resume = function () {
      this.resumeCalls++;
      return new Promise(resolve => { completeResume = () => { this.state = 'running'; resolve(); }; });
    };
    h.click('#btn-sound');
    const context = h.contexts[0];
    assert.equal(typeof completeResume, 'function', 'The browser must have a real pending resume request');
    h.click('#btn-sound');
    assert.equal(h.$('#btn-sound').getAttribute('aria-pressed'), 'false');
    completeResume();
    await h.settle();
    assert.notEqual(context.state, 'running', 'A late async completion must respect the current muted state');
    assertDisconnected(activeSources(context), 'Muted sources cannot become audible after the late resume');
  } finally { h.dispose(); }
});

test('review audio: a rejected browser resume preserves legal play without an audio backlog', async () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    h.window.AudioContext.prototype.resume = function () {
      this.resumeCalls++;
      return Promise.reject(new Error('The browser denied audio resume'));
    };
    h.click('#btn-sound');
    await h.settle();
    const action = h.app.getView().legalActions.find(a => a.type === 'attack');
    h.click(`#hand [data-card="${action.card}"]`);
    h.click('#btn-play');
    await h.settle();
    assert.equal(h.app.getState().revision, 1, 'Sound failure cannot prevent a legal card move');
    assert.equal(h.app.getState().table[0].attack, action.card);
    assert.equal(h.audioEvents.filter(e => e.type === 'start').length, 0, 'Rejected audio must not leave effects queued in a suspended context');
    assert.equal(h.contexts.length, 1, 'A failed resume does not create an uncontrolled series of audio contexts');
  } finally { h.dispose(); }
});

test('review audio: a delayed suspend completing after unmute cannot leave enabled sound suspended', async () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    h.click('#btn-sound');
    await h.settle();
    const context = h.contexts[0];
    let completeSuspend;
    context.suspend = function () {
      return new Promise(resolve => { completeSuspend = () => { this.state = 'suspended'; resolve(); }; });
    };
    h.click('#btn-sound');
    assert.equal(typeof completeSuspend, 'function', 'A real asynchronous suspend request must have been issued');
    assert.equal(h.$('#btn-sound').getAttribute('aria-pressed'), 'false');
    h.click('#btn-sound');
    assert.equal(h.$('#btn-sound').getAttribute('aria-pressed'), 'true');
    completeSuspend();
    await h.settle();
    assert.equal(context.state, 'running', 'A late mute completion must respect the newer enabled-sound preference');
    assert.equal(h.contexts.length, 1);
    assert.equal(h.app.getState().revision, 0);
  } finally { h.dispose(); }
});

test('review audio: ordinary completed one-shots release every transient audio connection', async () => {
  const h = loadGame();
  try {
    newHumanGame(h);
    h.click('#btn-sound');
    await h.settle();
    const context = h.contexts[0];
    for (let i = 0; i < 12; i++) {
      const card = h.app.getView().legalActions.find(a => a.card).card;
      h.click(`#hand [data-card="${card}"]`);
      h.advance(150);
    }
    const connected = context.nodes.filter(node => node.connections.length > 0);
    assert.equal(connected.length, 1, 'Only the shared master gain may stay connected between effects');
    assert.equal(activeSources(context).length, 0);
    h.app.destroy();
    assert.equal(context.state, 'closed');
    assertDisconnected(context.nodes, 'Destroy must release even the master connection');
    assert.equal(h.timers.size, 0);
  } finally { h.dispose(); }
});
