import base64
import hashlib
import io
from copy import deepcopy

import pytest
from PIL import Image

from generation.artifacts import materialize
from generation.errors import ContractError
from generation.feedback_image import image_input
from generation.providers.fake import fixture_response
from generation.visual import FRAME_IDS, contact_sheet, decode, packet_hash, permitted_issues


def encoded_image(size=(390, 844), color="navy", fmt="JPEG"):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=fmt)
    return base64.b64encode(output.getvalue()).decode()


def packet(artifact="a" * 64, environment="test"):
    frames = []
    for index, ident in enumerate(FRAME_IDS):
        size = (1280, 800) if index == 5 else (390, 844)
        data = encoded_image(size)
        frames.append(
            {
                "id": ident,
                "viewport": "desktop" if index == 5 else "mobile",
                "size": dict(zip(["width", "height"], size)),
                "check_id": None if index == 5 else "tap",
                "action": None if index in {0, 5} else {"action": "tap", "selector": "canvas"},
                "captured_at_ms": index * 100,
                "capture_duration_ms": 20,
                "mime": "image/jpeg",
                "data": data,
                "sha256": hashlib.sha256(base64.b64decode(data)).hexdigest(),
            }
        )
    return {
        "version": 1,
        "status": "captured",
        "artifact_hash": artifact,
        "environment": environment,
        "route_id": "tap",
        "route": [{"action": "tap", "selector": "canvas"}],
        "frames": frames,
        "elapsed_seconds": 1,
        "semantics": "ordinary-time replay; capture timestamps do not measure FPS",
    }


def policy():
    return {
        "base_revision": "base",
        "artifact_hash": "a" * 64,
        "report_id": 1,
        "report_identity": "identity",
        "packet_hash": "p" * 64,
        "requirement_ids": ["presentation"],
        "paths": ["styles.css"],
    }


def review(binding=None, kind="reproducible_defect"):
    return {
        "operation": "visual_review",
        "status": "ok",
        "message": "Перекрываются игровые элементы",
        **{
            k: v
            for k, v in (binding or policy()).items()
            if k in ("base_revision", "artifact_hash", "report_id", "report_identity", "packet_hash")
        },
        "issues": [
            {
                "kind": kind,
                "defect": "overlap",
                "frames": ["action_before", "action_after"],
                "requirement_id": "presentation",
                "path": "styles.css",
                "observation": "Подпись пересекается с кнопкой",
                "expected": "Подпись и кнопка должны читаться раздельно",
                "minimal_fix": "Увеличить отступ подписи от кнопки",
            }
        ],
    }


@pytest.mark.parametrize("fault", ["artifact", "frame_hash", "corrupt", "size", "time", "frames"])
def test_invalid_packet_cannot_reach_contact_sheet(fault):
    value = packet()
    if fault == "artifact":
        value["artifact_hash"] = "wrong"
    if fault == "frame_hash":
        value["frames"][0]["sha256"] = "wrong"
    if fault == "corrupt":
        value["frames"][0]["data"] = base64.b64encode(b"fake").decode()
    if fault == "size":
        value["frames"][0]["size"]["width"] = 123
    if fault == "time":
        value["frames"][3]["captured_at_ms"] = -1
    if fault == "frames":
        value["frames"][0]["id"] = "invented"
    with pytest.raises(ValueError):
        contact_sheet(value, artifact_hash="a" * 64, environment="test")


def test_actual_decode_bounds_and_sheet_size():
    image = contact_sheet(packet(), artifact_hash="a" * 64, environment="test")
    assert len(base64.b64decode(image["data"])) <= 512 * 1024
    assert decode(image["data"], image["mime"]).size == (1200, 680)
    for value, mime in [
        (encoded_image((2049, 1)), "image/jpeg"),
        (encoded_image(fmt="PNG"), "image/jpeg"),
        (base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode(), "image/png"),
    ]:
        with pytest.raises(Exception):
            decode(value, mime)


def test_visual_image_binding_is_checked_again_before_provider_send():
    value = packet()
    sheet = contact_sheet(value, artifact_hash="a" * 64, environment="test")
    binding = {
        **policy(),
        "packet_hash": packet_hash(value),
        "sheet_hash": hashlib.sha256(base64.b64decode(sheet["data"])).hexdigest(),
    }
    request = {
        "operation": "visual_review",
        "generation_strategy": "pro",
        "base_revision": "base",
        "artifact_hash": "a" * 64,
        "visual_review": binding,
        "validation_evidence": {"artifact_hash": "a" * 64, "report_id": 1},
        "preview_image": {
            **sheet,
            **{
                k: binding[k]
                for k in ("base_revision", "artifact_hash", "report_id", "report_identity", "packet_hash")
            },
        },
    }
    assert image_input(request)
    for key in ("report_id", "base_revision", "artifact_hash", "report_identity", "packet_hash", "data"):
        changed = deepcopy(request)
        changed["preview_image"][key] = "forged"
        assert image_input(changed) is None


