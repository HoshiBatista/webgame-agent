"""Only a bounded validator frame of the exact candidate may enter model context."""

import base64
import binascii

MAX_IMAGE_BYTES = 512 * 1024


def image_input(request):
    frame = request.get("preview_image")
    evidence = request.get("validation_evidence") or {}
    if request.get("generation_strategy") != "pro" or not isinstance(frame, dict):
        return None
    if (not request.get("base_revision") or not request.get("artifact_hash")
            or frame.get("artifact_hash") != request["artifact_hash"]
            or frame.get("artifact_hash") != evidence.get("artifact_hash")
            or not frame.get("report_id") or frame.get("report_id") != evidence.get("report_id")):
        return None
    mime, data = frame.get("mime"), frame.get("data")
    if mime not in {"image/png", "image/jpeg"} or not isinstance(data, str) or len(data) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        return None
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        return None
    signature = b"\x89PNG\r\n\x1a\n" if mime == "image/png" else b"\xff\xd8\xff"
    if len(raw) > MAX_IMAGE_BYTES or not raw.startswith(signature):
        return None
    return {"type": "image", "url": f"data:{mime};base64,{data}"}
