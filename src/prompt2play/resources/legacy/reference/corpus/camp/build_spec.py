#!/usr/bin/env python3
"""Declare the fixed reviewed corpus behavior; never a planner/provider template."""
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ALL=['engine.js','renderer.js','audio.js','ui.js']
RULES=['engine.js','ui.js']
route=json.loads((HERE/'first-loop-route.json').read_text())['steps']
def act(type,**values):return {'op':'act','action':{'type':type,**values}}
def capture(key):return {'op':'capture','key':key}
def assertion(path,value=None,*,saved=None,saved_path=None,cmp='eq'):
    return {'op':'assert','left':{'path':path},'cmp':cmp,'right':{'saved':saved,'path':saved_path or path}if saved else{'value':value}}
def scenario(id,category,purpose,steps,files=RULES):
    return {'id':id,'category':category,'purpose':purpose,'seed':'embers','steps':[json.dumps(s,ensure_ascii=False,separators=(',',':'))for s in steps],
        'affected_files':files,'limitations':['Trusted authored reference with recorded legal actions, not a live model result','The route planner sees the entire map; this does not measure human difficulty']}
start=[act('acceptQuest',id='watch_1'),act('start',seed='embers',classId='mage')]
first_loop=start+route[:-1]+[assertion('/campaign/engine/state/player/xp',0,cmp='gt')]+route[-1:]+[
    assertion('/campaign/mode','camp'),assertion('/campaign/meta/resources/gold',44),
    act('claimQuest',id='watch_1'),act('upgradeBuilding',id='hearth'),
    capture('built'),act('start',seed='embers-next',classId='mage'),
    assertion('/campaign/meta/buildings/hearth',1),assertion('/campaign/engine/state/player/maxHp',32),
    assertion('/campaign/engine/state/player/level',1),assertion('/campaign/engine/state/player/xp',0),
    assertion('/campaign/meta/resources',saved='built'),assertion('/campaign/meta/quests',saved='built')]
prefix=route[:8]
continuation=route[8:13]
scenarios=[
    scenario('camp-first-loop','progress','Accept an NPC quest, earn and deliver loot legally, claim a gate, build a permanent bonus and start a fresh hero',first_loop),
    scenario('camp-pause-reset','lifecycle','Pausing rejects game turns; abandonment preserves the camp and a new attempt resets hero XP',start+route[:6]+[
        act('pause',value=True),capture('paused'),act('wait'),assertion('/campaign',saved='paused'),
        act('pause',value=False),act('abandon'),capture('camp'),act('start',seed='next-attempt',classId='mage'),
        assertion('/campaign/engine/state/player/level',1),assertion('/campaign/engine/state/player/xp',0),
        assertion('/campaign/meta/resources',saved='camp'),assertion('/campaign/meta/quests',saved='camp'),
        assertion('/campaign/meta/buildings',saved='camp')]),
    scenario('camp-roundtrip','persistence','Actual save/load preserves rules and RNG, then the same legal continuation reaches the identical state',start+prefix+[
        capture('before'),{'op':'serialize','key':'checkpoint'}]+continuation+[
        capture('expected'),assertion('/campaign',saved='before',cmp='ne'),{'op':'restore','saved':'checkpoint','expect':'accepted'},assertion('/campaign',saved='before')]+continuation+[
        assertion('/campaign',saved='expected'),assertion('/bonuses',saved='expected')]),
    scenario('camp-settlement-once','accounting','Repeated return, reload and quest claim cannot credit the same loot or reward twice',start+route+[
        capture('settled'),{'op':'serialize','key':'settledSave'},{'op':'restore','saved':'settledSave','expect':'accepted'},assertion('/campaign',saved='settled'),
        {'op':'act','action':{'type':'return'},'repeat':3},assertion('/campaign',saved='settled'),
        act('claimQuest',id='watch_1'),capture('claimed'),{'op':'serialize','key':'claimedSave'},
        {'op':'act','action':{'type':'claimQuest','id':'watch_1'},'repeat':3},assertion('/campaign/meta',saved='claimed'),
        {'op':'restore','saved':'claimedSave','expect':'accepted'},assertion('/campaign',saved='claimed'),act('claimQuest',id='watch_1'),assertion('/campaign/meta',saved='claimed')]),
    scenario('camp-import-rejection','persistence','Empty, malformed and incompatible imports leave the live campaign untouched',start+prefix+[
        capture('live'),{'op':'restore','text':'','expect':'rejected'},assertion('/campaign',saved='live'),
        {'op':'restore','text':'{','expect':'rejected'},assertion('/campaign',saved='live'),
        {'op':'restore','text':'{"format":"ashen-campaign","version":999,"mode":"camp"}','expect':'rejected'},assertion('/campaign',saved='live')]),
    scenario('camp-unavailable-storage','persistence','Quota and denied storage preserve accepted in-memory actions and expose a truthful unsaved status',[
        {'op':'storage_fault','mode':'quota'},act('acceptQuest',id='watch_1'),
        assertion('/campaign/meta/quests/watch_1/status','active'),assertion('/persistence/status','memory'),
        capture('memory'),{'op':'serialize','key':'memorySave'},{'op':'storage_fault','mode':'normal'},
        {'op':'restore','saved':'memorySave','expect':'accepted'},assertion('/campaign',saved='memory'),assertion('/persistence/status','saved'),
        {'op':'storage_fault','mode':'denied'},act('acceptQuest',id='forge_1'),
        assertion('/campaign/meta/quests/forge_1/status','active'),assertion('/persistence/status','memory'),
        {'op':'storage_fault','mode':'normal'}],['ui.js']),
    scenario('camp-building-refusal','accounting','Locked upgrades and premature claims do not debit resources or grant bonuses',[
        capture('initial'),act('claimQuest',id='watch_1'),{'op':'act','action':{'type':'upgradeBuilding','id':'hearth'},'repeat':2},
        assertion('/campaign/meta',saved='initial'),assertion('/bonuses',saved='initial'),
        act('acceptQuest',id='watch_1'),capture('accepted'),act('acceptQuest',id='watch_1'),
        assertion('/campaign/meta',saved='accepted')]),
]
def field(id,path,type,unit,meaning,example,owner='engine.js',consumers=None):
    return {'id':id,'path':path,'type':type,'unit':unit,'meaning':meaning,'owner':owner,'consumers':['renderer.js','ui.js']if consumers is None else consumers,'example_json':json.dumps(example,ensure_ascii=False)}
