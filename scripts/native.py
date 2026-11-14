"""Prepare and check the Docker-free local browser; never starts model calls."""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare_linux_libraries(destination):
    """Fetch NSS/NSPR from the configured apt repository without sudo or host installation."""
    if platform.system() != "Linux" or not all(shutil.which(x) for x in ("apt-get", "dpkg-deb")):
        raise ValueError("--local-linux-libs requires Debian/Ubuntu apt-get and dpkg-deb")
    with tempfile.TemporaryDirectory(prefix="gf-linux-libs-") as directory:
        scratch = Path(directory)
        subprocess.run(["apt-get", "download", "libnspr4", "libnss3"], cwd=scratch, check=True)
        extracted = scratch / "extracted"
        for package in sorted(scratch.glob("*.deb")):
            subprocess.run(["dpkg-deb", "--extract", str(package), str(extracted)], check=True)
        candidates = list(extracted.rglob("libnspr4.so"))
        if len(candidates) != 1 or not (candidates[0].parent / "libnss3.so").is_file():
            raise ValueError("Downloaded NSS/NSPR libraries have an unexpected layout")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidates[0].parent, destination, dirs_exist_ok=True)


def main():
    from validation.native import BROWSERS, LINUX_LIBRARIES, environment_identity

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "check"])
    parser.add_argument("--local-linux-libs", action="store_true",
                        help="Prepare project-local NSS/NSPR libraries on Debian/Ubuntu, without sudo")
    args = parser.parse_args()
    if args.local_linux_libs and args.action != "prepare":
        parser.error("--local-linux-libs is supported only with prepare")
    if args.action == "prepare":
        BROWSERS.mkdir(parents=True, mode=0o700, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"],
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS)}, check=True,
        )
    try:
        if args.local_linux_libs:
            prepare_linux_libraries(LINUX_LIBRARIES)
        print("Native OS sandbox and Chromium: OK\n" + environment_identity())
    except (OSError, ValueError, ImportError, subprocess.SubprocessError) as exc:
        print(f"Native validator is unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
