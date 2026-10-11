#!/usr/bin/env python3
"""Reproduce full reviewed Durak DOM game as four trusted Forge modules.

This development tool is not imported by any model provider or production job.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ALL=['engine.js','renderer.js','audio.js','ui.js']

def once(source,before,after):
    if source.count(before)!=1:raise ValueError(f'Adaptation anchor differs: {before[:90]}')
    return source.replace(before,after)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def adapted_files():
    original={n:(HERE/'original'/n).read_text()for n in ['engine.js','bots.js','ui.js','shell.html','style.css']}
    engine=original['engine.js']+'\n'+original['bots.js']+'\n'+(HERE/'adapter_engine.part.js').read_text()
    renderer='''/* The original card game renders DOM/SVG. The adapter owns its actual
 * surface and calls the reviewed render implementation bound by mountGame.
 * It does not invent a hidden Canvas or a parallel render state. */
class GameRenderer {
  constructor(surface){if(!surface||typeof surface.querySelector!=='function')throw new TypeError('A DOM surface is required');this.surface=surface;this.callback=null;this.disposed=false;}
  bind(callback){this.callback=callback;return this;}
  draw(){if(!this.disposed&&this.callback)this.callback();}
  dispose(){this.disposed=true;this.callback=null;}
}
'''
    ui=original['ui.js']
    audio_start=ui.index('  function unlockAudio() {')
    audio_end=ui.index('  function init() {',audio_start)
    audio_functions=ui[audio_start:audio_end]
    audio_vars='''  let audioContext = null;
  let audioMaster = null;
  let noiseBuffer = null;
  let audioResumePending = null;
  const audioNodes = new Map();
'''
    audio_cleanup='''    cancelSounds();
    if (audioMaster) { try { audioMaster.disconnect(); } catch (_) { /* Best effort. */ } }
    if (audioContext && typeof audioContext.close === 'function') {
      try { const promise = audioContext.close(); if (promise && typeof promise.catch === 'function') promise.catch(() => {}); } catch (_) { /* Best effort. */ }
    }
    audioContext = null; audioMaster = null; noiseBuffer = null; audioResumePending = null;'''
    # UI retains sole ownership of context creation, closure and both pending
    # resume/suspend races. GameAudio owns only its buses and complete voices.
    split_effects=audio_functions.index('  function trackSound(')
    split_suspend=audio_functions.index('  function suspendAudio(')
    unlock=audio_functions[:split_effects]
    effects=audio_functions[split_effects:split_suspend]
    suspend=audio_functions[split_suspend:]
    unlock=once(unlock,'''        audioMaster = audioContext.createGain();
        audioMaster.gain.value = 0.24;
        audioMaster.connect(audioContext.destination);''','''        audio = new GameAudio(audioContext, audioContext.destination);''')
    unlock=once(unlock,"      if (audioContext.state !== 'running'", "      audio.setState({enabled:true});\n      if (audioContext.state !== 'running'")
    suspend=once(suspend,'    cancelSounds();','    cancelSounds();\n    if(audio)audio.setState({enabled:false});')
    effects=once(effects,"    if (!preferences.sound || destroyed || manualPaused || pageHidden || doc.hidden || modal && modal !== 'result' || !audioContext || audioContext.state !== 'running') return;",
        "    if (!settings.enabled || settings.sfxVolume <= 0 || disposed || audioContext.state !== 'running') return;")
    effects=once(effects,'    audioNodes.set(source, release);','''    if(audioNodes.size>=32){
      const oldest=audioNodes.entries().next().value;
      try{oldest[0].stop();}catch(_){}oldest[1]();
    }
    audioNodes.set(source, release);''')
    audio='''/* Original short synthesized cues, complete voice ownership and the
 * common Forge audio API. The UI owns the supplied context and its promises.
 * This preserved card game has no ambient composition; its music bus is silent. */
class GameAudio {
  constructor(context,destination=context.destination){
    const audioContext=context,master=context.createGain(),audioMaster=context.createGain(),musicGain=context.createGain();
    master.connect(destination);audioMaster.connect(master);musicGain.connect(master);
    const settings={enabled:false,musicEnabled:true,volume:.55,sfxVolume:.7,mode:'menu'};
    const audioNodes=new Map();let noiseBuffer=null,disposed=false;
    this.sequence=0;this.seen=new Set();this.settings=settings;this.sfxGain=audioMaster;this.musicGain=musicGain;
    master.gain.value=0;audioMaster.gain.value=.24;musicGain.gain.value=.55;
'''+effects+'''
    this.cancel=cancelSounds;
    this.play=kind=>this.handleEvents([{id:'ui:'+String(++this.sequence),type:kind}]);
    this.handleEvents=events=>{
      if(disposed||!Array.isArray(events))return;
      for(const event of events){
        if(!event||typeof event.id!=='string'||typeof event.type!=='string'||this.seen.has(event.id))continue;
        this.seen.add(event.id);if(this.seen.size>256)this.seen.delete(this.seen.values().next().value);
        sound(event.type);
      }
    };
    this.setState=patch=>{
      if(!patch||typeof patch!=='object'||disposed)return;
      const previousEnabled=settings.enabled,previousSfx=settings.sfxVolume;
      for(const key of ['enabled','musicEnabled'])if(typeof patch[key]==='boolean')settings[key]=patch[key];
      for(const key of ['volume','sfxVolume'])if(typeof patch[key]==='number'&&Number.isFinite(patch[key]))settings[key]=Math.max(0,Math.min(1,patch[key]));
      if(typeof patch.mode==='string')settings.mode=patch.mode;
      const masterTarget=settings.enabled?1:0,sfxTarget=.24*settings.sfxVolume/.7,musicTarget=settings.musicEnabled?settings.volume:0;
      if(master.gain.value!==masterTarget)master.gain.value=masterTarget;
      if(audioMaster.gain.value!==sfxTarget)audioMaster.gain.value=sfxTarget;
      if(musicGain.gain.value!==musicTarget)musicGain.gain.value=musicTarget;
      if(previousEnabled&&!settings.enabled||previousSfx>0&&settings.sfxVolume===0)cancelSounds();
    };
    this.tick=()=>{}; // This original SFX-only game has no looping score to schedule.
    this.dispose=()=>{if(disposed)return;disposed=true;cancelSounds();
      for(const node of [audioMaster,musicGain,master])try{node.disconnect();}catch(_){}
      noiseBuffer=null;this.seen.clear();
    };
  }
}
'''
    ui=ui[:audio_start]+unlock+suspend+'''  function cancelSounds(){if(audio)audio.cancel();}
  function sound(kind){
    if(destroyed||manualPaused||pageHidden||doc.hidden||modal&&modal!=='result')return;
    if(audio)audio.play(kind);
  }
  function resetAudioSession(){
    if(audio)audio.dispose();audio=null;
    if(audioContext&&audioContext.state!=='closed'){
      audio=new GameAudio(audioContext,audioContext.destination);
      audio.setState({enabled:preferences.sound&&!manualPaused&&!pageHidden&&!doc.hidden,mode:engine.state?engine.state.phase:'menu'});
    }
  }
'''+ui[audio_end:]
    ui=once(ui,audio_vars,'  let audio = null;\n  let audioContext = null;\n  let audioResumePending = null;\n')
    ui=once(ui,audio_cleanup,'''    cancelSounds();
    if(audio)audio.dispose();audio=null;
    if(audioContext&&typeof audioContext.close==='function'){
      try{const promise=audioContext.close();if(promise&&typeof promise.catch==='function')promise.catch(()=>{});}catch(_){}
    }
    audioContext=null;audioResumePending=null;''')
    ui=once(ui,"(function (root) {\n  'use strict';",'function mountGame(host) {\n  const root=window;\n  if(root.__DURAK_CORPUS_MOUNT__)root.__DURAK_CORPUS_MOUNT__.dispose();\n  let forgeManualMode=false,forgeDisposed=false,forgePendingSeed=null;')
    ui=once(ui,"})(typeof window !== 'undefined' ? window : globalThis);",'')
    ui=once(ui,'  let state = null;','  const engine = new GameEngine();')
    # All unqualified state identifiers refer to the single engine.state.
    # Preserve saved.state, AudioContext.state and the envelope property name.
    ui=once(ui,'{ format: 1, state, history:','{ format: 1, state: engine.state, history:')
    ui=re.sub(r'(?<![\w.])state(?=\s*(?:[.,;)?]|&&|\|\||===|=))','engine.state',ui)
    ui=ui.replace("'durak.cardclub.match.v1'","'game-forge.corpus.durak.match.v1'").replace("'durak.cardclub.preferences.v1'","'game-forge.corpus.durak.preferences.v1'")
    ui=once(ui,"      sound(next.phase === 'finished' ? (next.result.durak === 0 ? 'lose' : 'win') : canonical.type);",
        "      if(audio)audio.handleEvents(engine.events);")
    ui=once(ui,"    sound('deal');","    if(audio)audio.handleEvents(engine.events);")
    ui=once(ui,"    cancelSounds();\n    if (preferences.sound && audioContext) unlockAudio();","    resetAudioSession();\n    if (preferences.sound && audioContext) unlockAudio();")
    ui=once(ui,"const next = E.newGame({ playerCount: count, seed: settings.seed === undefined ? freshSeed() : settings.seed });",
        "const next = E.newGame({ playerCount: count, seed: settings.seed === undefined ? (forgePendingSeed === null ? freshSeed() : forgePendingSeed) : settings.seed });\n    forgePendingSeed=null;")
    ui=once(ui,"if (!engine.state || isPaused() || engine.state.phase === 'finished'", "if (forgeManualMode || !engine.state || isPaused() || engine.state.phase === 'finished'")
    ui=once(ui,'      state = next;','      engine.state = next;') if '      state = next;'in ui else ui
    ui=once(ui,'      engine.state = next;\n      selected', '      engine.state = next;\n      engine.recordEvent(canonical.type);\n      selected')
    ui=once(ui,'    engine.state = next;\n    manualPaused', '    engine.state = next;\n    engine.seed=next.seed;engine.playerCount=count;engine.session++;engine.paused=false;engine.recordEvent(\'deal\');\n    manualPaused')
    ui=once(ui,'    manualPaused = Boolean(value);','    manualPaused = Boolean(value);engine.paused=manualPaused;')
    ui=once(ui,'    initialized = true;\n    destroyed = false;','''    initialized = true;
    destroyed = false;
    engine.paused=false;engine.events=[];forgePendingSeed=null;''')
    # Every render uses GameRenderer; the original body remains an explicit
    # compatibility callback with no independent model.
    ui=once(ui,'  function render() {','  function renderOriginal() {')
    ui=re.sub(r'\brender\(', 'renderer.draw(', ui)
    ui=once(ui,'  const E = root.DurakEngine;', '  const renderer = new GameRenderer(host).bind(()=>renderOriginal());\n  const E = root.DurakEngine;')
    shell=original['shell.html']
    body=shell.split('<body>',1)[1].split('<script>',1)[0].rstrip()
    if '<script'in body or '</body>'in body:raise ValueError('Unexpected source shell')
    body=body.replace('id="game-table"','id="game-table" data-testid="game-surface"').replace('id="btn-start"','id="btn-start" data-testid="start"').replace('id="btn-sound"','id="btn-sound" data-testid="sound"')
    # This is exact source CSS plus its original body markup, not remote assets.
    ui=once(ui,'  const doc = root.document;', '  const doc = root.document;\n  host.innerHTML='+json.dumps('<style>'+original['style.css']+'</style>'+body,ensure_ascii=False)+';')
    # Original init auto-runs after all adapters have been created.
    ui += '\n'+(HERE/'adapter_ui.part.js').read_text()
    return {'engine.js':engine,'renderer.js':renderer,'audio.js':audio,'ui.js':ui}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    outputs=adapted_files()
    for name,source in outputs.items():
        path=HERE/name
        if args.check:
            if not path.exists()or path.read_text()!=source:raise SystemExit('Adapter differs: '+name)
        else:path.write_text(source)
    harness=(HERE/'original/ui-harness.cjs').read_text()
    harness=once(harness,"require('linkedom')","require('../../camp/node_modules/linkedom')")
    harness=once(harness,"const bytes = fs.readFileSync(artifactPath), html = bytes.toString('utf8');","const bytes = options.html === undefined ? fs.readFileSync(artifactPath) : Buffer.from(options.html), html = bytes.toString('utf8');")
    harness=once(harness,"assert.equal(scripts.length, 3, 'The artifact contains the three exact inline source modules');","assert.equal(scripts.length, 1, 'The Forge artifact contains the one exact assembled script');")
    for typ in ['get','set','remove']:
        harness=harness.replace("{ type: '"+typ+"', key", "{ type: '"+typ+"', mode: state.storageMode, key")
    harness=once(harness,"globals.DurakApp.destroy(); timers.clear(); frames.clear();","globals.__DURAK_CORPUS_MOUNT__.dispose(); timers.clear(); frames.clear();")
    harness_path=HERE/'qa/ui_harness.cjs'
    if args.check:
        if harness_path.read_text()!=harness:raise SystemExit('Reviewed DOM harness adaptation differs')
    else:harness_path.write_text(harness)
    provenance=json.loads((HERE/'provenance.json').read_text())
    if args.check:
        for group,directory in [('original_files_sha256',HERE/'original'),('adapted_files_sha256',HERE),('qa_files_sha256',HERE/'qa')]:
            if group=='qa_files_sha256' and set(provenance[group])!={p.name for p in directory.glob('*.cjs')}:
                raise SystemExit('QA input inventory differs from provenance')
            if group=='original_files_sha256' and set(provenance[group])!={p.name for p in directory.iterdir()if p.is_file()}:
                raise SystemExit('Original source inventory differs from provenance')
            for name,digest in provenance[group].items():
                if sha(directory/name)!=digest:raise SystemExit(f'Provenance differs: {group}/{name}')
    else:
        provenance['adapted_files_sha256']={name:sha(HERE/name)for name in ALL}
        provenance['qa_files_sha256']={p.name:sha(p)for p in sorted((HERE/'qa').glob('*.cjs'))}
        (HERE/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':'passed','mode':'check'if args.check else'build','files':{n:len(s.encode())for n,s in outputs.items()}}))

if __name__=='__main__':main()
