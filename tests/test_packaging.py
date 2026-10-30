"""The production image installs the lock, not the editable development package."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def test_production_lock_covers_every_runtime_dependency():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    locked = {}
    for line in (root / "requirements.lock").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            requirement = Requirement(line)
            locked[canonicalize_name(requirement.name)] = requirement
    for value in project["project"]["dependencies"]:
        dependency = Requirement(value)
        name = canonicalize_name(dependency.name)
        assert name in locked, f"Production image is missing runtime dependency: {name}"
        pins = list(locked[name].specifier)
        assert len(pins) == 1 and pins[0].operator == "==", f"Unpinned runtime dependency: {name}"
        assert pins[0].version in dependency.specifier, f"Incompatible runtime dependency: {name}"
