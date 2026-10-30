import json
import time
from copy import deepcopy

import pytest

from generation.artifacts import bundle, materialize, sha256
from generation.errors import ContractError
from generation.experience import PATH, RECIPE, attach, provenance, validate
from generation.helpers import catalog, resolve
from generation.planning import schema
from generation.prompts import build_messages
from generation.providers.fake import fixture_assets, fixture_response


def game():
    response = fixture_response()
    response['assets'] = fixture_assets()
    return materialize(response, operation='create', helper_catalog=catalog())


def test_required_generated_assets_are_materialized_and_bound_to_version():
    result = game()
    assert RECIPE in result['files'] and PATH in result['files']
    assert result['files']['gf-assets/target.svg'] == fixture_assets()['graphics'][0]['svg']
    assert result['artifact_hash'] == sha256(bundle(result['files']))
    assert provenance(result['files'])['assets_origin'] == 'model_recipe'
    assert result['html'].index('id="gf-assets"') < result['html'].index('window.gameState=')
    with pytest.raises(ContractError, match='game-assets.json'):
        materialize(fixture_response(), operation='create', helper_catalog=catalog())


def test_generated_media_does_not_reduce_the_twenty_game_file_budget():
    from generation.artifacts import apply_patches, normalize_files

    response = fixture_response(with_assets=True)
    response['files'] += [{'path':f'extra{i}.css','content':'/* game style */'} for i in range(17)]
    graphic = response['assets']['graphics'][0]
    response['assets']['graphics'] += [{**graphic, 'id':f'image{i}'} for i in range(7)]
    result = materialize(response, operation='create', helper_catalog=catalog())
    assert len(result['files']) == 30
    with pytest.raises(ContractError, match='Размер'):
        apply_patches(result['files'], [{'path':'extra21.css','file_hash':None,'old_text':'','new_text':'body{}'}])
    with pytest.raises(ContractError, match='Размер'):
        normalize_files({f'file{i}.css':'body{}' for i in range(21)})
    tampered = {**result['files'], 'gf-assets/target.svg':'<svg/>'}
    with pytest.raises(ContractError, match='Размер'):
        normalize_files(tampered)


def test_declared_player_reference_is_attached_locally_without_regenerating_the_game():
    response = fixture_response(with_assets=True)
    page = next(f for f in response['files'] if f['path'] == 'index.html')
    original_script = next(f['content'] for f in response['files'] if f['path'] == 'game.js')
    page['content'] = page['content'].replace('<script src="game.js">', f'<script src="{PATH}"></script><script src="game.js">')
    result = materialize(response, operation='create', helper_catalog=catalog())
    assert result['files']['game.js'] == original_script
    assert result['html'].count('id="gf-assets"') == 1
    assert result['html'].index('id="gf-assets"') < result['html'].index('/* Generic synthesis')
    assert attach(result['files']) == result['files']


def test_full_assets_are_typed_and_not_json_inside_a_file_string():
    from generation.schema import response_schema, validate_response

    request = {'operation':'create', 'helper_catalog':catalog()}
    contract = response_schema(request)
    response = fixture_response(with_assets=True)
    assert 'assets' in contract['required']
    validate_response(response, schema=contract)
    response['assets'] = json.dumps(response['assets'])
    with pytest.raises(ContractError, match='формату'):
        validate_response(response, schema=contract)
    response['assets'] = fixture_assets()
    response['files'].append({'path':RECIPE, 'content':json.dumps(response['assets'])})
    with pytest.raises(ContractError):
        materialize(response, operation='create', helper_catalog=catalog())


def test_full_media_edit_changes_recipe_but_preserves_game_and_checks():
    base = game()
    response = fixture_response(with_assets=True)
    response.update(operation='edit', base_revision='v1', files=[], patches=[], checks=[])
    response['assets']['music']['bpm'] = 100
    edited = materialize(response, operation='edit', base_revision='v1', files=base['files'],
                         previous_checks=base['checks'], helper_catalog=catalog())
    assert edited['files']['game.js'] == base['files']['game.js']
    assert edited['checks'] == base['checks']
    assert json.loads(edited['files'][RECIPE])['music']['bpm'] == 100
    assert edited['design']['assets']['recipe_sha256'] != base['design']['assets']['recipe_sha256']