@pytest.mark.parametrize(
    "fault", ["taste", "suspected", "unknown_frame", "other_requirement", "helper", "motion_single"]
)
def test_vague_or_unbound_visual_comments_do_not_authorize_patch(fault):
    response = review()
    issue = response["issues"][0]
    if fault == "taste":
        issue["kind"] = "preference"
    if fault == "suspected":
        issue["kind"] = "suspected_defect"
    if fault == "unknown_frame":
        issue["frames"] = ["invented"]
    if fault == "other_requirement":
        issue["requirement_id"] = "different"
    if fault == "helper":
        issue["path"] = "gf-motion-v1.js"
    if fault == "motion_single":
        issue.update(defect="inconsistent_motion", frames=["action_before"])
    assert permitted_issues(response, policy(), {"styles.css": "x", "gf-motion-v1.js": "x"}) == []


def test_visual_patch_cannot_change_criteria_identity_or_unlisted_files():
    game = materialize(fixture_response(), operation="create")
    binding = {**policy(), "artifact_hash": game["artifact_hash"]}
    response = {
        "operation": "visual_patch",
        "status": "ok",
        "message": "Исправлен отступ",
        **{
            k: binding[k]
            for k in ("base_revision", "artifact_hash", "report_id", "report_identity", "packet_hash")
        },
        "patches": [
            {
                "path": "styles.css",
                "file_hash": game["file_hashes"]["styles.css"],
                "old_text": "#eff4ff",
                "new_text": "#fff5e8",
            }
        ],
    }
    kwargs = {
        "operation": "visual_patch",
        "base_revision": "base",
        "files": game["files"],
        "previous_checks": game["checks"],
        "visual_patch": binding,
    }
    updated = materialize(response, **kwargs)
    assert updated["diff"] and any("styles.css" in line for line in updated["diff"])
    assert updated["checks"] == game["checks"] and updated["files"]["game.js"] == game["files"]["game.js"]
    for fault in ("checks", "report_id", "path"):
        changed = deepcopy(response)
        if fault == "checks":
            changed["checks"] = []
        if fault == "report_id":
            changed["report_id"] = 2
        if fault == "path":
            changed["patches"][0]["path"] = "game.js"
        with pytest.raises(ContractError):
            materialize(changed, **kwargs)


def visual_request(operation="visual_review"):
    value = packet()
    sheet = contact_sheet(value, artifact_hash="a" * 64, environment="test")
    binding = {
        **policy(),
        "packet_hash": packet_hash(value),
        "sheet_hash": hashlib.sha256(base64.b64decode(sheet["data"])).hexdigest(),
        "frames": [{k: v for k, v in f.items() if k != "data"} for f in value["frames"]],
    }
    return {
        "operation": operation,
        "generation_strategy": "pro",
        "reasoning_effort": "medium",
        "base_revision": "base",
        "artifact_hash": "a" * 64,
        operation: binding,
        "validation_evidence": {"artifact_hash": "a" * 64, "report_id": 1},
        "preview_image": {
            **sheet,
            **{
                k: binding[k]
                for k in ("base_revision", "artifact_hash", "report_id", "report_identity", "packet_hash")
            },
        },
    }


def test_invalid_visual_image_never_calls_provider():
    from unittest.mock import patch

    from generation.errors import GenerationError
    from generation.service import generate

    request = {**visual_request(), "provider": "fake"}
    request["preview_image"]["data"] = "invalid"
    with patch("generation.providers.fake.generate") as provider, pytest.raises(GenerationError):
        generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    provider.assert_not_called()


@pytest.mark.parametrize("fault", ["shell", "oversize"])
def test_compact_visual_patch_cannot_replace_runtime_or_expand_module(fault):
    from tests.test_compact_generation import compact_response

    game = materialize(compact_response(), operation="create", generation_profile="compact")
    binding = {**policy(), "artifact_hash": game["artifact_hash"], "paths": ["index.html", "game.js"]}
    path = "index.html" if fault == "shell" else "game.js"
    text = game["files"][path]
    old = text[:25]
    response = {
        "operation": "visual_patch",
        "status": "ok",
        "message": "Изменение оформления",
        **{
            k: binding[k]
            for k in ("base_revision", "artifact_hash", "report_id", "report_identity", "packet_hash")
        },
        "patches": [
            {
                "path": path,
                "file_hash": game["file_hashes"][path],
                "old_text": old,
                "new_text": old + (" " if fault == "shell" else "Ж" * 5990),
            }
        ],
    }
    with pytest.raises(ContractError):
        materialize(
            response,
            operation="visual_patch",
            base_revision="base",
            files=game["files"],
            previous_checks=game["checks"],
            generation_profile="compact",
            compact_manifest=game["compact_manifest"],
            visual_patch=binding,
        )
