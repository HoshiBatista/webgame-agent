import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from validation import native, service


def test_native_unavailable_never_falls_back_to_host_or_docker(monkeypatch):
    monkeypatch.setenv("VALIDATOR_BACKEND", "native")
    html = "<html></html>"
    with patch.object(native, "execute", side_effect=ValueError("sandbox unavailable")), \
            patch.object(service.subprocess, "run") as fallback:
        report = service.validate(html, [], artifact_hash=hashlib.sha256(html.encode()).hexdigest())
        assert report["status"] == "infrastructure_error"
        assert service.environment_identity().endswith(":unavailable")
        fallback.assert_not_called()


def test_unknown_backend_cannot_execute_game(monkeypatch):
    monkeypatch.setenv("VALIDATOR_BACKEND", "unsandboxed")
    html = "<html></html>"
    with patch.object(service.subprocess, "run") as launch:
        assert service.validate(html, [], artifact_hash=hashlib.sha256(html.encode()).hexdigest())["status"] \
            == "infrastructure_error"
    launch.assert_not_called()


def test_native_start_checks_sandbox_before_migrations_or_workers(tmp_path, monkeypatch):
    from scripts import dev

    monkeypatch.setattr(dev, "DATA", tmp_path)
    monkeypatch.setenv("VALIDATOR_BACKEND", "native")
    with patch.object(dev.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "check")) as run, \
            patch.object(dev.subprocess, "Popen") as start, patch.object(dev.socket, "socket"):
        with pytest.raises(subprocess.CalledProcessError):
            dev.start()
    assert run.call_count == 1
    assert run.call_args.args[0][-1] == "check"
    start.assert_not_called()
    assert not (tmp_path / "local-processes.json").exists()


def test_occupied_port_stops_start_before_database_changes(tmp_path, monkeypatch):
    from scripts import dev

    monkeypatch.setattr(dev, "DATA", tmp_path)
    with patch.object(dev.socket, "socket") as sock, patch.object(dev.subprocess, "run") as setup:
        sock.return_value.__enter__.return_value.bind.side_effect = OSError("already in use")
        with pytest.raises(RuntimeError, match="occupied"):
            dev.start()
    setup.assert_not_called()


@pytest.mark.browser
@pytest.mark.native_browser
def test_os_sandbox_denies_host_files_writes_and_network():
    # Trusted tiny program verifies the OS boundary, independently of Playwright
    # routing/CSP or game JS. No real secrets or external network are accessed.
    with tempfile.TemporaryDirectory() as private, tempfile.TemporaryDirectory() as writable, \
            socket.socket() as listener:
        scratch = Path(writable).resolve()
        secret = Path(private).resolve() / "canary"
        secret.write_text("canary")
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        code = f"""
import json, socket
denied = []
for mode in ['r', 'w']:
    try:
        with open({str(secret)!r}, mode): pass
    except (PermissionError, FileNotFoundError): denied.append(mode)
with socket.socket() as client:
    client.settimeout(1)
    try: client.connect(('127.0.0.1', {port}))
    except OSError: denied.append('network')
print(json.dumps(denied))
"""
        command = native.sandbox_command(native.runtime_paths(native.browser_path()), scratch,
                                         [str(Path(sys.executable).resolve()), "-I", "-S", "-c", code])
        result = subprocess.run(command, env={"PATH": "/usr/bin:/bin", "HOME": str(scratch)},
                                cwd=scratch, text=True, capture_output=True, check=True, timeout=10)
        assert json.loads(result.stdout) == ["r", "w", "network"]
        assert secret.read_text() == "canary"


@pytest.mark.browser
@pytest.mark.native_browser
def test_native_probe_really_launches_chromium_without_secret_environment(monkeypatch):
    monkeypatch.setenv("GAMEFORGE_RELAY_API_KEY", "canary-not-a-real-token")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/host/desktop-bus")
    seen = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        seen.append(kwargs["env"])
        return original(*args, **kwargs)

    with patch.object(native.subprocess, "Popen", side_effect=capture):
        identity = native.environment_identity()
    assert f":native-{platform.system().lower()}:" in identity
    assert len(seen) == 1
    assert "GAMEFORGE_RELAY_API_KEY" not in seen[0]
    assert "DATABASE_URL" not in seen[0]
    assert "PYTHONPATH" not in seen[0]
    assert seen[0]["HOME"] != os.path.expanduser("~")
    if platform.system() == "Linux":
        assert seen[0]["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/dev/null"
    else:
        assert "DBUS_SESSION_BUS_ADDRESS" not in seen[0]