def test_full_source_repair_cannot_replace_assets_or_patch_their_serialized_source():
    from generation.artifacts import apply_patches
    from generation.schema import validate_response

    response = fixture_response(with_assets=True)
    response.update(operation='repair', base_revision='v1', files=[], patches=[], checks=[])
    with pytest.raises(ContractError, match='assets=null'):
        validate_response(response)
    response['assets'] = None
    validate_response(response)
    base = game()
    with pytest.raises(ContractError):
        apply_patches(base['files'], [{'path':RECIPE, 'file_hash':sha256(base['files'][RECIPE]),
                                      'old_text':'80', 'new_text':'100'}])
    from generation.source_policy import module_policy
    assert not module_policy(base['files'], [{'code':'runtime_or_network','path':RECIPE}])['files']


def test_compact_unchanged_cannot_carry_new_media():
    from generation.compact import validate_wire

    with pytest.raises(ContractError, match='пустыми'):
        validate_wire({'status':'unchanged','message':'Без изменений','edits':[], 'observations':[],
                       'probes':[], 'assets':fixture_assets()},
                      {'operation':'edit','helper_catalog':catalog()})


@pytest.mark.parametrize('profile', ['full', 'compact'])
def test_cancelled_fragment_correction_discards_pending_media_together_with_source_edits(profile):
    from generation.patch_repair import permission
    from tests.test_compact_generation import compact_response

    response = fixture_response(with_assets=True) if profile == 'full' else compact_response(with_assets=True)
    base = materialize(response, operation='create', generation_profile=profile, helper_catalog=catalog())
    assets = fixture_assets()
    assets['music']['bpm'] = 100
    if profile == 'full':
        response.update(operation='edit', base_revision='v1', files=[], checks=[], assets=assets, patches=[{
            'path':'styles.css', 'file_hash':sha256(base['files']['styles.css']),
            'old_text':'missing fragment', 'new_text':'new fragment'}])
    else:
        response = {'status':'ok','message':'Изменить музыку и цвет','observations':[], 'probes':[],
                    'edits':[{'old_text':'missing fragment', 'new_text':'new fragment'}], 'assets':assets}
    policy = permission(response, files=base['files'], base_revision='v1', profile=profile)
    reply = {'status':'unchanged','operation':'edit','base_revision':'v1','response_hash':policy['response_hash'],
             'message':'Невозможно надёжно применить эту правку','corrections':[]}
    result = materialize(reply, operation='edit', base_revision='v1', files=base['files'],
                         previous_checks=base['checks'], patch_repair=policy,
                         generation_profile=profile, compact_manifest=base.get('compact_manifest'), helper_catalog=catalog())
    assert result['status'] == 'unchanged'
    assert json.loads(base['files'][RECIPE])['music']['bpm'] != 100


@pytest.mark.parametrize('mutate', [
    lambda a: a['music']['notes'][0].update(instrument='missing'),
    lambda a: a['music']['notes'][0].update(beat=8),
    lambda a: a['sounds'][0].update(gain=5),
    lambda a: a['instruments'].append(deepcopy(a['instruments'][0])),
    lambda a: a.update(sounds=[], music=None),
])
def test_invalid_media_recipe_is_rejected_before_browser_or_model_retry(mutate):
    value = fixture_assets()
    mutate(value)
    with pytest.raises(ContractError):
        validate(value)


@pytest.mark.parametrize('svg', [
    '<svg viewBox="0 0 10 10"><script>alert(1)</script></svg>',
    '<svg viewBox="0 0 10 10"><image href="https://example.org/a"/></svg>',
    '<svg viewBox="0 0 10 10"><rect fill="url(https://example.org)"/></svg>',
    '<!DOCTYPE svg><svg viewBox="0 0 10 10"/>',
    '<svg viewBox="0 0 10 10" onload="alert(1)"/>',
    '<svg viewBox="0 0 Infinity 10"/>',
    '<svg viewBox="0 0 100000000 10"/>',
    '<svg viewBox="0 0 -10 10"/>',
    '<svg viewBox="0 0 10 10" width="100000000"/>',
])
def test_generated_svg_cannot_carry_code_or_remote_content(svg):
    value = fixture_assets()
    value['graphics'][0]['svg'] = svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ')
    with pytest.raises(ContractError):
        validate(value)


def test_media_is_preserved_during_unrelated_edit_and_not_in_repair_context_twice():
    base = game()
    response = fixture_response()
    response.update(operation='edit', base_revision='v1', files=[], checks=[], patches=[{
        'path': 'styles.css', 'file_hash': sha256(base['files']['styles.css']),
        'old_text': '#eff4ff', 'new_text': '#fff5e8',
    }])
    edited = materialize(response, operation='edit', base_revision='v1', files=base['files'],
                         previous_checks=base['checks'], helper_catalog=catalog())
    for path in [RECIPE, PATH, 'gf-assets/target.svg']:
        assert edited['files'][path] == base['files'][path]
    context = json.loads(build_messages({'operation':'edit', 'files':base['files'], 'helper_catalog':catalog()})[1]['content'])
    assert RECIPE not in context['files'] and context['assets'] == fixture_assets()
    assert PATH not in context['files'] and 'gf-assets/target.svg' not in context['files']


