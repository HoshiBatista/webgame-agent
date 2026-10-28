from copy import deepcopy

import pytest

from generation.artifacts import bundle, materialize
from generation.errors import ContractError
from generation.helpers import PATH, catalog
from generation.providers.fake import fixture_response
from validation.service import validate


def helper_game(script):
    response = fixture_response(with_assets=True)
    page = next(f for f in response["files"] if f["path"] == "index.html")
    page["content"] = page["content"].replace(
        '<script src="game.js">', '<script src="gf-motion-v1.js"></script><script src="game.js">'
    )
    game = next(f for f in response["files"] if f["path"] == "game.js")
    game["content"] += "\n" + script
    return materialize(response, operation="create", helper_catalog=catalog())


def test_full_helper_is_explicit_local_pinned_and_cannot_be_replaced():
    ordinary = materialize(fixture_response(), operation="create")
    assert PATH not in ordinary["files"]
    enabled = helper_game("")
    assert (
        PATH in enabled["files"]
        and "GameForgeMotion" in enabled["html"]
        and "<script src=" not in enabled["html"]
    )
    with pytest.raises(ContractError):
        bundle({**enabled["files"], PATH: "modified helper"})
    response = fixture_response()
    response["files"].append({"path": PATH, "content": "malicious"})
    with pytest.raises(ContractError):
        materialize(response, operation="create")


@pytest.mark.browser
@pytest.mark.parametrize(
    "case", ["drift", "zero", "cancel", "retarget", "overshoot", "reduced", "long_pause"]
)
def test_numeric_motion_contract_in_isolated_browser(case):
    scripts = {
        "drift": (
            "const t=GameForgeMotion.create({from:10,to:30,duration:1});t.advance(.25);t.advance(.25);window.sample=t.sample();",
            20,
        ),
        "zero": (
            "let n=0;const t=GameForgeMotion.create({from:1,to:2,duration:0,onComplete:()=>n++});t.advance(0);t.advance(2);window.sample=n*10+t.sample();",
            12,
        ),
        "cancel": (
            "let n=0;const t=GameForgeMotion.create({from:0,to:10,duration:1,onComplete:()=>n++});t.advance(.5);t.cancel();t.advance(3);t.reset();t.advance(1);window.sample=n;",
            0,
        ),
        "retarget": (
            "const a=GameForgeMotion.create({from:0,to:20,duration:1});a.advance(.5);a.cancel();const b=GameForgeMotion.create({from:a.sample(),to:30,duration:1});window.sample=b.advance(.5);",
            20,
        ),
        "overshoot": (
            "const t=GameForgeMotion.create({from:0,to:10,duration:1,easing:t=>t*3});window.sample=t.advance(.5);",
            15,
        ),
        "reduced": (
            "let n=0;const t=GameForgeMotion.create({from:0,to:10,duration:1,reducedMotion:true,onComplete:()=>n++});t.advance(.2);window.sample=t.sample()+n*100;",
            10,
        ),
        "long_pause": (
            "let n=0;const t=GameForgeMotion.create({from:0,to:10,duration:1,onComplete:()=>n++});t.advance(300);t.advance(300);window.sample=t.sample()+n*100;",
            110,
        ),
    }
    script, expected = scripts[case]
    game = helper_game(script)
    checks = deepcopy(game["checks"])
    checks.append(
        {
            "id": "helper_sample",
            "category": "regression",
            "requirement": "Числовой результат средства анимации соответствует контракту",
            "viewport": "mobile",
            "steps": [],
            "observation": {"source": "state", "path": "sample"},
            "expect": {"operator": "eq", "value": expected},
        }
    )
    report = validate(game["html"], checks, artifact_hash=game["artifact_hash"])
    assert report["status"] == "passed", report["findings"]


def test_compact_helper_version_is_checked_before_materializing_reply():
    from tests.test_compact_generation import compact_response

    with pytest.raises(ContractError, match="Версия"):
        materialize(compact_response(), operation="create", generation_profile="compact", helper_catalog={})


def test_opt_in_helper_does_not_hide_the_single_repairable_game_module():
    from generation.artifacts import sha256
    from generation.source_policy import module_policy

    game = helper_game("")
    permission = module_policy(game["files"], [{"code": "runtime_or_network"}])
    assert permission["files"] == {"game.js": sha256(game["files"]["game.js"])}
    assert PATH not in module_policy(game["files"], [{"code": "javascript_syntax", "path": PATH}])["files"]
    # A second actual gameplay module must still prevent an arbitrary replacement.
    assert (
        module_policy({**game["files"], "effects.js": "const effect=1;"}, [{"code": "runtime_or_network"}])[
            "files"
        ]
        == {}
    )
