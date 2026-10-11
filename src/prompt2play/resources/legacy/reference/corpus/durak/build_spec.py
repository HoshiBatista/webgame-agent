#!/usr/bin/env python3
"""Explicit semantics for a complete recorded game, never a genre template."""
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ALL=['engine.js','renderer.js','audio.js','ui.js']
RULES=['engine.js','ui.js']
def act(type,**kw):return {'op':'act','action':{'type':type,**kw}}
def capture(key):return {'op':'capture','key':key}
def check(path,value=None,*,saved=None,cmp='eq'):
    return {'op':'assert','left':{'path':path},'cmp':cmp,'right':{'saved':saved,'path':path}if saved else{'value':value}}
def case(id,category,purpose,steps,seed='corpus-durak-1',files=RULES):
    return {'id':id,'category':category,'purpose':purpose,'seed':seed,
        'steps':[json.dumps(x,ensure_ascii=False,separators=(',',':'))for x in steps],
        'affected_files':files,'limitations':['Recorded developer-authored game and legal moves, not live generation','DOM models and rule scenarios do not establish native browser layout, WebView or subjective audio quality']}
start=act('start',playerCount=2)
first=[act('attack',card='S6'),act('stepBot'),act('attack',card='H7'),act('stepBot'),act('pass'),act('continue')]
scenarios=[
    case('durak-first-bout','progress','Play a complete first bout, settle it once, retain all36 cards and continue to the next attack',[
        start,check('/position/actor',0),*first,check('/position/round',2),check('/totalCards',36),capture('settled'),
        {'op':'act','action':{'type':'continue'},'repeat':3},check('/position',saved='settled')]),
    case('durak-voluntary-take','strategy','A human may choose take even with a legal defense; throwing and pickup settle once',[
        start,act('stepBot'),check('/position/actor',0),check('/position/phase','defend'),
        check('/position/legalActions/0/type','defend'),act('take'),check('/position/taking',True),
        act('stepBot'),check('/position/phase','roundEnd'),act('continue'),check('/position/round',2),check('/totalCards',36),
        capture('picked'),{'op':'act','action':{'type':'continue'},'repeat':2},check('/position',saved='picked')],seed='durak-review'),
    case('durak-pause','lifecycle','Paused inputs do not consume cards; resuming permits the same legal attack',[
        start,act('pause',value=True),capture('paused'),act('attack',card='S6'),check('/position',saved='paused'),
        act('pause',value=False),act('attack',card='S6'),check('/position/revision',1),check('/totalCards',36)]),
    case('durak-save-roundtrip','persistence','Restore a real save after legal progress and replay the same continuation to the same public position',[
        start,first[0],capture('before'),{'op':'serialize','key':'checkpoint'},*first[1:4],
        capture('continued'),check('/position',saved='before',cmp='ne'),
        {'op':'restore','saved':'checkpoint','expect':'accepted'},check('/position',saved='before'),
        *first[1:4],check('/position',saved='continued'),check('/totalCards',36)]),
    case('durak-import-rejection','persistence','Malformed or incompatible saves cannot replace the live card position',[
        start,first[0],capture('live'),{'op':'restore','text':'','expect':'rejected'},check('/position',saved='live'),
        {'op':'restore','text':'{','expect':'rejected'},check('/position',saved='live'),
        {'op':'restore','text':'{"format":999,"state":{}}','expect':'rejected'},check('/position',saved='live')]),
    case('durak-page-lifecycle','lifecycle','Hidden input is rejected and remount restores the actual saved position without resetting a deal',[
        start,first[0],capture('saved'),{'op':'lifecycle','event':'hide'},act('stepBot'),check('/position',saved='saved'),
        {'op':'lifecycle','event':'show'},act('stepBot'),check('/position/revision',2),capture('resumed'),
        {'op':'lifecycle','event':'remount'},check('/position',saved='resumed'),check('/paused',False)],files=ALL),
    case('durak-storage-unavailable','persistence','Actual quota and denied storage leave accepted card moves in memory and show truthful save status',[
        {'op':'storage_fault','mode':'quota'},start,check('/persistence/status','memory'),first[0],check('/position/revision',1),
        {'op':'storage_fault','mode':'normal'},first[1],check('/persistence/status','saved'),
        {'op':'storage_fault','mode':'denied'},first[2],check('/position/revision',3),check('/persistence/status','memory'),
        {'op':'storage_fault','mode':'normal'},check('/totalCards',36)],files=['ui.js']),
    case('durak-settlement-once','accounting','A settled table cannot be credited or drawn a second time by a repeated continuation',[
        start,*first,capture('settled'),{'op':'act','action':{'type':'continue'},'repeat':3},
        check('/position',saved='settled'),check('/totalCards',36)]),
]
def field(id,path,type,meaning,example,owner='engine.js',consumers=None):
    return {'id':id,'path':path,'type':type,'unit':'JSON game data','meaning':meaning,
        'owner':owner,'consumers':['renderer.js','ui.js']if consumers is None else consumers,'example_json':json.dumps(example)}
