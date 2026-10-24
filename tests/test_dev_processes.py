import json
import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import dev


def test_pid_reuse_is_never_signalled(tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "DATA", tmp_path)
    record = {"worker": {"pid": 123, "command": ["python", "-m", "celery"], "started": "old start"}}
    (tmp_path / "local-processes.json").write_text(json.dumps(record))
    with patch.object(dev.subprocess, "run", side_effect=[
        SimpleNamespace(stdout="python -m celery"), SimpleNamespace(stdout="new start")
    ] * 2), patch.object(dev.os, "killpg") as signal:
        dev.manage("stop")
    signal.assert_not_called()
    assert not (tmp_path / "local-processes.json").exists()


def test_draining_worker_keeps_record_and_blocks_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "DATA", tmp_path)
    path = tmp_path / "local-processes.json"
    path.write_text(json.dumps({"worker": {"pid": 123}}))
    with patch.object(dev, "still_ours", return_value=True), patch.object(dev.os, "killpg"), \
            patch.object(dev.time, "sleep"), patch.object(dev.subprocess, "Popen") as launch:
        dev.manage("stop")
        dev.start()
    assert path.exists()
    launch.assert_not_called()


def test_timezone_and_locale_changes_do_not_hide_an_owned_process(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Moscow")
    monkeypatch.setenv("LC_ALL", "ru_RU.UTF-8")
    record = {"pid": 123, "command": ["python", "-m", "celery"], "started": "stable UTC start"}

    def ps(command, **kwargs):
        if command[-1] == "command=":
            return SimpleNamespace(stdout="python -m celery")
        env = kwargs.get("env", {})
        return SimpleNamespace(stdout="stable UTC start" if (env.get("TZ"), env.get("LC_ALL")) == ("UTC", "C")
                               else "different local start")

    with patch.object(dev.subprocess, "run", side_effect=ps):
        assert dev.still_ours(record)


def test_port_probe_blocks_a_live_listener_but_allows_closed_connections():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        address = listener.getsockname()
        with pytest.raises(RuntimeError, match="occupied"):
            dev.ensure_available_port(address[1])
        with socket.create_connection(address, timeout=2) as client:
            connection, _ = listener.accept()
            connection.close()
            assert client.recv(1) == b""
    # The server-side connection may remain in TIME_WAIT; no competing listener exists.
    dev.ensure_available_port(address[1])
