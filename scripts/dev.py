"""Local app/worker processes. Supports either OS-sandboxed or Docker validation."""

import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".data"


def ensure_available_port(port):
    with socket.socket() as listener:
        # Match the dev server: a closed connection in TIME_WAIT is not a running listener.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"Local port {port} is occupied; no processes were started") from exc


def start():
    DATA.mkdir(mode=0o700, exist_ok=True)
    pidfile = DATA / "local-processes.json"
    if pidfile.exists():
        print("Local process record already exists. Use status/stop before starting another instance.")
        return
    python = str(ROOT / ".venv/bin/python")
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    # Do not start a competing worker if another local app already owns a port.
    for port in (8000, 8001):
        ensure_available_port(port)
    if os.environ.get("VALIDATOR_BACKEND") == "native":
        subprocess.run([python, str(ROOT / "scripts/native.py"), "check"], cwd=ROOT, check=True)
    subprocess.run([python, str(ROOT / "manage.py"), "migrate", "--noinput"], cwd=ROOT, check=True)
    subprocess.run([python, str(ROOT / "manage.py"), "bootstrap"], cwd=ROOT, check=True)
    processes = {}
    commands = {
        "app": [python, str(ROOT / "manage.py"), "runserver", "127.0.0.1:8000", "--noreload"],
        "preview": [python, str(ROOT / "manage.py"), "runserver", "127.0.0.1:8001", "--noreload"],
        "worker": [
            python,
            "-m",
            "celery",
            "-A",
            "gameforge",
            "worker",
            "--pool=threads",
            "--concurrency=4",
            "--loglevel=WARNING",
        ],
        "beat": [
            python,
            "-m",
            "celery",
            "-A",
            "gameforge",
            "beat",
            "--schedule",
            str(DATA / "celerybeat"),
            "--loglevel=WARNING",
        ],
    }
    for role, command in commands.items():
        env = os.environ.copy()
        if role == "preview":
            env["DJANGO_SETTINGS_MODULE"] = "gameforge.preview_settings"
        with (DATA / f"{role}.log").open("ab") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        started = process_start(process.pid)
        processes[role] = {"pid": process.pid, "command": command, "started": started}
    pidfile.write_text(json.dumps(processes, indent=2))
    deadline = time.monotonic() + 8
    ready = set()
    while time.monotonic() < deadline:
        for role, url, expected in (
            ("app", "http://127.0.0.1:8000/api/health/", 200),
            ("preview", "http://localhost:8001/", 404),
        ):
            if role in ready:
                continue
            try:
                with urlopen(url, timeout=.3) as response:
                    if response.status == expected:
                        ready.add(role)
            except HTTPError as exc:
                if exc.code == expected:
                    ready.add(role)
            except (URLError, TimeoutError):
                pass
        if len(ready) == 2:
            break
        time.sleep(.1)
    if len(ready) != 2:
        print("Servers are not ready yet. Process record retained; inspect .data/app.log and preview.log.")
        return
    print("GameForge: http://127.0.0.1:8000/; isolated preview: http://localhost:8001/")


def process_start(pid):
    # start() loads .env but status/stop need not; timezone/locale must not change identity.
    return subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], text=True, capture_output=True,
                          env={**os.environ, "TZ": "UTC", "LC_ALL": "C"}).stdout.strip()


def still_ours(item):
    pid = item["pid"]
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], text=True, capture_output=True)
    started = process_start(pid)
    args = shlex.split(result.stdout)
    return bool(args) and args[1:] == item["command"][1:] and started == item["started"]


def manage(action):
    pidfile = DATA / "local-processes.json"
    if not pidfile.exists():
        print("No local process record.")
        return
    processes = json.loads(pidfile.read_text())
    for role, item in processes.items():
        pid = item["pid"]
        # Never signal an unrelated process if a PID has been reused.
        matches = still_ours(item)
        print(f"{role}: {'running' if matches else 'stopped'}")
        if action == "stop" and matches:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    if action == "stop":
        # A worker may still be draining a model call after SIGTERM. Keep its identity
        # until it exits, so a subsequent start cannot create a competing worker.
        for _ in range(10):
            if not any(still_ours(item) for item in processes.values()):
                pidfile.unlink()
                return
            time.sleep(.2)
        print("Processes are still shutting down; record retained. Check status/stop before restart.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    start() if args.action == "start" else manage(args.action)