fields=[
    field('human-observation','/position','object','Null in the menu; otherwise a fresh viewer0 observation with public board/counts and only the human hand and legal actions. No seed, opponent hands or deck order.',{'phase':'attack','actor':0,'hand':['S6'],'players':[{'id':0,'count':6},{'id':1,'count':6}]}),
    field('paused','/paused','boolean','Transient pause belongs to the live controller; it is not restored from a previous mount.',False,owner='ui.js',consumers=['engine.js']),
    field('card-total','/totalCards','integer','Read-only sum of cards in hands, draw pile, board and discard; always36.',36),
    field('action-events','/events','array','Presentation event records with session/revision IDs; never a source of card accounting.',[],consumers=['audio.js','ui.js']),
    field('save-status','/persistence/status','string','Actual UI persistence result: empty, saved, memory, or conflict. Conflicts preserve live play.', 'saved',owner='ui.js',consumers=[]),
]
event_types=['deal','attack','defend','take','pass','continue','win','lose']
event_schema={'type':'object','properties':{'id':{'type':'string'},'type':{'enum':event_types}},'required':['id','type'],'additionalProperties':False}
contract={
    'version':3,'timing':{'mode':'turn_based','step_action':'{}','step_seconds':0,'max_catchup_steps':0,
        'pause_policy':'Only one authorized card decision or settlement changes the position. UI delays affect presentation and bot scheduling; hidden/manual pause cancels pending work.'},
    'fields':fields,'events':[{'type':kind,'payload_schema':json.dumps(event_schema),'example_json':json.dumps({'id':'1:1','type':kind}),
        'delivery':'An accepted action replaces the event list. Music/effects cannot move cards; mute discards rather than delays effects.','owner':'engine.js','consumers':['audio.js','ui.js']}for kind in event_types],
    'state_machines':[{'id':'turn-protocol','owner':'engine.js','states':['attack','defend','roundEnd','finished'],
        'initial_state':'attack','terminal_states':['finished'],'transitions':[
            {'from':'attack','to':'defend','trigger':'legal attack','effect':'Move one actor-owned card to the table; defender decides'},
            {'from':'defend','to':'attack','trigger':'legal defense or voluntary take','effect':'Cover the chosen attack or commit irreversible taking; original attacker regains priority'},
            {'from':'attack','to':'attack','trigger':'legal throw after take or pass','effect':'Respect fixed defender-start attack limit and table rank set'},
            {'from':'attack','to':'roundEnd','trigger':'all attackers pass or fixed limit reached','effect':'Freeze complete visible bout and clear actor'},
            {'from':'roundEnd','to':'attack','trigger':'continue','effect':'Move table exactly once, draw attacker-first and defender-last, select next active neighbors'},
            {'from':'roundEnd','to':'finished','trigger':'continue with terminal remaining hands','effect':'Set single remaining durak or genuine all-empty draw only after settlement'}]}],
    'resources':[{'name':'mounted-session','owner':'ui.js','acquire':'Mount one DOM session and listeners; lazy audio context after activation',
        'release':'Destroy cancels bot timeout, removes listeners and closes audio; remount reads current valid localStorage',
        'stale_work_policy':'Check session, revision and independent task ticket before touching the active timer handle. Reconcile resume/suspend completion against the current desired state.'},
        {'name':'audio-session','owner':'audio.js','acquire':'GameAudio receives the UI-owned context and creates independent music/SFX buses; track and bound each entire effect chain to32 active sources',
        'release':'Mute/hide cancel sources and disconnect chains; dispose releases buses without closing the supplied context',
        'stale_work_policy':'Discard muted/suspended-context events, bounded ID deduplication and no replay; UI resource owner reconciles both late resume and late suspend'}],
    'invariants':[
        {'id':'card-conservation','statement':'Each of36 rank/suit cards exists in exactly one hand, deck, table slot or discard.', 'owners':RULES,'check_strategy':'Independent identity multiset after every public action in a finite full-match matrix; verify the original validator too'},
        {'id':'actor-isolation','statement':'Only the current actor chooses; each bot receives its own copied filtered observation, never full game state.', 'owners':RULES,'check_strategy':'Assert no deck order/seed/opponent hands, copied view mutation isolation, and legality of every chosen bot action'},
        {'id':'take-is-irreversible','statement':'Taking is a legal voluntary defense alternative; further throws stay bounded and the entire board moves once.', 'owners':RULES,'check_strategy':'A human chooses take while legal defenses exist, then legal throw/pass/settlement and repeated-continue rejection'},
        {'id':'focus-identity','statement':'Selected card, focused control and original modal opener have separate lifetimes.', 'owners':['ui.js','renderer.js'],'check_strategy':'Original reviewed DOM handlers retained; focused integration smoke remains separate from a browser layout claim'}],
    'state_domains':[
        {'id':'domain-match','owner':'engine.js','field_ids':['human-observation'],'lifetime':'persistent','reset_policy':'Explicit newGame creates one new shuffled deal; full hidden position is authoritative in GameEngine.state','preserve_policy':'Serialize validated36-card state, including actor, priority, phase, limit and committed taking; UI sees only derived observation'},
        {'id':'domain-derived','owner':'engine.js','field_ids':['card-total'],'lifetime':'derived','reset_policy':'Recompute from authoritative state','preserve_policy':'No independent accounting copy'},
        {'id':'domain-events','owner':'engine.js','field_ids':['action-events'],'lifetime':'action','reset_policy':'Accepted action/reinitialization replaces or clears event list','preserve_policy':'Never restore audio or settle cards from historical event replay'},
        {'id':'domain-ui','owner':'ui.js','field_ids':['paused','save-status'],'lifetime':'session','reset_policy':'New mount resets transient pause and reads actual saved bytes','preserve_policy':'Failed writes leave playable state in memory with truthful status'}],
    'transactions':[{'id':'tx-settlement','owner':'engine.js','action_json':'{"type":"continue"}','domain_ids':['domain-match'],
        'preconditions':['phase is roundEnd and actor is null','All36 unique cards and phase relations validate'],
        'commit':['Move the entire board once to discard or defender','Draw in specified order','Mark empty-deck players out and assign next turn or terminal outcome'],
        'rejection_policy':'No state mutation outside roundEnd','repeat_policy':'Repeated continue in the next phase is rejected without another pickup or draw','scenario_ids':['durak-settlement-once']}],
    'progression':[],
    'persistence':[{'id':'save-match','owner':'ui.js','domain_ids':['domain-match'],'storage':'local_storage','format_version':'format1 with original Durak schemaVersion1',
        'validation_rules':['Bounded JSON before manual import','Exactly36 unique cards; real rank/suit identities and bottom trump','Validate actor/neighbor, card ownership, table-rank sequence, beats, pass priority, limit and terminal relations'],
        'migration_policy':'Only supported current format accepted; corrupt or unknown versions cannot replace the live game',
        'write_policy':'One complete envelope after accepted actions; explicit newGame may claim the slot; no teardown write',
        'conflict_policy':'Compare actual serialized durable bytes to observed baseline; sticky conflict preserves this live branch. This is best effort, not an atomic cross-tab CAS.',
        'failure_policy':'Quota/denied or a changed slot leaves in-memory play and reports memory/conflict; rejected manual import preserves state',
        'scenario_ids':['durak-save-roundtrip','durak-import-rejection','durak-storage-unavailable']}],
    'first_playable_loop':{'description':'A human attacks, bots respond and a full bout settles to the next legal round with all cards conserved','scenario_id':'durak-first-bout'},
    'review_obligations':[
        {'id':'review-turns','kind':'decision_protocol','owners':RULES,'contract_ids':['turn-protocol','tx-settlement','actor-isolation'],'scenario_ids':['durak-first-bout','durak-voluntary-take'],'limitations':[]},
        {'id':'review-information','kind':'information_boundary','owners':RULES,'contract_ids':['actor-isolation','human-observation'],'scenario_ids':[], 'limitations':['A specialized privileged full-state reference oracle checks every filtered bot input; the public QA bridge does not expose hidden hands.']},
        {'id':'review-alternative','kind':'alternative_choice','owners':RULES,'contract_ids':['take-is-irreversible'],'scenario_ids':['durak-voluntary-take'],'limitations':[]},
        {'id':'review-deferred','kind':'deferred_task','owners':['ui.js'],'contract_ids':['resource:mounted-session'],'scenario_ids':['durak-page-lifecycle'],'limitations':['Independent stale callbacks are additionally invoked in a controlled exact-HTML timer model; synthetic hide/show is not operating-system backgrounding.']},
        {'id':'review-conflict','kind':'durable_conflict','owners':['ui.js'],'contract_ids':['save-match'],'scenario_ids':[], 'limitations':['Specialized exact-HTML two-document shared-storage test; no cross-process atomicity claim.']},
        {'id':'review-focus','kind':'focus','owners':['renderer.js','ui.js'],'contract_ids':['focus-identity'],'scenario_ids':[], 'limitations':['Original reviewed focus handlers retained; exact-HTML focused-control integration uses explicit DOM focus model rather than native keyboard/layout.']},
        {'id':'review-audio','kind':'async_audio','owners':['audio.js','ui.js'],'contract_ids':['resource:audio-session','resource:mounted-session'],'scenario_ids':[], 'limitations':['Specialized deferred-resume model verifies mute reconciliation on exact HTML; real device audio and BFCache are not exercised.']}],
}
spec={'title':'Дурак · полный записанный корпус','summary':'Complete reviewed Durak1.0.1, adapted to Forge without changing its rules; this is recorded source, not model-generated quality evidence.',
    'genre':'2–4-player card game, one human and computer opponents','presentation_mode':'dom',
    'rules':['36 cards, ranks6 through ace, one bottom trump drawn last','2–4 seats; one human, others computers','Ordinary throwing Durak; no transfers, teams or trump-six swap','Fixed min(6, starting defender hand) attack limit','Original attacker gets throw priority; defender draws last','Human may voluntarily take; taking cannot be cancelled','Only final settlement declares remaining durak or genuine all-empty draw'],
    'state_schema':json.dumps({f['path']:f['meaning']for f in fields},ensure_ascii=False),
    'action_schema':json.dumps({'type':'object','properties':{'type':{'enum':['start','attack','defend','take','pass','continue','stepBot','pause']},'card':{'type':'string'},'target':{'type':'integer'},'seed':{'type':'string'},'playerCount':{'enum':[2,3,4]},'value':{'type':'boolean'}},'required':['type'],'additionalProperties':False}),
    'event_schema':json.dumps(event_schema),'visual_direction':'Full original responsive emerald/ivory DOM table, procedural SVG card faces, card-motion CSS and reduced-motion media query; no bitmap assets or fake Canvas.',
    'audio_direction':'Original short synthesized card/deal/outcome effects; no ambient music. Mute/hide cancels complete effect chains and never replays suspended events.',
    'controls':['Pointer/touch selects a card then plays it','Keyboard Tab/Enter and Escape','Take or stop throwing buttons','2–4 participant selector, rules, new game, sound and quick tempo'],
    'win_condition':'The human exits with no cards after the deck is empty; bot play continues to a final table outcome',
    'lose_condition':'The human is the sole remaining hand at final settlement',
    'smoke_actions':['{"type":"start","seed":"corpus-durak-1","playerCount":2}','{"type":"attack","card":"S6"}','{"type":"stepBot"}'],
    'affected_files':ALL,'acceptance_criteria':[s['purpose']for s in scenarios],'semantic_contract':contract,'qa_scenarios':scenarios}
encoded=json.dumps(spec,ensure_ascii=False,indent=2)+'\n'
if '--check'in sys.argv:
    if (HERE/'spec.json').read_text()!=encoded:raise SystemExit('Durak spec differs from the authored declaration')
else:(HERE/'spec.json').write_text(encoded)
print(json.dumps({'scenarios':len(scenarios),'step_counts':{s['id']:len(s['steps'])for s in scenarios}}))
