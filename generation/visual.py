"""Bounded visual hypotheses, never a second source of gameplay acceptance."""

import base64
import hashlib
import io
import warnings
from copy import deepcopy

from PIL import Image, ImageDraw

from validation.contracts import VIEWPORTS

from .errors import ContractError
from .requirements import digest
from .schema import array, obj, string

VERSION = 1
MAX_IMAGE_BYTES = 512 * 1024
MAX_PIXELS = 2_000_000
FRAME_IDS = ["mobile_start", "action_before", "action_after", "action_100ms", "action_240ms", "desktop_start"]


def decode(data, mime, *, max_bytes=MAX_IMAGE_BYTES):
    if not isinstance(data, str) or len(data) > 4 * ((max_bytes + 2) // 3):
        raise ValueError("image too large")
    raw = base64.b64decode(data, validate=True)
    if len(raw) > max_bytes or mime not in {"image/png", "image/jpeg"}:
        raise ValueError("invalid image")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as opened:
            expected = "PNG" if mime == "image/png" else "JPEG"
            if (
                opened.format != expected
                or opened.width * opened.height > MAX_PIXELS
                or max(opened.size) > 2048
            ):
                raise ValueError("invalid image dimensions or format")
            opened.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            return opened.convert("RGB")


def packet_hash(packet):
    return digest(
        {**packet, "frames": [{k: v for k, v in f.items() if k != "data"} for f in packet.get("frames", [])]}
    )


def contact_sheet(packet, *, artifact_hash, environment):
    if (
        packet.get("version") != VERSION
        or packet.get("status") != "captured"
        or packet.get("artifact_hash") != artifact_hash
        or packet.get("environment") != environment
        or [f.get("id") for f in packet.get("frames", [])] != FRAME_IDS
    ):
        raise ValueError("invalid visual packet binding")
    sheet = Image.new("RGB", (1200, 680), "#e7e9ed")
    draw = ImageDraw.Draw(sheet)
    times: list[float] = []
    for i, frame in enumerate(packet["frames"]):
        viewport = "desktop" if i == 5 else "mobile"
        if (
            frame.get("viewport") != viewport
            or frame.get("size") != VIEWPORTS[viewport]
            or frame.get("check_id") != (None if i == 5 else packet.get("route_id"))
            or not packet.get("route_id")
            or not packet.get("route")
            or (
                1 <= i <= 4
                and (
                    frame.get("action") not in packet["route"]
                    or frame.get("action") != packet["frames"][1].get("action")
                )
            )
            or (i in {0, 5} and frame.get("action") is not None)
        ):
            raise ValueError("invalid visual route metadata")
        raw = base64.b64decode(frame["data"], validate=True)
        if hashlib.sha256(raw).hexdigest() != frame["sha256"]:
            raise ValueError("corrupt visual frame")
        decoded = decode(frame["data"], frame["mime"], max_bytes=256 * 1024)
        if list(decoded.size) != [frame["size"]["width"], frame["size"]["height"]]:
            raise ValueError("frame dimensions disagree")
        timestamp = frame["captured_at_ms"]
        if (
            type(timestamp) not in (int, float)
            or not 0 <= timestamp <= 45000
            or times
            and timestamp < times[-1]
        ):
            raise ValueError("invalid capture time")
        times.append(timestamp)
        decoded.thumbnail((390, 306))
        x = (i % 3) * 400 + (400 - decoded.width) // 2
        y = (i // 3) * 340 + 25
        sheet.paste(decoded, (x, y))
        draw.text(
            ((i % 3) * 400 + 8, (i // 3) * 340 + 5),
            f"{frame['id']} | {frame['viewport']} | {timestamp:.0f} ms",
            fill="black",
        )
    output = io.BytesIO()
    sheet.save(output, format="JPEG", quality=75)
    if len(output.getvalue()) > MAX_IMAGE_BYTES:
        raise ValueError("contact sheet too large")
    return {
        "mime": "image/jpeg",
        "data": base64.b64encode(output.getvalue()).decode(),
        "packet_hash": packet_hash(packet),
    }


ISSUE = obj(
    {
        "kind": {"enum": ["reproducible_defect", "suspected_defect", "preference"]},
        "defect": {
            "enum": [
                "clipping",
                "overlap",
                "unreadable_text",
                "missing_feedback",
                "inconsistent_motion",
                "other",
            ]
        },
        "frames": array(string(), minItems=1, maxItems=4),
        "requirement_id": string(maxLength=80),
        "path": string(maxLength=120),
        "observation": string(minLength=10, maxLength=500),
        "expected": string(minLength=10, maxLength=500),
        "minimal_fix": string(minLength=10, maxLength=500),
    }
)
BINDINGS = {
    "base_revision": string(),
    "artifact_hash": string(),
    "report_id": {"type": "integer"},
    "report_identity": string(),
    "packet_hash": string(),
}
REVIEW_SCHEMA = obj(
    {
        "operation": {"enum": ["visual_review"]},
        "status": {"enum": ["ok", "no_change", "scope_refusal"]},
        "message": string(minLength=1, maxLength=1000),
        **BINDINGS,
        "issues": array(ISSUE, maxItems=3),
    }
)
PATCH_SCHEMA = obj(
    {
        "operation": {"enum": ["visual_patch"]},
        "status": {"enum": ["ok", "unchanged", "scope_refusal"]},
        "message": string(minLength=1, maxLength=1000),
        **BINDINGS,
        "patches": array(
            obj(
                {
                    "path": string(maxLength=120),
                    "file_hash": string(),
                    "old_text": string(minLength=1, maxLength=6000),
                    "new_text": string(maxLength=6000),
                }
            ),
            maxItems=6,
        ),
    }
)


def validate_binding(response, policy):
    if not policy or any(response.get(k) != policy.get(k) for k in BINDINGS):
        raise ContractError("stale_visual_evidence", "Замечания относятся к другой версии или пакету кадров.")


def permitted_issues(response, policy, files):
    validate_binding(response, policy)
    if response["status"] != "ok":
        if response["issues"]:
            raise ContractError("invalid_visual_review", "Отказ или отсутствие изменений требует issues=[].")
        return []
    result = []
    for issue in response["issues"]:
        if (
            issue["kind"] != "reproducible_defect"
            or issue["defect"] == "other"
            or issue["path"] not in files
            or issue["path"] in {"runtime.js", "runtime.css", "gf-motion-v1.js"}
            or not issue["path"].endswith((".js", ".css", ".html"))
            or issue["requirement_id"] not in policy["requirement_ids"]
            or not set(issue["frames"]).issubset(FRAME_IDS)
            or issue["defect"] == "inconsistent_motion"
            and len(set(issue["frames"]) & set(FRAME_IDS[1:5])) < 2
        ):
            continue
        result.append(deepcopy(issue))
    return result[:2]


REVIEW_PROMPT = """Review only the supplied contact sheet and exact saved game. Return the visual_review schema, with all visual_review identity fields copied exactly. No source changes or tools. Frames show an ordinary-time replay of a previously passed route, not FPS or proof of every mechanic. Separate a concrete reproducible defect (clipping, overlap, unreadable text, missing action feedback, inconsistent motion) from suspected defects and taste preferences. For each cite real frame IDs, exact requirement ID (presentation is the saved art brief), editable source path, observation, expected presentation and the smallest change. Never request a genre change, fewer mechanics, weaker tests or removal of animation to get a pass. A different palette alone is a preference. The contact sheet downsizes frames: never infer unreadable text solely from thumbnail scaling. If evidence is insufficient say no_change; do not invent intermediate frames or gameplay. Use Russian message/observations."""
PATCH_PROMPT = """Apply only the application-admitted visual_patch.issues to the exact supplied files using small unique old_text/new_text patches and exact file hashes. Copy all visual_patch identity fields. No new files, checks, rules, title, helper changes or unrelated redesign. Preserve mechanics, timing of rules, art direction, existing animations, input and all frozen requirements. Cosmetic state must remain separate. Fix only the listed paths. If impossible return unchanged with patches=[]; do not weaken a game to make it look compliant. The application reruns unchanged gameplay checks and keeps the former candidate on a regression. Use Russian message; do not claim unperformed tests."""
