"""Portable entry points for the studio, preview, workers and verification."""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import os
import secrets
import shutil
import signal
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from prompt2play.paths import PACKAGE_ROOT

SETTINGS = "prompt2play.adapters.django.config.settings"
PREVIEW_SETTINGS = "prompt2play.adapters.django.config.preview_settings"


def configuration_path() -> Path:
    """Discover config from the caller's environment before reading any redirects."""
    return Path(os.environ.get("PROMPT2PLAY_DATA_DIR", ".prompt2play")).expanduser() / ".env"


def configured_environment() -> dict[str, str]:
    """Read local configuration as data; never source it as shell code."""
    result: dict[str, str] = {}
    config = configuration_path()
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not key.isidentifier():
                raise ValueError("Local configuration must contain NAME=value entries")
            result[key] = value.strip()
    result.update(os.environ)
    result.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS)
    return result


@contextmanager
def local_environment() -> Iterator[None]:
    """Apply local configuration for one in-process command without retaining it."""
    additions = {
        name: value for name, value in configured_environment().items() if name not in os.environ
    }
    try:
        os.environ.update(additions)
        yield
    finally:
        for name in additions:
            os.environ.pop(name, None)


def django_command(args: list[str], env: dict[str, str]) -> int:
    return subprocess.call([sys.executable, "-m", "django", *args], env=env)


def setup(args: argparse.Namespace) -> int:
    if os.environ.get("DJANGO_SECRET_KEY") == "":
        raise ValueError("DJANGO_SECRET_KEY is empty; unset it or provide a nonempty signing key.")
    env = configured_environment()
    location = Path(env.get("PROMPT2PLAY_DATA_DIR", ".prompt2play")).expanduser().resolve()
    location.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A config may redirect the actual data directory. Persist the key in the
    # originally discovered file so later commands find exactly the same key.
    config = configuration_path()
    if not env.get("DJANGO_SECRET_KEY"):
        config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        original = config.read_text(encoding="utf-8") if config.exists() else ""
        descriptor = os.open(config, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            if original and not original.endswith("\n"):
                stream.write("\n")
            stream.write("DJANGO_SECRET_KEY=" + secrets.token_urlsafe(48) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        env = configured_environment()
    elif config.exists():
        config.chmod(0o600)
    code = django_command(["migrate", "--noinput"], env)
    if code:
        return code
    password = env.get(args.password_env, "") if args.password_env else ""
    if not password and not args.noinput:
        password = getpass.getpass("Password for the studio administrator: ")
    if not password:
        print("Set the specified password environment variable to create the administrator.")
        return 1
    # Pass the password in a child's environment, never its argv or logs.
    env["PROMPT2PLAY_SETUP_PASSWORD"] = password
    code = django_command(
        [
            "bootstrap",
            "--username",
            args.username,
            "--password-env",
            "PROMPT2PLAY_SETUP_PASSWORD",
            "--noinput",
        ],
        env,
    )
    if not code:
        print("Studio configured. Start it with: prompt2play serve")
    return code


def serve(args: argparse.Namespace) -> int:
    env = configured_environment()
    env["PROMPT2PLAY_APP_ORIGIN"] = f"http://{args.host}:{args.port}"
    env["PROMPT2PLAY_PREVIEW_ORIGIN"] = f"http://{args.host}:{args.preview_port}"
    app = subprocess.Popen(
        [sys.executable, "-m", "django", "runserver", f"{args.host}:{args.port}", "--noreload"],
        env=env,
    )
    preview_env = dict(env, DJANGO_SETTINGS_MODULE=PREVIEW_SETTINGS)
    preview = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "django",
            "runserver",
            f"{args.host}:{args.preview_port}",
            "--noreload",
        ],
        env=preview_env,
    )
    processes = [app, preview]

    def stop(_signum: int, _frame: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    old_term = signal.signal(signal.SIGTERM, stop)
    old_int = signal.signal(signal.SIGINT, stop)
    try:
        # The parent owns the two listeners; no silent surviving preview process.
        while True:
            for process in processes:
                if process.poll() is not None:
                    return process.returncode or 0
            try:
                app.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                continue
    finally:
        stop(0, None)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


def build_validator(args: argparse.Namespace) -> int:
    docker = shutil.which("docker")
    if docker is None:
        print("Docker is unavailable; browser validation cannot run.", file=sys.stderr)
        return 1
    source = PACKAGE_ROOT / "legacy" / "validator"
    dockerfile = source / ("Dockerfile.slim" if args.slim else "Dockerfile")
    return subprocess.call([docker, "build", "-f", str(dockerfile), "-t", args.image, str(source)])


def doctor() -> int:
    for name in ("node", "npm", "codex", "docker"):
        print(f"{name}: {'available' if shutil.which(name) else 'unavailable'}")
    print(f"Django: {'available' if importlib.util.find_spec('django') else 'unavailable'}")
    env = configured_environment()
    print(f"API credentials: {'configured' if env.get('OPENAI_API_KEY') else 'not configured'}")
    print("No credential values are printed. Codex authentication is local to each worker.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prompt2Play game generation studio")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("setup", help="Migrate local database and create a login")
    install.add_argument("--username", default="admin")
    install.add_argument("--password-env", default="PROMPT2PLAY_ADMIN_PASSWORD")
    install.add_argument("--noinput", action="store_true")
    studio = commands.add_parser("serve", help="Serve studio and separate preview origin")
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--port", type=int, default=8000)
    studio.add_argument("--preview-port", type=int, default=8001)
    commands.add_parser("manage", help="Run a Django management command")
    commands.add_parser("doctor", help="Inspect available tools without revealing secrets")
    image = commands.add_parser("build-validator", help="Build the isolated browser runner")
    image.add_argument("--image", default="prompt2play-validator:local")
    image.add_argument("--slim", action="store_true")
    commands.add_parser("worker", help="Connect a local model or validation executor")
    commands.add_parser("evaluate", help="Run a fixed live generation comparison")
    commands.add_parser("backup", help="Snapshot database and immutable artifacts")
    commands.add_parser("restore", help="Restore a verified backup into an empty target")
    args, extra = parser.parse_known_args(argv)
    if extra and args.command not in {"manage", "worker", "evaluate", "backup", "restore"}:
        parser.error("Unrecognized arguments: " + " ".join(extra))
    try:
        if args.command == "setup":
            return setup(args)
        if args.command == "serve":
            if args.port == args.preview_port:
                parser.error("Studio and preview ports must differ")
            return serve(args)
        if args.command == "manage":
            return django_command(extra, configured_environment())
        if args.command == "doctor":
            return doctor()
        if args.command == "build-validator":
            return build_validator(args)
        if args.command in {"worker", "evaluate", "backup", "restore"}:
            with local_environment():
                if args.command == "worker":
                    from prompt2play.workers.runner import main as worker_main

                    return worker_main(extra)
                if args.command == "evaluate":
                    from prompt2play.evaluation import main as evaluation_main

                    return evaluation_main(extra)
                from prompt2play.operations import main as operations_main

                return operations_main([args.command, *extra])
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
