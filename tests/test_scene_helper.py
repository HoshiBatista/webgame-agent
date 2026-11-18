import pytest

from generation.artifacts import apply_patches, bundle, materialize
from generation.errors import ContractError
from generation.helpers import catalog, used
from generation.pro_staged import source_prompt
from generation.providers.fake import fixture_response
from generation.scene import PATH, SOURCE
from tests.test_pro_staged import staged


def scene_game():
    reply = fixture_response(with_assets=True)
    files = {
        'index.html': f'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0}} canvas{{transform:scale(.85)}}</style></head>
<body><main data-gf-scene><header data-gf-hud id="status">Старт</header>
<canvas data-gf-field id="field"></canvas>
<nav data-gf-controls><button id="travel">К цели</button></nav></main>
<script src="{PATH}"></script><script src="game.js"></script></body></html>''',
        'game.js': """
const canvas = document.querySelector('#field');
const ctx = canvas.getContext('2d', {willReadFrequently:true});
const statusText = document.querySelector('#status');
const target = {x:1873, y:1311};
let focus = {x:0, y:0};
let camera;
function draw() {
  canvas.width = canvas.clientWidth * 2;
  canvas.height = canvas.clientHeight * 2;
  camera = GameForgeScene.view(canvas, {worldWidth:4000, worldHeight:3000, ...focus, zoom:1.5});
  if (!camera) return;
  camera.apply(ctx);
  ctx.fillStyle = '#ff0000';
  ctx.fillRect(target.x - 9, target.y - 9, 18, 18);
}
document.querySelector('#travel').onclick = () => {
  focus = target; statusText.textContent = 'Ищем цель'; draw();
};
canvas.onpointerdown = event => {
  const point = camera.point(event);
  const rect = canvas.getBoundingClientRect();
  const pixel = ctx.getImageData((event.clientX-rect.left)*canvas.width/rect.width,
                                 (event.clientY-rect.top)*canvas.height/rect.height, 1, 1).data;
  if (point && Math.abs(point.x-target.x)<9 && Math.abs(point.y-target.y)<9 && pixel[0]===255)
    statusText.textContent = 'Цель найдена';
};
new ResizeObserver(draw).observe(canvas);
draw();
""",
    }
    reply['files'] = [{'path': key, 'content': value} for key, value in files.items()]
    travel = {'action': 'tap', 'selector': '#travel', 'x': None, 'y': None}
    hit = {'action': 'tap_fraction', 'selector': '#field', 'x': .5, 'y': .5}
    reply['checks'] = [
        {'id': name, 'category': category, 'viewport': viewport, 'steps': steps,
         'requirement': description, 'observation': {'source': 'text', 'selector': '#status'},
         'expect': {'operator': 'eq', 'value': expected}}
        for name, category, viewport, steps, expected, description in [
            ('start', 'start', 'mobile', [], 'Старт', 'Игра готова к началу'),
            ('travel', 'control', 'mobile', [travel], 'Ищем цель', 'Кнопка переводит камеру к цели'),
            ('hit', 'outcome', 'mobile', [travel, hit], 'Цель найдена', 'Касание нарисованной цели засчитывается'),
            ('rotate', 'regression', 'mobile', [travel, {'action': 'resize', 'viewport': 'landscape'}, hit],
             'Цель найдена', 'После поворота экрана касание находит ту же цель'),
            ('wide', 'regression', 'landscape', [travel, hit], 'Цель найдена',
             'Боковая панель позволяет переместиться и попасть по цели'),
            ('click', 'control', 'desktop', [{**travel, 'action':'click'}, {**hit, 'action': 'click_fraction'}], 'Цель найдена',
             'На компьютере щелчок попадает по нарисованной цели'),
            ('keyboard', 'control', 'desktop', [{'action': 'press', 'key': 'Tab'}, {'action': 'press', 'key': 'Enter'}],
             'Ищем цель', 'Кнопка смены камеры доступна с клавиатуры'),
        ]
    ]
    return reply


def test_experiment_pins_scene_bytes_only_when_used():
    reply = scene_game()
    frozen = catalog(include_scene=True)
    assert PATH not in catalog()
    candidate = materialize(reply, operation='create', helper_catalog=frozen)
    assert candidate['files'][PATH] == SOURCE.read_text()
    assert used(candidate['files'])[PATH] == frozen[PATH]
    assert SOURCE.read_text() in bundle(candidate['files'])
    assert PATH not in materialize(fixture_response(with_assets=True), operation='create',
                                   helper_catalog=frozen)['files']
    with pytest.raises(ContractError, match='Версия'):
        materialize(reply, operation='create', helper_catalog=catalog())
    with pytest.raises(ContractError, match='Версия'):
        materialize(reply, operation='create', helper_catalog={**frozen, PATH: {'sha256': 'stale'}})
    with pytest.raises(ContractError, match='заменяться'):
        bundle({**candidate['files'], PATH: 'wrong'})
    with pytest.raises(ContractError, match='принадлежат приложению'):
        apply_patches(candidate['files'], [{'path': PATH}])


def test_only_pinned_new_experimental_scene_authors_receive_the_api():
    request, _, _ = staged()
    for role in ('scene', 'gameplay'):
        old = {**request, 'pro_parallel_branch': role}
        assert 'GameForgeScene.view' not in source_prompt(old)
        assert 'GameForgeScene.view' in source_prompt({**old, 'helper_catalog':catalog(include_scene=True)})


@pytest.mark.browser
@pytest.mark.native_browser
def test_following_camera_and_controls_survive_rotation_in_offline_export():
    from validation.service import validate

    candidate = materialize(scene_game(), operation='create', helper_catalog=catalog(include_scene=True))
    result = validate(candidate['html'], candidate['checks'], artifact_hash=candidate['artifact_hash'])
    assert result['status'] == 'passed', result.get('findings')