def test_plan_and_packaging_have_no_additional_model_stage():
    brief = schema({'helper_catalog':catalog()})['properties']['plan']['anyOf'][0]
    assert 'player_experience' in brief['required']
    started = time.monotonic()
    for _ in range(10):
        result = game()
    assert len(result['html'].encode()) < 60_000
    # A generous regression ceiling for pure local packaging, not a latency SLA.
    assert time.monotonic() - started < 5


def test_helper_bytes_and_derived_assets_are_not_model_editable():
    with pytest.raises(ContractError):
        resolve({PATH:'tampered'})
    result = game()
    from generation.artifacts import apply_patches
    with pytest.raises(ContractError):
        apply_patches(result['files'], [{'path':'gf-assets/target.svg',
            'file_hash':sha256(result['files']['gf-assets/target.svg']), 'old_text':'#5879e8', 'new_text':'red'}])


def test_compact_requires_the_exact_frozen_helper_and_locks_assets_in_source_repair():
    from tests.test_compact_generation import compact_response

    frozen = catalog()
    frozen[PATH]['sha256'] = '0' * 64
    with pytest.raises(ContractError, match='Версия'):
        materialize(compact_response(with_assets=True), operation='create', generation_profile='compact', helper_catalog=frozen)
    from generation.compact import validate_wire
    with pytest.raises(ContractError, match='assets=null'):
        validate_wire({'status':'ok','message':'repair','edits':[], 'assets':fixture_assets()},
                      {'operation':'repair','helper_catalog':catalog()})


def test_helpers_and_assets_cannot_disguise_a_missing_game_implementation():
    response = fixture_response(with_assets=True)
    next(f for f in response['files'] if f['path']=='game.js')['content'] = '// no implementation'
    with pytest.raises(ContractError, match='исполняемой реализации'):
        materialize(response, operation='create', helper_catalog=catalog())


def test_compact_media_edit_preserves_mechanics_and_scenarios():
    from tests.test_compact_generation import compact_response

    base = materialize(compact_response(with_assets=True), operation='create', generation_profile='compact', helper_catalog=catalog())
    assets = fixture_assets()
    assets['music']['bpm'] = 100
    edited = materialize({'status':'ok','message':'Ускорена музыка','edits':[], 'observations':[], 'probes':[], 'assets':assets},
        operation='edit', files=base['files'], previous_checks=base['checks'], generation_profile='compact',
        compact_manifest=base['compact_manifest'], helper_catalog=catalog())
    assert edited['files']['game.js'] == base['files']['game.js']
    assert edited['checks'] == base['checks']
    assert edited['compact_manifest']['assets']['music']['bpm'] == 100
    assert edited['design']['assets']['recipe_sha256'] != base['design']['assets']['recipe_sha256']


def test_missing_keyboard_coverage_repairs_only_checks_and_preserves_every_asset():
    from generation.check_repair import needs_check_repair, permission
    from validation.contracts import suite_findings

    base = game()
    findings = suite_findings(base['checks'], require_keyboard=True)
    assert needs_check_repair(base['checks'], findings)
    policy = permission(base['artifact_hash'], base['checks'], base['design'])
    keyboard = deepcopy(fixture_response(with_assets=True)['checks'][-1])
    keyboard.update(policy['requirements'][-1])
    proposal = {'status':'ok', 'operation':'check_repair', 'message':'Добавлена проверка клавиатуры',
                'base_revision':'base', 'artifact_hash':base['artifact_hash'], 'checks_hash':policy['checks_hash'],
                'checks':base['checks']+[keyboard]}
    fixed = materialize(proposal, operation='check_repair', base_revision='base', files=base['files'],
                        previous_checks=base['checks'], check_repair=policy)
    assert fixed['files'] == base['files'] and fixed['artifact_hash'] == base['artifact_hash']
    assert not suite_findings(fixed['checks'], require_keyboard=True)
    proposal['checks'][-1]['steps'] = [{'action':'click','selector':'#arena','x':150,'y':150}]
    with pytest.raises(ContractError, match='клавиатуры'):
        materialize(proposal, operation='check_repair', base_revision='base', files=base['files'],
                    previous_checks=base['checks'], check_repair=policy)


