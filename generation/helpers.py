"""Only pinned local helper bytes can become part of an exported artifact."""

import hashlib
from pathlib import Path

from bs4 import BeautifulSoup

from .errors import ContractError

PATH = "gf-motion-v1.js"
SOURCE = Path(__file__).parent / "runtime" / "motion-v1.js"


def sources():
    from .experience import PATH as experience_path
    from .experience import SOURCE as experience_source

    return {PATH: SOURCE, experience_path: experience_source}


def catalog():
    return {path: {"version": 1, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
            for path, source in sources().items()}


def resolve(files, frozen=None):
    result = dict(files)
    soup = BeautifulSoup(result.get("index.html", ""), "html.parser")
    for path, source_path in sources().items():
        if path in result or soup.find("script", src=path):
            allowed = catalog() if frozen is None else frozen
            if allowed.get(path) != catalog()[path]:
                raise ContractError("helper_version_changed", "Версия разрешённого средства приложения изменилась.")
            source = source_path.read_text()
            if path in result and result[path] != source:
                raise ContractError("trusted_helper_locked", "Средства приложения не могут заменяться моделью.")
            result[path] = source
    return result


def used(files):
    return {path: item for path, item in catalog().items() if path in files}


GUIDANCE = """
Optional GameForgeMotion v1: full adds <script src="gf-motion-v1.js"></script> before game.js; compact uses api.motion. Do not return/replace it; bundling is local.
create({from,to,duration,easing,onComplete,reducedMotion}) gives sample(), advance(dt), cancel(), reset(), inspect(). dt/duration are seconds. Fixed origin; easing may overshoot. Completion fires once; cancel/reset clear callbacks. Retarget: cancel; create from current sample. Reduced motion samples the endpoint but keeps completion timing. Keep rules independent of cosmetic callbacks. Advance in the existing update/RAF, no extra loop. Use native ctx.roundRect.
"""
