(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./engine.js'));
  else root.DurakBots = factory(root.DurakEngine);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Engine) {
  'use strict';

  function chooseAction(actorView) {
    if (!actorView || !Array.isArray(actorView.legalActions) || !actorView.legalActions.length) return null;
    const legal = actorView.legalActions;
    const rankCounts = {};
    for (const id of actorView.hand || []) {
      const rank = Engine.card(id).rank;
      rankCounts[rank] = (rankCounts[rank] || 0) + 1;
    }
    const defender = actorView.players.find(player => player.id === actorView.defender);
    // A fixed high-card endgame policy can circulate the same unanswerable
    // cards forever. Vary only the attack preference using public counters.
    // This changes no rule and does not reveal the shuffle seed to the bot.
    let publicMix = Math.imul(actorView.round | 0, 0x45d9f3b) ^ Math.imul(actorView.revision | 0, 0x27d4eb2d) ^ (actorView.viewer | 0);
    publicMix = Math.imul(publicMix ^ publicMix >>> 16, 0x45d9f3b);
    publicMix = (publicMix ^ publicMix >>> 16) >>> 0;
    const closeFinish = actorView.deckCount === 0 && defender && defender.count <= 2 && publicMix % 3 === 0;
    function score(action) {
      const value = Engine.card(action.card), trump = value.suit === actorView.trumpSuit;
      // The engine supplies legal moves; the bot ranks them without seeing any
      // opponent hand, future draw order or the random seed.
      if (action.type === 'defend') return (trump ? 32 : 0) + value.rank;
      const rankScore = closeFinish ? (14 - value.rank) * 0.55 : value.rank;
      return (trump ? 28 : 0) + rankScore - Math.min(3, (rankCounts[value.rank] || 1) - 1) * 1.6;
    }
    const plays = legal.filter(action => action.type === 'defend' || action.type === 'attack');
    if (plays.length) {
      return plays.map((action, index) => ({ action, score: score(action), index }))
        .sort((left, right) => left.score - right.score || left.action.card.localeCompare(right.action.card, 'en') || left.index - right.index)[0].action;
    }
    return legal.find(action => action.type === 'take') || legal.find(action => action.type === 'pass') || legal[0];
  }

  return Object.freeze({ chooseAction });
});
