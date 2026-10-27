"""Only pinned local helper bytes can become part of an exported artifact."""

import hashlib
from pathlib import Path

from bs4 import BeautifulSoup

from .errors import ContractError

PATH = "gf-motion-v1.js"
SOURCE = Path(__file__).parent / "runtime" / "motion-v1.js"


def catalog():
    return {PATH: {"version": 1, "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest()}}


def resolve(files, frozen=None):
    result = dict(files)
    if PATH in result or BeautifulSoup(result.get("index.html", ""), "html.parser").find("script", src=PATH):
        allowed = catalog() if frozen is None else frozen
        if allowed.get(PATH) != catalog()[PATH]:
            raise ContractError("helper_version_changed", "Версия разрешённого средства анимации изменилась.")
        source = SOURCE.read_text()
        if PATH in result and result[PATH] != source:
            raise ContractError("trusted_helper_locked", "Средства приложения не могут заменяться моделью.")
        result[PATH] = source
    return result


def used(files):
    return catalog() if PATH in files else {}


GUIDANCE = """
Optional GameForgeMotion v1: full adds <script src="gf-motion-v1.js"></script> before game.js; compact uses api.motion. Do not return/replace it; bundling is local.
create({from,to,duration,easing,onComplete,reducedMotion}) gives sample(), advance(dt), cancel(), reset(), inspect(). dt/duration are seconds. Fixed origin; easing may overshoot. Completion fires once; cancel/reset clear callbacks. Retarget: cancel; create from current sample. Reduced motion samples the endpoint but keeps completion timing. Keep rules independent of cosmetic callbacks. Advance in the existing update/RAF, no extra loop. Use native ctx.roundRect.
"""