fields=[
    field('camp-mode','/campaign/mode','string','phase label','Campaign phase; run result is settled before returning to camp','camp'),
    field('bank-resources','/campaign/meta/resources','object','integer resource units','Permanent spendable camp bank; distinct from the active hero backpack',{'gold':0,'wood':0,'ore':0,'herb':0,'crystal':0}),
    field('building-levels','/campaign/meta/buildings','object','building levels','Permanent building levels, each gated by an NPC quest',{'hearth':0,'forge':0,'garden':0,'archive':0}),
    field('quest-ledger','/campaign/meta/quests','object','accepted objective counters','Permanent quest status and bounded progress accumulated after acceptance',{'watch_1':{'status':'active','progress':0}}),
    field('campaign-statistics','/campaign/meta/stats','object','attempt counts','Aggregate statistics committed with settlement',{'runs':0,'wins':0,'deaths':0,'returns':0,'bestFloor':0}),
    field('hero-state','/campaign/engine/state/player','object','hero stats and backpack units','Present only during an attempt/result; level, XP, temporary gear and carried resources reset on the next attempt',{'classId':'mage','level':1,'xp':0,'maxHp':26,'gold':0,'materials':{'wood':0,'ore':0,'herb':0,'crystal':0}}),
    field('random-state','/campaign/engine/rng','integer','PRNG state','Present during an attempt; restore preserves future random outcomes',0),
    field('run-floor','/campaign/engine/state/floor','integer','dungeon floors','Present during an attempt; starts at one, ends after fifth-floor boss and exit',1),
    field('camp-bonuses','/bonuses','object','hero stat increments','Read-only bonuses derived from canonical building levels and applied once when constructing a new hero',{'hp':0,'atk':0,'armor':0,'mana':0,'potions':0,'spellPower':0}),
    field('quest-views','/quests','array','quest presentation records','Read-only objective/gate views from the one canonical campaign catalog',[]),
    field('presentation-events','/events','array','one-action event records','Bounded events are presentation only and disappear on restore; quest accounting uses rule counters',[],consumers=['audio.js','ui.js']),
    field('persistence-status','/persistence/status','string','storage status label','UI reports saved only after a write succeeds; memory and blocked retain the live session','unknown',owner='ui.js',consumers=[]),
]
event_schema={'type':'object','properties':{'id':{'type':'string'},'type':{'const':'step'}},'required':['id','type'],'additionalProperties':True}
domains=[
    {'id':'domain-phase','owner':'engine.js','field_ids':['camp-mode'],'lifetime':'phase','reset_policy':'camp -> run -> result -> camp; safe return can move run directly to camp','preserve_policy':'Phase and settlement are serialized together'},
    {'id':'domain-camp','owner':'engine.js','field_ids':['bank-resources','building-levels','quest-ledger','campaign-statistics'],'lifetime':'persistent','reset_policy':'Only an explicit new-campaign action resets the camp','preserve_policy':'Deaths, abandonment and new attempts retain the bank, buildings and earned objective progress'},
    {'id':'domain-attempt','owner':'engine.js','field_ids':['hero-state','random-state','run-floor'],'lifetime':'attempt','reset_policy':'New hero starts floor1, level1, XP0 with fresh temporary gear and empty backpack','preserve_policy':'Save/load resumes the current hero and RNG; settlement transfers loot once according to outcome'},
    {'id':'domain-derived','owner':'engine.js','field_ids':['camp-bonuses','quest-views'],'lifetime':'derived','reset_policy':'Recompute from canonical campaign state without writes','preserve_policy':'No independent authoritative copy or reward issuance in render/UI'},
    {'id':'domain-events','owner':'engine.js','field_ids':['presentation-events'],'lifetime':'action','reset_policy':'Next accepted action/reload replaces presentation events','preserve_policy':'Never reconstruct rewards or objective progress from event playback'},
    {'id':'domain-storage-ui','owner':'ui.js','field_ids':['persistence-status'],'lifetime':'session','reset_policy':'Recompute after real persistence reads/writes','preserve_policy':'Preserve live session when writes fail; distinguish durable success'}]
