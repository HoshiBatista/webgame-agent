"""One-shot OS sandbox for local development; no unsandboxed fallback.

The browser gets public runtime files and a fresh scratch directory only.
The controller keeps credentials, the repository and all database connections.
"""

import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from .contracts import browser_watchdog_seconds

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = ROOT / ".data/native-validator/browsers"
MAX_RESULT = 4_000_000


def browser_path():
    # Only the project's downloaded, pinned Playwright browser is supported.
    import playwright

    registry = json.loads((Path(playwright.__file__).parent / "driver/package/browsers.json").read_text())
    descriptor = next(b for b in registry["browsers"] if b["name"] == "chromium-headless-shell")
    names = ("chrome-headless-shell", "headless_shell")
    candidates = [p for p in BROWSERS.glob(f"chromium_headless_shell-{descriptor['revision']}/*/*")
                  if p.name in names and p.is_file()]
    if len(candidates) != 1:
        raise ValueError("Run .venv/bin/python scripts/native.py prepare (one pinned Chromium required)")
    return candidates[0].resolve()


def runtime_paths(browser):
    import greenlet
    import playwright
    import pyee
    import typing_extensions

    # Do not expose the application's venv or repository: only stdlib, the
    # Playwright package/driver and validation sources are needed by this child.
    paths = [Path(sys.base_prefix), Path(playwright.__file__).parent,
             Path(greenlet.__file__).parent, Path(pyee.__file__).parent,
             Path(typing_extensions.__file__), browser.parent]
    if platform.system() == "Darwin":
        for cellar in ("/opt/homebrew/Cellar", "/usr/local/Cellar"):
            if Path(cellar).is_dir():
                paths.append(Path(cellar))
    return sorted({str(p.resolve()) for p in paths})


def mac_profile(read_paths, scratch):
    def rule(kind, paths):
        return "\n".join(f"(allow {kind} (subpath {json.dumps(str(p))}))" for p in paths)

    return "\n".join([
        "(version 1)", "(deny default)",
        "(allow process-exec process-fork)",
        "(allow signal (target same-sandbox))",
        "(allow signal (target self))",
        "(allow process-info-pidinfo process-info-setcontrol (target self))",
        "(allow sysctl-read)",
        "(allow file-read-metadata)",
        '(allow file-read* (literal "/"))',
        "(allow mach-lookup (global-name \"com.apple.system.logger\") "
        "(global-name \"com.apple.logd\") (global-name \"com.apple.system.notification_center\") "
        "(global-name \"com.apple.FontObjectsServer\") (global-name \"com.apple.fonts\") "
        "(global-name \"com.apple.windowserver.active\") (global-name \"com.apple.lsd.mapdb\"))",
        '(allow iokit-open (iokit-registry-entry-class "IOSurfaceRootUserClient") '
        '(iokit-user-client-class "IOSurfaceSendRight") (iokit-user-client-class "RootDomainUserClient"))',
        '(allow ipc-posix-shm-read-data (ipc-posix-name "apple.shm.notification_center"))',
        '(allow file-read* (literal "/private/etc/passwd") '
        '(literal "/Library/Preferences/.GlobalPreferences.plist") (subpath "/System/Library/OpenDirectory"))',
        '(allow mach-lookup (global-name-regex #"^org\\.chromium\\."))',
        '(allow mach-register (global-name-regex #"^org\\.chromium\\."))',
        '(allow file-read* file-write* (literal "/dev/null") (literal "/dev/zero"))',
        '(allow file-read* (literal "/dev/random") (literal "/dev/urandom"))',
        rule("file-read*", [*read_paths, "/usr/lib", "/usr/share/zoneinfo", "/usr/share/icu",
                            "/private/var/db/timezone",
                            "/System/Library/Frameworks", "/System/Library/PrivateFrameworks",
                            "/System/Library/OpenSSL",
                            "/System/Library/Fonts", "/System/Library/CoreServices"]),
        rule("file-read* file-write*", [scratch]),
        # No network*, user preferences, keychain, home or whole /tmp permission.
    ])


def linux_command(read_paths, scratch, command):
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise ValueError("Install bubblewrap; native validation will not run without OS isolation")
    result = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
              "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/home",
              "--dir", "/run", "--dir", "/var", "--dir", "/etc"]
    # Runtime directories only. Never bind /, /home, /run or host /tmp.
    for path in ["/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc/fonts", "/etc/ld.so.cache",
                 *read_paths]:
        if Path(path).exists():
            result += ["--ro-bind", path, path]
    result += ["--bind", str(scratch), str(scratch), "--chdir", str(scratch), "--", *command]
    return result


def sandbox_command(read_paths, scratch, command):
    system = platform.system()
    if system == "Darwin":
        executable = "/usr/bin/sandbox-exec"
        if not Path(executable).is_file():
            raise ValueError("macOS sandbox-exec unavailable; use the Docker validator")
        profile = scratch / "sandbox.sb"
        profile.write_text(mac_profile(read_paths, scratch))
        return [executable, "-f", str(profile), *command]
    if system == "Linux":
        return linux_command(read_paths, scratch, command)
    raise ValueError("Native validator supports macOS and Linux/WSL2 only")


