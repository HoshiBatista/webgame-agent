"""Trusted preview controls, separate from stored/exported game bytes."""

import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def audio_script():
    return (Path(__file__).parent / "runtime" / "preview_audio.js").read_text()


def with_audio_control(html, *, artifact_hash, app_origin):
    config = json.dumps({"artifactKey": artifact_hash, "origin": app_origin}).replace("<", "\\u003c")
    script = "<script>" + audio_script().replace("__GAMEFORGE_AUDIO_CONFIG__", config) + "</script>"
    # Keep standards mode and execute before any game script, including headless HTML.
    doctype = re.match(r"\s*<!doctype\s+html[^>]*>", html, re.I)
    offset = doctype.end() if doctype else 0
    return html[:offset] + script + html[offset:]
