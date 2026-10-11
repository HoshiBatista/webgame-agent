// QA invokes the same state and action dispatcher as visible controls.
function forgeSnapshot(){
  const snapshot=engine.snapshot();snapshot.paused=manualPaused;
  snapshot.persistence={status:saveConflict?'conflict':saveWarning?'memory':engine.state?'saved':'empty'};
  return snapshot;
}
function forgeAction(action){
  if(!action||typeof action!=='object'||Array.isArray(action)||destroyed)return false;
  if(action.type==='start'){newGame({seed:action.seed??engine.seed,playerCount:action.playerCount??engine.playerCount});return true;}
  if(action.type==='pause'){setPaused(action.value);return true;}
  if(isPaused()||!engine.state)return false;
  if(action.type==='stepBot'){
    if(engine.state.actor===null||engine.state.actor===0)return false;
    return applyAction(B.chooseAction(E.view(engine.state,engine.state.actor)),'bot');
  }
  if(action.type==='continue')return engine.state.phase==='roundEnd'&&applyAction({type:'continue'},'system');
  return applyAction(action,'human');
}
function forgeImport(text){
  const saved=GameEngine.parseSave(text);if(!saved)return {ok:false};
  // Explicit synchronous restore may replace this session, but it still honors
  // the original best-effort guard against overwriting another tab's save.
  cancelAdvance();session++;engine.session++;
  engine.state=saved.state;engine.seed=saved.state.seed;engine.playerCount=saved.state.players.length;
  engine.events=[];engine.paused=false;manualPaused=false;
  selected=null;target=null;shownResult=null;history=saved.history;
  closeModal(true);resetAudioSession();saveMatch();renderer.draw();return {ok:true};
}
const forgeBridge={ready:true,snapshot:forgeSnapshot,act:forgeAction,
  reset(options={}){engine.seed=String(options.seed??'durak-corpus');engine.playerCount=options.playerCount??2;
    cancelAdvance();session++;engine.reset(options);manualPaused=false;selected=null;target=null;history=[];shownResult=null;
    forgePendingSeed=engine.seed;closeModal(true);resetAudioSession();renderer.draw();openModal('start');return forgeSnapshot();},
  setManualMode(enabled){forgeManualMode=Boolean(enabled);scheduleAdvance();},
  advance(){throw new Error('Durak is turn-based; wall time is not a legal card move');},
  exportSave(){return JSON.stringify({format:1,state:engine.state,history:history.slice(-80)});},
  importSave:forgeImport,
  remount(){const manual=forgeManualMode;destroy();init();forgeManualMode=manual;if(engine.state)closeModal(true);scheduleAdvance();return {ok:true};}
};
root.__GAME_TEST__=forgeBridge;
const forgeController={dispose(){
  if(forgeDisposed)return;forgeDisposed=true;destroy();renderer.dispose();engine.dispose();
  if(root.__GAME_TEST__===forgeBridge)delete root.__GAME_TEST__;
  if(root.__DURAK_CORPUS_MOUNT__===forgeController)delete root.__DURAK_CORPUS_MOUNT__;
  host.replaceChildren();
}};
root.__DURAK_CORPUS_MOUNT__=forgeController;
return forgeController;
}