def test_batched_keyboard_coverage_is_combined_without_false_missing_coverage():
    from tests.test_artifact_evidence import valid_report
    from validation.suites import combine

    checks = fixture_response(with_assets=True)['checks']
    checks += [dict(checks[0], id=f'extra{i}') for i in range(9)]
    reports = []
    for group in (checks[:12], checks[12:]):
        report = valid_report()
        report.update(facts=[dict(c, status='passed') for c in group], findings=[{'code':'missing_keyboard_control'}])
        reports.append(report)
    combined = combine(checks, reports, artifact_hash='hash')
    assert combined['status'] == 'passed'
    assert not combined['findings']


@pytest.mark.parametrize('kind', ['tap', 'tap_fraction'])
def test_touch_on_desktop_is_a_scenario_error_not_a_game_or_browser_failure(kind):
    from validation.runner import InvalidCheck, action

    with pytest.raises(InvalidCheck, match='сенсорного'):
        action(None, None, {'action':kind}, touch_enabled=False)


@pytest.mark.parametrize('viewport', ['mobile', 'landscape', 'desktop'])
def test_compiler_accepts_landscape_scenarios_and_rotation(viewport):
    from validation.check_program import compile_check

    scenario = deepcopy(fixture_response(with_assets=True)['checks'][1])
    scenario.update(category='regression', viewport=viewport,
                    steps=[{'action':'resize','viewport':'landscape'}])
    assert compile_check(scenario).issue is None


@pytest.mark.browser
@pytest.mark.native_browser
@pytest.mark.parametrize('profile', ['full', 'compact'])
def test_native_generated_game_has_three_device_profiles_and_real_keyboard_coverage(profile):
    from generation.compact import validation_contract
    from tests.test_compact_generation import compact_response
    from validation.service import validate as check

    response = fixture_response(with_assets=True) if profile == 'full' else compact_response(with_assets=True)
    result = materialize(response, operation='create', generation_profile=profile, helper_catalog=catalog())
    rotation = deepcopy(result['checks'][1])
    rotation.update(id='rotate', category='regression')
    rotation['steps'] += [{'action':'checkpoint'}, {'action':'resize','viewport':'landscape'}]
    rotation['expect'] = {'operator':'unchanged', 'value':None}
    result['checks'].append(rotation)
    contract = validation_contract(result['compact_manifest'], result['files']) if profile == 'compact' else None
    report = check(result['html'], result['checks'], artifact_hash=result['artifact_hash'], contract=contract)
    assert report['status'] == 'passed', report['findings']
    assert {v['viewport'] for v in report['artifact_evidence']['viewports']} == {'mobile','landscape','desktop'}
    desktop = [f for f in report['facts'] if f['viewport']=='desktop']
    assert any(f['player_experience']['keyboardOnly'] for f in desktop)


@pytest.mark.browser
def test_real_audio_mute_restart_graphics_and_input_in_both_engines():
    from playwright.sync_api import sync_playwright

    files = attach({'index.html': '<!doctype html><body><button id="left">Left</button><canvas id="c" width="100" height="100"></canvas><script>window.count=0;window.edges=[];const binding=GameForgeExperience.bindInput([{id:"left",keys:["KeyA","ArrowLeft"],selector:"#left"}], e=>{edges.push(e);if(e.phase==="down"){count++;GameForgeExperience.sound("hit")}});const ctx=c.getContext("2d");function draw(){GameForgeExperience.draw(ctx,"target",0,0,100,100);requestAnimationFrame(draw)}draw();</script>',
                    RECIPE: json.dumps(fixture_assets())})
    html = bundle(files)
    with sync_playwright() as pw:
        for engine in [pw.chromium, pw.webkit]:
            browser = engine.launch()
            page = browser.new_page(viewport={'width':390,'height':844}, has_touch=True)
            page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=html))
            page.goto('http://fixture.test/')
            errors=[]
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.wait_for_function('GameForgeExperience.inspect().drawCalls>0')
            page.locator('#left').tap()
            page.wait_for_function('GameForgeExperience.inspect().state==="running"')
            assert page.evaluate('count') == 1
            page.wait_for_function('GameForgeExperience.inspect().peak>.001')
            page.locator('#left').focus()
            page.keyboard.press('Enter')
            assert page.evaluate('count') == 2
            page.keyboard.down('a')
            page.keyboard.down('ArrowLeft')
            page.keyboard.up('a')
            assert page.evaluate('edges.at(-1).phase') == 'down'
            page.keyboard.up('ArrowLeft')
            assert page.evaluate('edges.at(-1).phase') == 'up'
            page.evaluate('GameForgeExperience.setMuted(true)')
            page.wait_for_timeout(100)
            assert page.evaluate('GameForgeExperience.inspect().peak') < .001
            count=page.evaluate('count')
            page.set_viewport_size({'width':844,'height':390})
            assert page.evaluate('count') == count
            assert page.locator('#gf-player-tools button').bounding_box()['height'] >= 48
            page.evaluate('GameForgeExperience.setMuted(false);GameForgeExperience.stopMusic();GameForgeExperience.startMusic();GameForgeExperience.startMusic()')
            page.wait_for_timeout(350)
            data=page.evaluate('GameForgeExperience.inspect()')
            assert data['musicPlaying'] and data['activeVoices'] <= 16 and not data['audioError']
            assert not errors
            browser.close()


