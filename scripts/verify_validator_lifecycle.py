"""Run forty real browser jobs in the disposable test container without a model."""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generation.artifacts import materialize  # noqa: E402
from generation.providers.fake import fixture_response  # noqa: E402

CONTAINER = "gf-mini-validator-tests"
inspect = json.loads(subprocess.check_output(["docker", "inspect", CONTAINER]))[0]
host = inspect["HostConfig"]
assert host["Init"] is True
assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] is True
assert host["PidsLimit"] == 256
assert inspect["Config"]["User"] == "10001:10001"
assert "ALL" in host["CapDrop"] and not host["Privileged"]
assert not any(mount["Type"] == "bind" for mount in inspect["Mounts"])

process_probe = """
import json
from pathlib import Path
states = []
for path in Path('/proc').glob('[0-9]*/stat'):
    try:
        states.append(path.read_text().rsplit(')', 1)[1].split()[0])
    except (FileNotFoundError, ProcessLookupError):
        pass
print(json.dumps({'processes': len(states), 'zombies': states.count('Z')}))
"""


def processes():
    return json.loads(subprocess.check_output(["docker", "exec", CONTAINER, "python", "-c", process_probe]))


artifact = materialize(fixture_response(), operation="create")
payload = json.dumps({key: artifact[key] for key in ("html", "checks", "artifact_hash")}, ensure_ascii=False)
report = {
    "profile": "fixture-real-isolated-Chromium-no-model",
    "container": CONTAINER,
    "image": inspect["Image"],
    "init": True,
    "pids_limit": host["PidsLimit"],
    "baseline": processes(),
    "samples": [],
}
started = time.monotonic()
for index in range(40):
    response = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-m", "validation.daemon", "--once"],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
    )
    result = json.loads(response.stdout)
    assert result["status"] == "passed", result.get("findings")
    assert result["artifact_hash"] == artifact["artifact_hash"]
    assert len(result["facts"]) == 3
    # Allow PID 1 to reap exited grandchildren before taking the measurement.
    time.sleep(0.1)
    sample = {"job": index + 1, **processes()}
    report["samples"].append(sample)
    assert sample["zombies"] == 0, sample
    assert sample["processes"] <= report["baseline"]["processes"] + 2, sample
    if (index + 1) % 10 == 0:
        print(json.dumps(sample), flush=True)
report["elapsed_seconds"] = round(time.monotonic() - started, 3)
report["status"] = "passed"
destination = ROOT / ".data/validator-lifecycle.json"
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"status": "passed", "jobs": 40, "elapsed_seconds": report["elapsed_seconds"]}))
