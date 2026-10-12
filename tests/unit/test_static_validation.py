"""Static validation rule tests."""

from prompt2play.validation.static import validate_html

VALID_GAME = """<!doctype html>
<html><body><canvas id="game"></canvas><button>Начать</button><button>Заново</button>
<script>
window.__prompt2play={}; addEventListener('pointerdown',()=>{}); addEventListener('resize',()=>{});
const ratio=devicePixelRatio; function loop(){requestAnimationFrame(loop)}; loop();
</script></body></html>"""


def test_valid_self_contained_game_passes_static_rules() -> None:
    findings, checks = validate_html(VALID_GAME)
    assert findings == []
    assert "тестовый bridge" in checks
    assert "remote_resource" in checks


def test_remote_and_dangerous_game_is_rejected() -> None:
    findings, _ = validate_html(
        VALID_GAME.replace("</script>", "fetch('https://tracker.test'); eval('1')</script>")
    )
    assert {item.code for item in findings} == {"REMOTE_RESOURCE", "DANGEROUS_EXECUTION"}


def test_missing_runtime_contract_has_actionable_findings() -> None:
    findings, _ = validate_html("<html><script>alert('x')</script></html>")
    codes = {item.code for item in findings}
    assert "DOCTYPE_MISSING" in codes
    assert "TEST_BRIDGE_MISSING" in codes
    assert "BLOCKING_DIALOG" in codes