@pytest.mark.browser
def test_first_music_note_is_not_dropped_or_duplicated_and_stopping_music_keeps_effects():
    from playwright.sync_api import sync_playwright

    assets = fixture_assets()
    assets['music'].update(bpm=60, beats=8)
    assets['music']['notes'] = [dict(assets['music']['notes'][0], beat=beat, duration=.25) for beat in (0, 2, 4, 6)]
    assets['sounds'][0]['duration'] = 1
    html = bundle(attach({'index.html':'<!doctype html><button>Start</button>', RECIPE:json.dumps(assets)}))
    with sync_playwright() as pw:
        for engine in (pw.chromium, pw.webkit):
            browser = engine.launch()
            page = browser.new_page()
            page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=html))
            page.goto('http://fixture.test/')
            page.locator('body > button').click()
            page.wait_for_function('GameForgeExperience.inspect().state === "running"')
            page.wait_for_timeout(200)
            assert page.evaluate('GameForgeExperience.inspect().voicesPlayed') == 1
            page.evaluate('GameForgeExperience.startMusic();GameForgeExperience.startMusic()')
            assert page.evaluate('GameForgeExperience.inspect().voicesPlayed') == 1
            page.evaluate('GameForgeExperience.sound("hit");GameForgeExperience.stopMusic()')
            assert page.evaluate('GameForgeExperience.inspect().activeVoices') == 1
            page.wait_for_function('GameForgeExperience.inspect().peak > .001')
            browser.close()


@pytest.mark.browser
def test_compact_physical_control_names_keep_logical_key_events_for_game_code():
    from playwright.sync_api import sync_playwright

    from tests.test_compact_generation import compact_response

    response = compact_response('''GameForge.register(api=>{const state={events:[]};return {state,
      input(e){if(e.type==='key')state.events.push(e.key+':'+e.action+':'+e.phase)},
      render(ctx){ctx.fillStyle='#249';ctx.fillRect(0,0,api.width,api.height)}}});''', with_assets=True)
    response['controls'] = [{'id':'restart','key':'KeyR','label':'Заново'},
                            {'id':'card1','key':'Digit1','label':'1'},
                            {'id':'jump','key':'Space','label':'Прыжок'}]
    response['probes'] = []
    game = materialize(response, operation='create', generation_profile='compact', helper_catalog=catalog())
    with sync_playwright() as pw:
        for engine in (pw.chromium, pw.webkit):
            browser = engine.launch()
            page = browser.new_page()
            page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=game['html']))
            page.goto('http://fixture.test/')
            for key in ('r','1','Space'):
                page.keyboard.press(key)
            assert page.evaluate('gfState.events') == ['r:restart:down','r:restart:up',
                '1:card1:down','1:card1:up',' :jump:down',' :jump:up']
            browser.close()


@pytest.mark.browser
def test_wrong_graphic_calls_report_a_concrete_defect_instead_of_silently_hiding_assets():
    from playwright.sync_api import Error, sync_playwright

    html = bundle(attach({'index.html':'<!doctype html><canvas id="scene"></canvas>',
                         RECIPE:json.dumps(fixture_assets())}))
    with sync_playwright() as pw:
        for engine in (pw.chromium,pw.webkit):
            browser=engine.launch()
            page=browser.new_page()
            page.route('**/*',lambda route:route.fulfill(content_type='text/html',body=html))
            page.goto('http://fixture.test/')
            with pytest.raises(Error,match='pass the Canvas context'):
                page.evaluate("GameForgeExperience.draw('target',0,0,10,10)")
            with pytest.raises(Error,match='Unknown generated graphic'):
                page.evaluate("GameForgeExperience.draw(document.querySelector('canvas').getContext('2d'),'missing',0,0,10,10)")
            page.evaluate("GameForgeExperience.ready.then(()=>GameForgeExperience.draw(document.querySelector('canvas').getContext('2d'),'target',0,0,10,10))")
            assert page.evaluate('GameForgeExperience.inspect().drawCalls') == 1
            browser.close()
