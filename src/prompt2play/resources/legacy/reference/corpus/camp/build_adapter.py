#!/usr/bin/env python3
"""Reproduce trusted four-module adapters from unchanged reviewed source bytes.

This build tool is never called by the game generator or production worker.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent

def replace_once(source, before, after):
    if source.count(before)!=1:
        raise ValueError(f"Reviewed source adaptation anchor changed: {before[:80]}")
    return source.replace(before,after)

def module_source(name):
    source=(HERE/'original'/name).read_text()
    source=re.sub(r"^if \(typeof module !== 'undefined' && module.exports\) module.exports = .*?;\n?",'',source,flags=re.M)
    return source

def adapted_files():
    engine=module_source('engine.js')
    campaign=module_source('campaign.js')
    campaign=replace_once(campaign,"typeof module !== 'undefined' && module.exports ? require('./engine.js').AshenEngine : AshenEngine",'AshenEngine')
    campaign=replace_once(campaign,"typeof module !== 'undefined' && module.exports ? require('./engine.js').ASHEN_CLASSES : ASHEN_CLASSES",'ASHEN_CLASSES')
    engine+='\n'+campaign+'\n'+(HERE/'adapter_engine.part.js').read_text()
    renderer=module_source('renderer.js')+'\n'+module_source('camp_renderer.js')+'\nclass GameRenderer extends AshenRenderer {}\n'
    audio=module_source('music.js')+'\nclass GameAudio extends AshenMusic {}\n'
    ui=module_source('ui.js')
    ui=ui.replace('AshenCampaign','GameEngine').replace('new AshenRenderer(canvas)','new GameRenderer(canvas)').replace('new AshenMusic(this.ctx,this.ctx.destination)','new GameAudio(this.ctx,this.ctx.destination)')
    ui=replace_once(ui,'document.body.appendChild(root);','host.appendChild(root);')
    ui=ui.replace("'ashen-vault.campaign.v2'","'game-forge.corpus.camp.v2'").replace("'ashen-vault.run.v1'","'game-forge.corpus.camp.legacy.v1'").replace("'ashen-vault.preferences.v1'","'game-forge.corpus.camp.preferences.v1'")
    ui=replace_once(ui,'function frame(time){','function frame(time){\n  if(uiDisposed)return;')
    ui=replace_once(ui,'if(moveQueue.length&&time>=nextAutoStep','if(!uiManualMode&&moveQueue.length&&time>=nextAutoStep')
    ui=ui.replace('requestAnimationFrame(frame);','uiRaf=requestAnimationFrame(frame);')
    ui,n=re.subn(r"(root|canvas|document|window|\$\('[^']+'\))\.addEventListener\(",r'uiListen(\1,',ui)
    if n!=14:raise ValueError(f'Expected 14 reviewed listeners, saw {n}')
    ui=replace_once(ui,"function onAction(action){","function onAction(action){\n  if(action==='fresh-campaign'){setScreen('confirm');mountDialog('<section class=\"ash-dialog\"><h2>Начать новую кампанию?</h2><p>Лагерь будет создан заново. Перед этим можно выгрузить нынешнее сохранение из меню.</p><div class=\"ash-dialog-actions\"><button class=\"ash-primary\" data-action=\"fresh-campaign-confirmed\">Создать новый лагерь</button><button class=\"ash-secondary\" data-action=\"resume\">Назад</button></div></section>');return;}\n  if(action==='fresh-campaign-confirmed')return uiFreshCampaign();")
    ui=ui.replace('<button class="ash-secondary" data-action="export">Выгрузить кампанию</button>','<button class="ash-secondary" data-action="export">Выгрузить кампанию</button><button class="ash-secondary" data-action="fresh-campaign">Новая кампания</button>')
    ui=replace_once(ui,"renderHUD();updateSoundButton();uiRaf=requestAnimationFrame(frame);","renderHUD();updateSoundButton();\n$('ash-sound-button').setAttribute('data-testid','sound');\nconst uiStartButton=root.querySelector('[data-action=\"depart\"]');if(uiStartButton)uiStartButton.setAttribute('data-testid','start');\nuiRaf=requestAnimationFrame(frame);")
    ui="""/* Full reviewed camp UI, adapted only for Forge mounting and QA surfaces. */
function mountGame(host){
let uiDisposed=false,uiManualMode=false,uiRaf=null;
const uiListeners=[];
function uiListen(target,event,handler,options){
  target.addEventListener(event,handler,options);
  uiListeners.push(()=>target.removeEventListener(event,handler,options));
}
"""+ui+'\n'+(HERE/'adapter_ui.part.js').read_text()
    return {'engine.js':engine,'renderer.js':renderer,'audio.js':audio,'ui.js':ui}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    outputs=adapted_files()
    for name,source in outputs.items():
        path=HERE/name
        if args.check:
            if not path.exists()or path.read_text()!=source:raise SystemExit(f'Corpus adapter differs: {name}')
        else:path.write_text(source)
    provenance=json.loads((HERE/'provenance.json').read_text()) if (HERE/'provenance.json').exists() else None
    if args.check and provenance is None:raise SystemExit('Missing reviewed source provenance')
    if args.check and provenance:
        for group,directory in [('original_files_sha256',HERE/'original'),('adapted_files_sha256',HERE),('qa_files_sha256',HERE/'qa')]:
            for name,digest in provenance[group].items():
                if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=digest:raise SystemExit(f'Provenance hash differs: {group}/{name}')
    print(json.dumps({'status':'passed','mode':'check'if args.check else'build','files':{name:len(source.encode())for name,source in outputs.items()}}))

if __name__=='__main__':main()