def execute(payload, *, probe=False):
    import greenlet
    import playwright
    import pyee
    import typing_extensions

    browser = browser_path()
    registry = json.loads((Path(playwright.__file__).parent / "driver/package/browsers.json").read_text())
    descriptor = next(b for b in registry["browsers"] if b["name"] == "chromium-headless-shell")
    if browser.parent.parent.name != f"chromium_headless_shell-{descriptor['revision']}":
        raise ValueError("Chromium revision differs from installed Playwright; rerun native.py prepare")
    reads = runtime_paths(browser)
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    # A canary outside the sandbox proves denial without trying to read secrets.
    with tempfile.TemporaryDirectory(prefix="gf-canary-") as canary_dir, \
            tempfile.TemporaryDirectory(prefix="gf-browser-") as scratch_dir:
        scratch = Path(scratch_dir).resolve()
        canary = Path(canary_dir).resolve() / "private-file"
        canary.write_text("not-a-secret")
        shutil.copytree(Path(__file__).parent, scratch / "validation",
                        ignore=shutil.ignore_patterns("__pycache__"))
        packages = scratch / "packages"
        packages.mkdir()
        for module in (playwright, greenlet, pyee):
            if module.__file__ is None:
                raise ValueError("Browser dependency has no installed package path")
            (packages / module.__name__).symlink_to(Path(module.__file__).parent.resolve())
        (packages / "typing_extensions.py").symlink_to(Path(typing_extensions.__file__).resolve())
        entry = scratch / "entry.py"
        entry.write_text(
            "import sys,os,json,socket,resource\n"
            "resource.setrlimit(resource.RLIMIT_CORE,(0,0))\n"
            "resource.setrlimit(resource.RLIMIT_FSIZE,(8000000,8000000))\n"
            "resource.setrlimit(resource.RLIMIT_NOFILE,(256,256))\n"
            "resource.setrlimit(resource.RLIMIT_CPU,(180,180))\n"
            f"sys.path.insert(0,{str(scratch)!r})\n"
            f"sys.path.insert(0,{str(packages)!r})\n"
            # sandbox policy permits the package, not siblings in site-packages.
            f"private={str(canary)!r}\n"
            "try:\n open(private).read(); raise RuntimeError('Sandbox allowed private file access')\n"
            "except (PermissionError,FileNotFoundError): pass\n"
            "try:\n s=socket.socket(); s.bind(('127.0.0.1',0)); "
            "raise RuntimeError('Sandbox allowed host networking')\n"
            "except PermissionError: pass\n"
            # Linux has its own loopback namespace, binding there is safe. Its
            # separate network namespace is guaranteed by the bwrap invocation.
            "from validation.runner import identity,run\n"
            + ("from playwright.sync_api import sync_playwright\n"
               "with sync_playwright() as pw:\n"
               " browser=pw.chromium.launch(headless=True,executable_path=os.environ['CHROMIUM_EXECUTABLE'],"
               "args=['--disable-dev-shm-usage','--disable-gpu'])\n"
               " assert browser.version == os.environ['CHROMIUM_VERSION'], 'Browser version mismatch'\n"
               " browser.close()\n" if probe else "") +
            f"print(json.dumps({{'environment':identity()}} if {probe!r} "
            "else run(json.loads(sys.stdin.read(2000000))),ensure_ascii=False))\n"
        )
        if platform.system() == "Linux":
            entry.write_text(entry.read_text().replace(
                "raise RuntimeError('Sandbox allowed host networking')", "s.close()"
            ))
        python = Path(sys.executable).resolve()
        command = sandbox_command(reads, scratch, [str(python), "-I", "-S", str(entry)])
        env = {
            "PATH": "/usr/bin:/bin", "HOME": str(scratch), "TMPDIR": str(scratch),
            "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
            "CHROMIUM_EXECUTABLE": str(browser), "PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS.resolve()),
            "CHROMIUM_VERSION": descriptor["browserVersion"],
            "VALIDATOR_IDENTITY_SUFFIX": f"native-{platform.system().lower()}:{source_hash}",
        }
        if platform.system() == "Linux":
            # Avoid libdbus session auto-discovery during Chromium startup. There
            # is no desktop bus in this isolated process; never inherit the host's
            # address or start a session daemon. /dev/null cannot be a bus socket.
            env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/dev/null"
        timeout = 40 if probe else browser_watchdog_seconds(payload.get("checks"), payload.get("operator_criteria"), capture_visual=payload.get("capture_visual", False)) + 5
        with (scratch / "stdout").open("w+b") as output, (scratch / "stderr").open("w+b") as errors:
            process = subprocess.Popen(command, cwd=scratch, env=env, stdin=subprocess.PIPE,
                                       stdout=output, stderr=errors, start_new_session=True)
            try:
                process.communicate(json.dumps(payload).encode(), timeout=timeout)
                output.seek(0)
                raw = output.read(MAX_RESULT + 1)
                if process.returncode or len(raw) > MAX_RESULT:
                    errors.seek(0)
                    # Private local diagnostic only; no inherited credentials.
                    detail = errors.read(16000).decode(errors="replace")[-5000:]
                    raise ValueError(f"Native sandbox could not run ({process.returncode}): {detail}")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError("Invalid native browser report")
                return result
            finally:
                # Also remove orphan browser descendants after a normal result.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)


def environment_identity():
    return execute({}, probe=True)["environment"]
