import pytest

from generation.artifacts import materialize
from generation.providers.fake import fixture_response
from generation.visual import FRAME_IDS, contact_sheet, decode
from tests.test_motion_helper import helper_game
from validation.contracts import browser_watchdog_seconds
from validation.service import validate


def test_visual_replay_has_an_explicit_watchdog_allowance():
    checks = fixture_response()["checks"]
    assert browser_watchdog_seconds(checks, capture_visual=True) == browser_watchdog_seconds(checks) + 45


@pytest.mark.browser
def test_frames_are_real_bounded_and_bound_to_passed_game():
    game = materialize(fixture_response(), operation="create")
    result = validate(game["html"], game["checks"], artifact_hash=game["artifact_hash"], capture_visual=True)
    assert result["status"] == "passed", result["findings"]
    packet = result["visual_evidence"]
    assert packet["status"] == "captured", packet
    assert [f["id"] for f in packet["frames"]] == FRAME_IDS
    assert packet["artifact_hash"] == game["artifact_hash"] and packet["environment"] == result["environment"]
    assert packet["route"] and packet["route_id"] in {c["id"] for c in game["checks"]}
    assert "FPS" in packet["semantics"]
    assert packet["frames"][4]["captured_at_ms"] > packet["frames"][1]["captured_at_ms"]
    sheet = contact_sheet(packet, artifact_hash=game["artifact_hash"], environment=result["environment"])
    assert decode(sheet["data"], sheet["mime"]).size == (1200, 680)


@pytest.mark.browser
@pytest.mark.parametrize("defect", ["drift", "rounding"])
@pytest.mark.parametrize("fixed", [False, True])
def test_rendered_pixels_distinguish_broken_and_correct_transition_and_rounding(defect, fixed):
    setup = """const panel=document.createElement('canvas');panel.width=120;panel.height=90;
    panel.style.cssText='position:fixed;left:10px;top:600px;width:120px;height:90px;z-index:100';
    document.body.appendChild(panel);const pc=panel.getContext('2d');
    pc.fillStyle='white';pc.fillRect(0,0,120,90);pc.fillStyle='black';"""
    if defect == "drift":
        drawing = (
            "const tr=GameForgeMotion.create({from:10,to:90,duration:1});tr.advance(.25);const pos=tr.advance(.25);"
            if fixed
            else "let pos=10;pos+=(90-pos)*.25;pos+=(90-pos)*.5;"
        )
        drawing += "pc.fillRect(pos,20,12,24);"
        pixel = (10 + 52, 600 + 30)
    else:
        # The earlier class of error mixed x/y when calculating a curved corner.
        drawing = (
            "pc.beginPath();pc.roundRect(20,35,70,40,12);pc.fill();"
            if fixed
            else "pc.beginPath();pc.moveTo(32,35);pc.lineTo(78,35);pc.quadraticCurveTo(90,20,90,47);pc.lineTo(90,75);pc.lineTo(20,75);pc.lineTo(20,47);pc.quadraticCurveTo(20,20,32,35);pc.fill();"
        )
        pixel = (10 + 23, 600 + 36)
    game = helper_game(setup + drawing)
    result = validate(game["html"], game["checks"], artifact_hash=game["artifact_hash"], capture_visual=True)
    assert result["status"] == "passed", result["findings"]
    packet = result["visual_evidence"]
    assert packet["status"] == "captured", packet
    first = packet["frames"][0]
    image = decode(first["data"], first["mime"])
    intensity = sum(image.getpixel(pixel)) / 3
    # Drift: the fixed object covers the expected midpoint. Rounding: the fixed
    # native primitive leaves the outside of its top-left corner white.
    if defect == "drift":
        assert (intensity < 80) == fixed, (fixed, intensity)
    else:
        assert (intensity > 175) == fixed, (fixed, intensity)
