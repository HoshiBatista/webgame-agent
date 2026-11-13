"""Clean runtime and development installs must include the application's dependencies."""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


@pytest.mark.parametrize("lock_name", ["requirements.lock", "requirements-dev.lock"])
def test_locks_cover_every_runtime_dependency(lock_name):
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    locked = {}
    for line in (root / lock_name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            requirement = Requirement(line)
            locked[canonicalize_name(requirement.name)] = requirement
    for value in project["project"]["dependencies"]:
        dependency = Requirement(value)
        name = canonicalize_name(dependency.name)
        assert name in locked, f"{lock_name} is missing runtime dependency: {name}"
        pins = list(locked[name].specifier)
        assert len(pins) == 1 and pins[0].operator == "==", f"Unpinned runtime dependency: {name}"
        assert pins[0].version in dependency.specifier, f"Incompatible runtime dependency: {name}"
        assert dependency.extras <= locked[name].extras, f"Missing runtime extras: {name}"