contract={
    'version':3,
    'timing':{'mode':'turn_based','step_action':'{}','step_seconds':0,'max_catchup_steps':0,'pause_policy':'Only accepted public actions advance turns; menus block movement and hidden time is discarded'},
    'fields':fields,'events':[{'type':'step','payload_schema':json.dumps(event_schema),'example_json':'{"id":"1","type":"step"}','delivery':'Reviewed engine emits once per action; UI routes real events to renderer and sound. Snapshot normalizes legacy numeric event IDs to strings. Events never own quests or settlement.','owner':'engine.js','consumers':['renderer.js','audio.js','ui.js']}],
    'state_machines':[{'id':'campaign-cycle','owner':'engine.js','states':['camp','run','result'],'initial_state':'camp','terminal_states':[],
        'transitions':[{'from':'camp','to':'run','trigger':'startRun','effect':'Construct level1 hero with camp bonuses once'},{'from':'run','to':'camp','trigger':'safe return','effect':'Transfer loot and close the attempt once'},{'from':'run','to':'result','trigger':'victory, death or abandonment','effect':'Preflight dependent writes and settle once'},{'from':'result','to':'camp','trigger':'returnToCamp','effect':'Display settled camp without crediting again'}]}],
    'resources':[{'name':'camp-mount','owner':'ui.js','acquire':'mount creates one UI session, listeners and RAF; sound context is lazy','release':'dispose removes listeners, cancels RAF and closes owned audio','stale_work_policy':'Import ticket and session revision reject late file reads; actual shared bytes are rechecked before replacement'}],
    'invariants':[{'id':'settlement-once','statement':'Bank credit, delivery objectives, aggregate statistics and closed attempt commit together exactly once','owners':RULES,'check_strategy':'Legal extraction, repeated return/claim and save/load between repetitions'},{'id':'campaign-import-valid','statement':'Rejected imports preserve live game; accepted real saves preserve rules and RNG','owners':RULES,'check_strategy':'Roundtrip and legal continuation; blank/corrupt/version rejection; source parser also validates map connectivity and boss consistency'}],
    'state_domains':domains,
    'transactions':[
        {'id':'tx-return','owner':'engine.js','action_json':'{"type":"return"}','domain_ids':['domain-camp','domain-attempt','domain-phase'],'preconditions':['At safe entry/stair with no visible enemy, or an already settled result','All resource credits fit the accepted bank range before terminal change'],'commit':['Credit bank and delivery progress according to outcome','Record result/statistics and close attempt in the same serialized campaign'],'rejection_policy':'Domain state remains unchanged; show current refusal notice','repeat_policy':'A second return/restore cannot settle the same attempt again','scenario_ids':['camp-settlement-once']},
        {'id':'tx-claim','owner':'engine.js','action_json':'{"type":"claimQuest","id":"watch_1"}','domain_ids':['domain-camp'],'preconditions':['Camp mode','Accepted quest is ready and not claimed','Reward fits bank bounds'],'commit':['Credit reward','Mark quest claimed to unlock its building level'],'rejection_policy':'No partial rewards or progress changes','repeat_policy':'Claiming a claimed quest is rejected','scenario_ids':['camp-settlement-once','camp-building-refusal']},
        {'id':'tx-building','owner':'engine.js','action_json':'{"type":"upgradeBuilding","id":"hearth"}','domain_ids':['domain-camp','domain-derived'],'preconditions':['Camp mode','Required quest gate claimed','Every resource cost affordable'],'commit':['Debit full declared cost','Increment the authorized building level'],'rejection_policy':'No partial debit or bonus on refusal','repeat_policy':'Next tier requires its own gate and cost; stale UI levels cannot silently buy it','scenario_ids':['camp-first-loop','camp-building-refusal']}],
    'progression':[{'id':'progress-first-hearth','owner':'engine.js','source_field_id':'quest-ledger','unit':'two enemies defeated after quest acceptance','starts_when':'Accept watch_1 at its NPC in camp','completion':'Kill2, return safely, claim watch_1, then pay hearth1 cost','prerequisites':[],'reward_policy':'Quest reward credits once; gate unlock does not make construction free','scenario_ids':['camp-first-loop','camp-settlement-once']}],
    'persistence':[{'id':'save-campaign','owner':'ui.js','domain_ids':['domain-phase','domain-camp','domain-attempt'],'storage':'local_storage','format_version':'ashen-campaign v2 with supported ashen-vault v1 migration','validation_rules':['Bound types and counters, exact field sets and resource limits','Validate phase/settlement/quest/gate consistency','Connected walkable map, one exit, consistent boss/floor and terminal state'],'migration_policy':'Migrate genuine v1 saves without reapplying bonuses or replaying presentation events; unknown versions rejected','write_policy':'Serialize camp and attempt in one JSON after accepted public actions; render/result display does not write','conflict_policy':'Compare durable bytes with observed baseline before write and after deferred file reading; protect local session and offer explicit resolution. This is not atomic multi-process CAS','failure_policy':'Invalid import preserves current session; quota/denied leaves progress in memory and displays memory/blocked, with full JSON export available','scenario_ids':['camp-roundtrip','camp-import-rejection','camp-unavailable-storage']}],
    'first_playable_loop':{'description':'Accept first NPC quest, earn and deliver loot, claim authorization, build hearth and see permanent HP bonus on a fresh hero','scenario_id':'camp-first-loop'},
}
spec={'title':'Пепельный свод · записанный корпус совместимости','summary':'Complete reviewed camp roguelike2.0.1 adapted for real Forge graph compatibility; not live model generation','genre':'turn-based roguelike with persistent camp',
    'rules':['Explore five procedural floors with three hero classes','NPC quests authorize four permanent buildings','Each new attempt resets hero level and XP; bank and buildings survive','Safe return/victory transfers carried loot once; death/abandonment loses carried loot'],
    'state_schema':json.dumps({f['path']:f['meaning']for f in fields},ensure_ascii=False),'action_schema':json.dumps({'type':'start|acceptQuest|claimQuest|upgradeBuilding|choose|return|abandon|pause|move|cast|potion|interact|wait'},ensure_ascii=False),
    'event_schema':json.dumps(event_schema),'visual_direction':'Reviewed original procedural Canvas dungeon and NPC camp scenes; articulated walking and reduced motion','audio_direction':'Reviewed original medieval score and procedural effects with original UI routing','controls':['WASD/arrows','pointer/touch','E interact/depart','R return','J quests','Escape pause'],
    'win_condition':'Defeat the fifth-floor boss, exit and settle victory','lose_condition':'Hero HP reaches zero; permanent camp remains','smoke_actions':['{"type":"start","seed":"embers","classId":"mage"}'],
    'affected_files':ALL,'acceptance_criteria':[s['purpose']for s in scenarios],'semantic_contract':contract,'qa_scenarios':scenarios}
encoded=json.dumps(spec,ensure_ascii=False,indent=2)+'\n'
if '--check' in sys.argv:
    if (HERE/'spec.json').read_text()!=encoded:raise SystemExit('Recorded camp specification differs from its reviewed declaration and action trace')
else:(HERE/'spec.json').write_text(encoded)
print(json.dumps({'scenarios':len(scenarios),'step_counts':{s['id']:len(s['steps'])for s in scenarios}}))
