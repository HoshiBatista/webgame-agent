import json
from types import SimpleNamespace
from unittest.mock import patch

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
